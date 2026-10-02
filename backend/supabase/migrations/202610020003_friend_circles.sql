-- Private circles share immutable food snapshots. All reads and writes use
-- narrow RPCs; direct table access cannot bypass circle membership.
create table public.friend_circles (
  id uuid primary key default gen_random_uuid(),
  name text not null check (char_length(trim(name)) between 1 and 80),
  owner_id uuid not null references auth.users(id) on delete cascade,
  created_at timestamptz not null default now()
);
create table public.circle_members (
  circle_id uuid not null references public.friend_circles(id) on delete cascade,
  user_id uuid not null references auth.users(id) on delete cascade,
  status text not null check (status in ('pending', 'accepted')),
  invited_by uuid references auth.users(id) on delete set null,
  created_at timestamptz not null default now(),
  primary key (circle_id, user_id)
);
create table public.circle_posts (
  id uuid primary key default gen_random_uuid(),
  circle_id uuid not null references public.friend_circles(id) on delete cascade,
  source_household_id uuid not null references public.households(id) on delete cascade,
  created_by uuid not null references auth.users(id) on delete cascade,
  kind text not null check (kind in ('week', 'recipe')),
  snapshot jsonb not null check (jsonb_typeof(snapshot) = 'object'),
  created_at timestamptz not null default now(),
  revoked_at timestamptz
);
create index circle_posts_feed on public.circle_posts(circle_id, created_at desc, id desc);
create table public.circle_comments (
  id uuid primary key default gen_random_uuid(),
  post_id uuid not null references public.circle_posts(id) on delete cascade,
  author_id uuid not null references auth.users(id) on delete cascade,
  body text not null check (char_length(trim(body)) between 1 and 2000),
  target_type text not null check (target_type in ('post', 'meal', 'recipe')),
  target_id uuid,
  created_at timestamptz not null default now()
);
create index circle_comments_post on public.circle_comments(post_id, created_at, id);
create table public.circle_recipe_saves (
  post_id uuid not null references public.circle_posts(id) on delete cascade,
  source_recipe_id uuid not null,
  target_household_id uuid not null references public.households(id) on delete cascade,
  copied_recipe_id uuid not null references public.recipes(id) on delete cascade,
  saved_by uuid not null references auth.users(id) on delete cascade,
  primary key(post_id, source_recipe_id, target_household_id)
);
-- A household keeps one active copy of a source recipe even if friends share
-- it in several posts. Archiving the copy permits saving a fresh one.
create unique index circle_recipe_one_active_copy on public.recipes
  (household_id, (source_snapshot->>'sourceRecipeId'))
  where source_type = 'shared' and archived_at is null and source_snapshot ? 'sourceRecipeId';
alter table public.friend_circles enable row level security;
alter table public.circle_members enable row level security;
alter table public.circle_posts enable row level security;
alter table public.circle_comments enable row level security;
alter table public.circle_recipe_saves enable row level security;
revoke all on public.friend_circles, public.circle_members, public.circle_posts,
  public.circle_comments, public.circle_recipe_saves from public, anon, authenticated;

create function public.is_accepted_circle_member(requested_circle_id uuid)
returns boolean language sql stable security definer set search_path = '' as $$
  select exists(select 1 from public.circle_members
    where circle_id = requested_circle_id and user_id = auth.uid() and status = 'accepted');
$$;
revoke all on function public.is_accepted_circle_member(uuid) from public, anon, authenticated;
grant execute on function public.is_accepted_circle_member(uuid) to authenticated;

-- Circle notifications are visible only while the recipient remains a member.
-- Pending invitations use a personal inbox entry without a circle scope.
alter table public.notifications add column circle_id uuid references public.friend_circles(id) on delete cascade;
drop policy notifications_read on public.notifications;
drop policy notifications_mark_read on public.notifications;
create policy notifications_read on public.notifications for select to authenticated
  using (recipient_id = auth.uid() and (expires_at is null or expires_at > now())
    and (household_id is null or public.can_read_notification(household_id))
    and (circle_id is null or public.is_accepted_circle_member(circle_id)));
create policy notifications_mark_read on public.notifications for update to authenticated
  using (recipient_id = auth.uid() and (expires_at is null or expires_at > now())
    and (household_id is null or public.can_read_notification(household_id))
    and (circle_id is null or public.is_accepted_circle_member(circle_id)))
  with check (recipient_id = auth.uid() and (expires_at is null or expires_at > now())
    and (household_id is null or public.can_read_notification(household_id))
    and (circle_id is null or public.is_accepted_circle_member(circle_id)));

create function public.circle_recipe_snapshot(requested_id uuid, requested_household_id uuid,
  include_archived boolean default false)
returns jsonb language sql stable security definer set search_path = '' as $$
  select jsonb_build_object('id', r.id, 'title', r.title, 'kind', r.kind,
    'description', r.description, 'servings', r.servings, 'activeMinutes', r.active_minutes,
    'totalMinutes', r.total_minutes, 'tags', r.tags, 'cuisines', r.cuisines,
    'eatingGoals', r.eating_goals, 'mealTypes', r.meal_types, 'diets', r.diets,
    'ingredients', r.ingredients, 'instructions', r.instructions, 'sourceUrl', r.source_url)
  from public.recipes r where r.id = requested_id and r.household_id = requested_household_id
    and (include_archived or r.archived_at is null);
$$;
revoke all on function public.circle_recipe_snapshot(uuid, uuid, boolean) from public, anon, authenticated;

create function public.create_circle(requested_name text)
returns jsonb language plpgsql security definer set search_path = '' as $$
declare row public.friend_circles%rowtype;
begin
  if auth.uid() is null then raise exception 'Authentication required'; end if;
  if char_length(trim(coalesce(requested_name, ''))) not between 1 and 80 then
    raise exception 'Enter a circle name of 1 to 80 characters';
  end if;
  insert into public.friend_circles(name, owner_id) values(trim(requested_name), auth.uid()) returning * into row;
  insert into public.circle_members(circle_id, user_id, status) values(row.id, auth.uid(), 'accepted');
  return jsonb_build_object('id', row.id, 'name', row.name, 'ownerId', row.owner_id, 'myStatus', 'accepted');
end;
$$;

create function public.list_my_circles()
returns jsonb language sql stable security definer set search_path = '' as $$
  select coalesce(jsonb_agg(jsonb_build_object(
    'id', c.id, 'name', c.name, 'ownerId', c.owner_id, 'myStatus', m.status,
    'members', case when c.owner_id = auth.uid() then
      (select coalesce(jsonb_agg(jsonb_build_object('userId', cm.user_id, 'email', u.email, 'status', cm.status)
        order by cm.created_at), '[]'::jsonb)
       from public.circle_members cm join auth.users u on u.id = cm.user_id where cm.circle_id = c.id)
      else '[]'::jsonb end
  ) order by c.created_at desc), '[]'::jsonb)
  from public.circle_members m join public.friend_circles c on c.id = m.circle_id
  where m.user_id = auth.uid();
$$;

create function public.invite_circle_friend(requested_circle_id uuid, requested_email text)
returns jsonb language plpgsql security definer set search_path = '' as $$
declare target_user uuid; clean_email text := lower(trim(coalesce(requested_email, '')));
begin
  if not exists(select 1 from public.friend_circles where id = requested_circle_id and owner_id = auth.uid()) then
    raise exception 'Circle is not available';
  end if;
  select id into target_user from auth.users where lower(email) = clean_email and email_confirmed_at is not null;
  if target_user is null or target_user = auth.uid() then raise exception 'Existing friend account was not found'; end if;
  if exists(select 1 from public.circle_members where circle_id = requested_circle_id and user_id = target_user) then
    raise exception 'Friend is already invited or a member';
  end if;
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

create function public.remove_circle_member(requested_circle_id uuid, requested_user_id uuid)
returns jsonb language plpgsql security definer set search_path = '' as $$
begin
  if requested_user_id = auth.uid() or not exists(select 1 from public.friend_circles
    where id = requested_circle_id and owner_id = auth.uid()) then raise exception 'Circle member was not found'; end if;
  delete from public.circle_members where circle_id = requested_circle_id and user_id = requested_user_id;
  if not found then raise exception 'Circle member was not found'; end if;
  update public.notifications set expires_at = now() where recipient_id = requested_user_id
    and event_key = 'circle-invite:' || requested_circle_id::text;
  return jsonb_build_object('removed', true);
end;
$$;

create function public.leave_circle(requested_circle_id uuid)
returns jsonb language plpgsql security definer set search_path = '' as $$
begin
  if exists(select 1 from public.friend_circles where id = requested_circle_id and owner_id = auth.uid()) then
    raise exception 'Circle owners cannot leave'; end if;
  delete from public.circle_members where circle_id = requested_circle_id and user_id = auth.uid() and status = 'accepted';
  if not found then raise exception 'Circle is not available to leave'; end if;
  return jsonb_build_object('left', true);
end;
$$;

create function public.respond_circle_invitation(requested_circle_id uuid, requested_accept boolean)
returns jsonb language plpgsql security definer set search_path = '' as $$
begin
  if not exists(select 1 from public.circle_members where circle_id = requested_circle_id
    and user_id = auth.uid() and status = 'pending') then raise exception 'Circle invitation was not found'; end if;
  if requested_accept then
    update public.circle_members set status = 'accepted' where circle_id = requested_circle_id and user_id = auth.uid();
  else
    delete from public.circle_members where circle_id = requested_circle_id and user_id = auth.uid();
  end if;
  update public.notifications set expires_at = now() where recipient_id = auth.uid()
    and event_key = 'circle-invite:' || requested_circle_id::text;
  return jsonb_build_object('circleId', requested_circle_id, 'accepted', requested_accept);
end;
$$;

create function public.circle_post_summary(p public.circle_posts)
returns jsonb language sql stable security definer set search_path = '' as $$
  select jsonb_build_object('id', p.id, 'circleId', p.circle_id, 'circleName', c.name,
    'kind', p.kind, 'createdBy', p.created_by, 'createdByName', split_part(u.email, '@', 1),
    'createdAt', p.created_at, 'snapshot', p.snapshot)
  from public.friend_circles c join auth.users u on u.id = p.created_by where c.id = p.circle_id;
$$;
revoke all on function public.circle_post_summary(public.circle_posts) from public, anon, authenticated;

create function public.list_shared_with_me(result_limit integer default 51, result_offset integer default 0,
  requested_kind text default null)
returns jsonb language plpgsql stable security definer set search_path = '' as $$
begin
  if result_limit is null or result_limit not between 1 and 101 or result_offset is null or result_offset < 0 or
    requested_kind not in ('week', 'recipe') and requested_kind is not null then
    raise exception 'Choose a valid share type, limit, and offset'; end if;
  return (
  select coalesce(jsonb_agg(public.circle_post_summary(p) order by p.created_at desc, p.id desc), '[]'::jsonb)
  from (select p.* from public.circle_posts p join public.circle_members m on m.circle_id = p.circle_id
    where m.user_id = auth.uid() and m.status = 'accepted' and p.revoked_at is null
      and (requested_kind is null or p.kind = requested_kind)
    order by p.created_at desc, p.id desc limit result_limit offset result_offset) p);
end;
$$;

create function public.get_circle_share(requested_share_id uuid)
returns jsonb language plpgsql stable security definer set search_path = '' as $$
declare p public.circle_posts%rowtype;
begin
  select * into p from public.circle_posts where id = requested_share_id and revoked_at is null
    and public.is_accepted_circle_member(circle_id);
  if not found then raise exception 'Shared item was not found'; end if;
  return public.circle_post_summary(p) || jsonb_build_object(
    'comments', (select coalesce(jsonb_agg(jsonb_build_object('id', c.id, 'authorId', c.author_id,
      'authorName', split_part(u.email, '@', 1),
      'body', c.body, 'targetType', c.target_type, 'targetId', c.target_id, 'createdAt', c.created_at)
      order by c.created_at, c.id), '[]'::jsonb) from public.circle_comments c
      join auth.users u on u.id = c.author_id where c.post_id = p.id),
    'savedRecipeIds', (select coalesce(jsonb_object_agg(r.source_snapshot->>'sourceRecipeId', r.id::text), '{}'::jsonb)
      from public.recipes r where r.household_id = public.active_household_id() and r.source_type = 'shared'
        and r.archived_at is null and r.source_snapshot->>'sourceRecipeId' in (
          select recipe->>'id' from jsonb_array_elements(case when p.kind = 'week'
            then p.snapshot->'recipes' else jsonb_build_array(p.snapshot->'recipe') end) recipe))
  );
end;
$$;

create function public.notify_circle_post(requested_post public.circle_posts)
returns void language sql security definer set search_path = '' as $$
  insert into public.notifications(recipient_id, circle_id, actor_id, kind, title, target_path, event_key)
  select m.user_id, requested_post.circle_id, auth.uid(), 'circle_share',
    case when requested_post.kind = 'week' then 'A friend shared a weekly meal plan' else 'A friend shared a recipe' end,
    '/app?view=circles&share=' || requested_post.id::text, 'circle-share:' || requested_post.id::text
  from public.circle_members m where m.circle_id = requested_post.circle_id and m.status = 'accepted'
    and m.user_id <> auth.uid() on conflict(recipient_id, event_key) do nothing;
$$;
revoke all on function public.notify_circle_post(public.circle_posts) from public, anon, authenticated;

create function public.share_recipe_to_circle(requested_circle_id uuid, requested_recipe_id uuid)
returns jsonb language plpgsql security definer set search_path = '' as $$
declare h uuid := public.active_household_id(); snap jsonb; p public.circle_posts%rowtype;
begin
  if not public.is_accepted_circle_member(requested_circle_id) then raise exception 'Circle is not available'; end if;
  snap := public.circle_recipe_snapshot(requested_recipe_id, h);
  if snap is null then raise exception 'Recipe was not found'; end if;
  insert into public.circle_posts(circle_id, source_household_id, created_by, kind, snapshot)
    values(requested_circle_id, h, auth.uid(), 'recipe', jsonb_build_object('recipe', snap)) returning * into p;
  perform public.notify_circle_post(p);
  return public.circle_post_summary(p);
end;
$$;

create function public.share_week_to_circle(requested_circle_id uuid, requested_week_start text)
returns jsonb language plpgsql security definer set search_path = '' as $$
declare h uuid := public.active_household_id(); plan public.meal_plans%rowtype;
  entries jsonb; recipes jsonb; p public.circle_posts%rowtype;
begin
  if not public.is_accepted_circle_member(requested_circle_id) then raise exception 'Circle is not available'; end if;
  select * into plan from public.meal_plans where household_id = h and week_start = requested_week_start::date
    order by version desc limit 1;
  if not found then raise exception 'Weekly plan was not found'; end if;
  select coalesce(jsonb_agg(jsonb_build_object('id', e.id, 'date', e.planned_for, 'slot', e.slot,
    'slotName', e.slot_name, 'meal', e.title, 'servings', e.servings, 'notes', e.notes,
    'components', coalesce((select jsonb_agg(jsonb_build_object('name', x.value->>'name',
      'quantity', x.value->'quantity', 'unit', x.value->>'unit', 'source', x.value->>'source',
      'action', x.value->>'action', 'recipeId', coalesce(x.value->>'recipeId',
        (select task->>'recipeId' from jsonb_array_elements(plan.tasks) task
         where task->>'id' = x.value->>'taskId' limit 1))) order by x.ordinality)
      from jsonb_array_elements(e.components) with ordinality x(value, ordinality)), '[]'::jsonb))
    order by e.planned_for, e.position), '[]'::jsonb) into entries
  from public.meal_plan_entries e where e.meal_plan_id = plan.id;
  select coalesce(jsonb_agg(public.circle_recipe_snapshot(r.id, h, true) order by lower(r.title), r.id), '[]'::jsonb)
    into recipes from public.recipes r where r.household_id = h and r.id in (
      select distinct (component->>'recipeId')::uuid from jsonb_array_elements(entries) entry,
        jsonb_array_elements(entry->'components') component
      where component->>'recipeId' is not null and component->>'recipeId' <> '');
  insert into public.circle_posts(circle_id, source_household_id, created_by, kind, snapshot)
    values(requested_circle_id, h, auth.uid(), 'week',
      jsonb_build_object('weekStart', plan.week_start, 'entries', entries, 'recipes', recipes)) returning * into p;
  perform public.notify_circle_post(p);
  return public.circle_post_summary(p);
end;
$$;

create function public.comment_on_circle_share(requested_share_id uuid, requested_body text,
  requested_target_type text default 'post', requested_target_id uuid default null)
returns jsonb language plpgsql security definer set search_path = '' as $$
declare p public.circle_posts%rowtype; c public.circle_comments%rowtype; valid_target boolean;
begin
  select * into p from public.circle_posts where id = requested_share_id and revoked_at is null
    and public.is_accepted_circle_member(circle_id);
  if not found then raise exception 'Shared item was not found'; end if;
  if char_length(trim(coalesce(requested_body, ''))) not between 1 and 2000 then
    raise exception 'Enter a comment of 1 to 2000 characters'; end if;
  valid_target := case requested_target_type
    when 'post' then requested_target_id is null
    when 'meal' then p.kind = 'week' and exists(select 1 from jsonb_array_elements(p.snapshot->'entries') e
      where e->>'id' = requested_target_id::text)
    when 'recipe' then exists(select 1 from jsonb_array_elements(
      case when p.kind = 'week' then p.snapshot->'recipes' else jsonb_build_array(p.snapshot->'recipe') end) r
      where r->>'id' = requested_target_id::text)
    else false end;
  if not coalesce(valid_target, false) then raise exception 'Comment target was not found'; end if;
  insert into public.circle_comments(post_id, author_id, body, target_type, target_id)
    values(p.id, auth.uid(), trim(requested_body), requested_target_type, requested_target_id) returning * into c;
  insert into public.notifications(recipient_id, circle_id, actor_id, kind, title, target_path, event_key)
    select m.user_id, p.circle_id, auth.uid(), 'circle_comment', 'A friend commented on a meal share',
      '/app?view=circles&share=' || p.id::text, 'circle-comment:' || c.id::text
    from public.circle_members m where m.circle_id = p.circle_id and m.status = 'accepted'
      and m.user_id <> auth.uid() on conflict(recipient_id, event_key) do nothing;
  return jsonb_build_object('id', c.id, 'authorId', c.author_id,
    'authorName', (select split_part(email, '@', 1) from auth.users where id = c.author_id), 'body', c.body,
    'targetType', c.target_type, 'targetId', c.target_id, 'createdAt', c.created_at);
end;
$$;

create function public.save_circle_recipe(requested_share_id uuid, requested_recipe_id uuid)
returns jsonb language plpgsql security definer set search_path = '' as $$
declare p public.circle_posts%rowtype; h uuid := public.active_household_id(); snap jsonb;
  existing uuid; copied uuid;
begin
  if h is null then raise exception 'Household required'; end if;
  select * into p from public.circle_posts where id = requested_share_id and revoked_at is null
    and public.is_accepted_circle_member(circle_id) for update;
  if not found then raise exception 'Shared item was not found'; end if;
  select value into snap from jsonb_array_elements(case when p.kind = 'week' then p.snapshot->'recipes'
    else jsonb_build_array(p.snapshot->'recipe') end) where value->>'id' = requested_recipe_id::text limit 1;
  if snap is null then raise exception 'Shared recipe was not found'; end if;
  perform 1 from public.households where id = h for update;
  select r.id into existing from public.recipes r where r.household_id = h and r.source_type = 'shared'
    and r.archived_at is null and r.source_snapshot->>'sourceRecipeId' = requested_recipe_id::text;
  delete from public.circle_recipe_saves where post_id = p.id and source_recipe_id = requested_recipe_id
    and target_household_id = h;
  if existing is not null then
    insert into public.circle_recipe_saves(post_id, source_recipe_id, target_household_id, copied_recipe_id, saved_by)
      values(p.id, requested_recipe_id, h, existing, auth.uid());
    return jsonb_build_object('recipeId', existing, 'alreadySaved', true);
  end if;
  insert into public.recipes(household_id, kind, title, description, servings, active_minutes,
    total_minutes, tags, cuisines, eating_goals, meal_types, diets, ingredients, instructions,
    source_type, source_url, source_snapshot)
  values(h, snap->>'kind', snap->>'title', coalesce(snap->>'description', ''),
    coalesce((snap->>'servings')::numeric, 4), (snap->>'activeMinutes')::integer,
    (snap->>'totalMinutes')::integer, coalesce(array(select jsonb_array_elements_text(snap->'tags')), '{}'::text[]),
    coalesce(array(select jsonb_array_elements_text(snap->'cuisines')), '{}'::text[]),
    coalesce(array(select jsonb_array_elements_text(snap->'eatingGoals')), '{}'::text[]),
    coalesce(array(select jsonb_array_elements_text(snap->'mealTypes')), '{}'::text[]),
    coalesce(array(select jsonb_array_elements_text(snap->'diets')), '{}'::text[]),
    coalesce(snap->'ingredients', '[]'::jsonb), coalesce(snap->'instructions', '[]'::jsonb),
    'shared', snap->>'sourceUrl', jsonb_build_object('circleShareId', p.id, 'sourceRecipeId', requested_recipe_id))
    returning id into copied;
  insert into public.circle_recipe_saves(post_id, source_recipe_id, target_household_id, copied_recipe_id, saved_by)
    values(p.id, requested_recipe_id, h, copied, auth.uid());
  return jsonb_build_object('recipeId', copied, 'alreadySaved', false);
end;
$$;

create function public.revoke_circle_share(requested_share_id uuid)
returns jsonb language plpgsql security definer set search_path = '' as $$
begin
  update public.circle_posts set revoked_at = coalesce(revoked_at, now())
    where id = requested_share_id and created_by = auth.uid();
  if not found then raise exception 'Shared item was not found'; end if;
  return jsonb_build_object('revoked', true);
end;
$$;

revoke all on function public.create_circle(text), public.list_my_circles(),
  public.invite_circle_friend(uuid, text), public.respond_circle_invitation(uuid, boolean),
  public.remove_circle_member(uuid, uuid), public.leave_circle(uuid),
  public.list_shared_with_me(integer, integer, text), public.get_circle_share(uuid), public.share_recipe_to_circle(uuid, uuid),
  public.share_week_to_circle(uuid, text), public.comment_on_circle_share(uuid, text, text, uuid),
  public.save_circle_recipe(uuid, uuid), public.revoke_circle_share(uuid) from public, anon;
grant execute on function public.create_circle(text), public.list_my_circles(),
  public.invite_circle_friend(uuid, text), public.respond_circle_invitation(uuid, boolean),
  public.remove_circle_member(uuid, uuid), public.leave_circle(uuid),
  public.list_shared_with_me(integer, integer, text), public.get_circle_share(uuid), public.share_recipe_to_circle(uuid, uuid),
  public.share_week_to_circle(uuid, text), public.comment_on_circle_share(uuid, text, text, uuid),
  public.save_circle_recipe(uuid, uuid), public.revoke_circle_share(uuid) to authenticated;
