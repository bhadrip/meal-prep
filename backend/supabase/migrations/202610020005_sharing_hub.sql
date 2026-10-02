-- One-to-one shares reuse the snapshot, thread, and notification access model.
-- Each direct share has exactly one original post and a frozen two-person audience.
alter table public.friend_circles add column room_type text not null default 'group'
  check (room_type in ('group', 'direct'));

create or replace function public.list_my_circles()
returns jsonb language sql stable security definer set search_path = '' as $$
  select coalesce(jsonb_agg(jsonb_build_object(
    'id', c.id, 'name', c.name, 'ownerId', c.owner_id, 'myStatus', m.status,
    'memberNames', case when m.status = 'accepted' then
      (select coalesce(jsonb_agg(split_part(u.email, '@', 1) order by cm.created_at), '[]'::jsonb)
       from public.circle_members cm join auth.users u on u.id = cm.user_id
       where cm.circle_id = c.id and cm.status = 'accepted') else '[]'::jsonb end,
    'memberCount', case when m.status = 'accepted' then
      (select count(*) from public.circle_members cm where cm.circle_id = c.id and cm.status = 'accepted') else 0 end,
    'audience', case when m.status = 'accepted' then
      (select coalesce(jsonb_agg(jsonb_build_object('userId', cm.user_id,
        'membershipId', cm.membership_id, 'name', split_part(u.email, '@', 1)) order by u.email), '[]'::jsonb)
       from public.circle_members cm join auth.users u on u.id = cm.user_id
       where cm.circle_id = c.id and cm.status = 'accepted') else '[]'::jsonb end,
    'members', case when c.owner_id = auth.uid() then
      (select coalesce(jsonb_agg(jsonb_build_object('userId', cm.user_id, 'email', u.email, 'status', cm.status)
        order by cm.created_at), '[]'::jsonb)
       from public.circle_members cm join auth.users u on u.id = cm.user_id where cm.circle_id = c.id)
      else '[]'::jsonb end
  ) order by c.created_at desc), '[]'::jsonb)
  from public.circle_members m join public.friend_circles c on c.id = m.circle_id
  where m.user_id = auth.uid() and c.room_type = 'group';
$$;

create or replace function public.circle_post_summary(p public.circle_posts)
returns jsonb language sql stable security definer set search_path = '' as $$
  select jsonb_build_object('id', p.id, 'circleId', p.circle_id, 'circleName', c.name,
    'roomType', c.room_type,
    'directPeerName', case when c.room_type = 'direct' then
      (select split_part(peer.email, '@', 1) from public.circle_members cm
        join auth.users peer on peer.id = cm.user_id
        where cm.circle_id = c.id and cm.user_id <> auth.uid() limit 1) else null end,
    'kind', p.kind, 'createdBy', p.created_by, 'createdByName', split_part(u.email, '@', 1),
    'createdAt', p.created_at, 'snapshot', p.snapshot,
    'commentCount', (select count(*) from public.circle_comments co
      where co.post_id = p.id and co.deleted_at is null))
  from public.friend_circles c join auth.users u on u.id = p.created_by where c.id = p.circle_id;
$$;

create function public.list_direct_shares(result_limit integer default 51, result_offset integer default 0)
returns jsonb language plpgsql stable security definer set search_path = '' as $$
begin
  if result_limit is null or result_limit not between 1 and 101 or result_offset is null or result_offset < 0 then
    raise exception 'Choose a valid limit and offset'; end if;
  return (select coalesce(jsonb_agg(public.circle_post_summary(p) order by p.created_at desc, p.id desc), '[]'::jsonb)
    from (select p.* from public.circle_posts p
      join public.friend_circles f on f.id = p.circle_id and f.room_type = 'direct'
      join public.circle_members m on m.circle_id = p.circle_id and m.user_id = auth.uid() and m.status = 'accepted'
      join public.circle_post_recipients a on a.post_id = p.id and a.user_id = m.user_id
        and a.membership_id = m.membership_id
      where p.revoked_at is null order by p.created_at desc, p.id desc
      limit result_limit offset result_offset) p);
end;
$$;

create function public.share_direct(requested_email text, requested_kind text,
  requested_recipe_id uuid default null, requested_week_start text default null)
returns jsonb language plpgsql security definer set search_path = '' as $$
declare target_user uuid; room_id uuid; post jsonb; clean_email text := lower(trim(coalesce(requested_email, '')));
begin
  if auth.uid() is null or public.active_household_id() is null then raise exception 'Household required'; end if;
  if requested_kind not in ('recipe', 'week') then raise exception 'Choose a recipe or weekly plan'; end if;
  if (requested_kind = 'recipe' and (requested_recipe_id is null or requested_week_start is not null))
    or (requested_kind = 'week' and (requested_week_start is null or requested_recipe_id is not null)) then
    raise exception 'Choose one item to share'; end if;
  select id into target_user from auth.users where lower(email) = clean_email and email_confirmed_at is not null;
  if target_user is null or target_user = auth.uid() then raise exception 'Existing friend account was not found'; end if;
  perform 1 from auth.users where id = auth.uid() for update;
  if (select count(*) from public.circle_posts p join public.friend_circles f on f.id = p.circle_id
      where f.room_type = 'direct' and p.created_by = auth.uid()
        and p.created_at >= now() - interval '1 day') >= 20 then raise exception 'Daily share limit reached'; end if;
  insert into public.friend_circles(name, owner_id, room_type)
    values('Direct share', auth.uid(), 'direct') returning id into room_id;
  insert into public.circle_members(circle_id, user_id, status)
    values(room_id, auth.uid(), 'accepted'), (room_id, target_user, 'accepted');
  if requested_kind = 'recipe' then
    post := public.share_recipe_to_circle(room_id, requested_recipe_id);
  else
    post := public.share_week_to_circle(room_id, requested_week_start);
  end if;
  return post;
end;
$$;

-- Direct rooms cannot be expanded into groups by a second client.
create or replace function public.invite_circle_friend(requested_circle_id uuid, requested_email text)
returns jsonb language plpgsql security definer set search_path = '' as $$
declare target_user uuid; clean_email text := lower(trim(coalesce(requested_email, '')));
begin
  if not exists(select 1 from public.friend_circles where id = requested_circle_id
      and owner_id = auth.uid() and room_type = 'group') then
    raise exception 'Circle is not available'; end if;
  select id into target_user from auth.users where lower(email) = clean_email and email_confirmed_at is not null;
  if target_user is null or target_user = auth.uid() then raise exception 'Existing friend account was not found'; end if;
  if exists(select 1 from public.circle_members where circle_id = requested_circle_id and user_id = target_user) then
    raise exception 'Friend is already invited or a member'; end if;
  perform 1 from public.friend_circles where id = requested_circle_id for update;
  if (select count(*) from public.circle_members where circle_id = requested_circle_id) >= 25 then
    raise exception 'Circle member limit reached'; end if;
  insert into public.circle_members(circle_id, user_id, status, invited_by)
    values(requested_circle_id, target_user, 'pending', auth.uid());
  insert into public.notifications(recipient_id, actor_id, kind, title, target_path, event_key)
    values(target_user, auth.uid(), 'circle_invitation', 'A friend invited you to a meal circle',
      '/app?view=circles', 'circle-invite:' || requested_circle_id::text)
    on conflict(recipient_id, event_key) do update set actor_id = excluded.actor_id,
      title = excluded.title, expires_at = null, read_at = null, created_at = now();
  return jsonb_build_object('circleId', requested_circle_id, 'email', clean_email, 'status', 'pending');
end;
$$;

revoke all on function public.list_direct_shares(integer, integer), public.share_direct(text, text, uuid, text) from public, anon;
grant execute on function public.list_direct_shares(integer, integer), public.share_direct(text, text, uuid, text) to authenticated;

-- Public links are bearer capabilities. The creator alone may retrieve new
-- links later; older hash-only links remain revocable but cannot be recovered.
alter table public.share_links drop constraint share_links_artifact_type_check;
alter table public.share_links add constraint share_links_artifact_type_check check (artifact_type in ('recipe', 'meal'));
alter table public.share_links add column source_meal_id uuid references public.meals(id) on delete set null;
alter table public.share_links add column owner_token text;

create or replace function public.create_recipe_share(requested_recipe_id uuid, requested_expires_at timestamptz default null)
returns jsonb language plpgsql security definer set search_path = pg_catalog, extensions, public as $$
declare r public.recipes%rowtype; raw_token text; new_id uuid;
begin
  if auth.uid() is null then raise exception 'authentication required'; end if;
  if requested_expires_at is not null and requested_expires_at <= now() then raise exception 'expiration must be in the future'; end if;
  select * into r from public.recipes where id = requested_recipe_id and archived_at is null
    and public.is_household_member(household_id);
  if not found then raise exception 'recipe not found'; end if;
  raw_token := encode(gen_random_bytes(32), 'hex');
  insert into public.share_links(household_id, created_by, artifact_type, source_recipe_id,
    snapshot, token_hash, owner_token, expires_at)
  values(r.household_id, auth.uid(), 'recipe', r.id,
    public.circle_recipe_snapshot(r.id, r.household_id), digest(raw_token, 'sha256'), raw_token, requested_expires_at)
  returning id into new_id;
  return jsonb_build_object('id', new_id, 'token', raw_token, 'expiresAt', requested_expires_at);
end;
$$;

create function public.create_meal_share(requested_meal_id uuid, requested_expires_at timestamptz default null)
returns jsonb language plpgsql security definer set search_path = pg_catalog, extensions, public as $$
declare m public.meals%rowtype; raw_token text; new_id uuid; snap jsonb;
begin
  if auth.uid() is null then raise exception 'authentication required'; end if;
  if requested_expires_at is not null and requested_expires_at <= now() then raise exception 'expiration must be in the future'; end if;
  select * into m from public.meals where id = requested_meal_id and archived_at is null
    and public.is_household_member(household_id);
  if not found then raise exception 'meal not found'; end if;
  snap := jsonb_build_object('name', m.name, 'servings', m.servings, 'notes', m.notes,
    'components', (select coalesce(jsonb_agg(jsonb_build_object('name', c.value->>'name',
      'quantity', c.value->'quantity', 'unit', c.value->>'unit', 'source', c.value->>'source',
      'action', c.value->>'action', 'recipeId', c.value->>'recipeId') order by c.ordinality), '[]'::jsonb)
      from jsonb_array_elements(m.components) with ordinality c(value, ordinality)),
    'recipes', (select coalesce(jsonb_agg(public.circle_recipe_snapshot(r.id, m.household_id, true)
       order by r.title), '[]'::jsonb) from public.recipes r where r.household_id = m.household_id
       and r.id in (select (c->>'recipeId')::uuid from jsonb_array_elements(m.components) c
         where c->>'recipeId' is not null)));
  raw_token := encode(gen_random_bytes(32), 'hex');
  insert into public.share_links(household_id, created_by, artifact_type, source_meal_id,
    snapshot, token_hash, owner_token, expires_at)
  values(m.household_id, auth.uid(), 'meal', m.id, snap,
    digest(raw_token, 'sha256'), raw_token, requested_expires_at)
  returning id into new_id;
  return jsonb_build_object('id', new_id, 'token', raw_token, 'expiresAt', requested_expires_at);
end;
$$;

create function public.list_public_shares()
returns jsonb language sql stable security definer set search_path = '' as $$
  select coalesce(jsonb_agg(jsonb_build_object('id', s.id, 'kind', s.artifact_type,
    'sourceId', coalesce(s.source_recipe_id, s.source_meal_id),
    'title', coalesce(s.snapshot->>'title', s.snapshot->>'name'), 'createdAt', s.created_at,
    'expiresAt', s.expires_at, 'revokedAt', s.revoked_at,
    'token', case when s.revoked_at is null and (s.expires_at is null or s.expires_at > now())
      then s.owner_token else null end) order by s.created_at desc), '[]'::jsonb)
  from public.share_links s where s.created_by = auth.uid() and public.is_household_member(s.household_id);
$$;

create function public.revoke_public_share(requested_share_id uuid)
returns boolean language plpgsql security definer set search_path = '' as $$
begin
  if auth.uid() is null then raise exception 'authentication required'; end if;
  update public.share_links s set revoked_at = coalesce(s.revoked_at, now()), owner_token = null
    where s.id = requested_share_id and s.created_by = auth.uid()
      and public.is_household_member(s.household_id);
  return found;
end;
$$;

create or replace function public.revoke_recipe_share(requested_share_id uuid)
returns boolean language sql security definer set search_path = '' as $$
  select public.revoke_public_share(requested_share_id);
$$;

create function public.read_shared_food(raw_token text)
returns jsonb language sql stable security definer set search_path = pg_catalog, extensions, public as $$
  select jsonb_build_object('id', s.id, 'kind', s.artifact_type,
    'recipe', case when s.artifact_type = 'recipe' then s.snapshot else null end,
    'meal', case when s.artifact_type = 'meal' then s.snapshot else null end,
    'createdAt', s.created_at)
  from public.share_links s where s.token_hash = digest(raw_token, 'sha256')
    and s.revoked_at is null and (s.expires_at is null or s.expires_at > now());
$$;
revoke all on function public.create_meal_share(uuid, timestamptz), public.list_public_shares(),
  public.revoke_public_share(uuid), public.read_shared_food(text) from public, anon, authenticated;
grant execute on function public.create_meal_share(uuid, timestamptz), public.list_public_shares(),
  public.revoke_public_share(uuid) to authenticated;
grant execute on function public.read_shared_food(text) to anon, authenticated;
