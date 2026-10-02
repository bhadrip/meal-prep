-- The conversation composer can attach a saved food snapshot and mention only
-- people who can read that exact conversation.
alter table public.circle_posts drop constraint circle_posts_kind_check;
alter table public.circle_posts add constraint circle_posts_kind_check
  check (kind in ('week', 'recipe', 'meal', 'message'));
alter table public.circle_comments add column mentioned_user_ids uuid[] not null default '{}'::uuid[];
alter table public.circle_posts add column mentioned_user_ids uuid[] not null default '{}'::uuid[];

create function public.circle_mention_candidates(requested_circle_id uuid)
returns jsonb language sql stable security definer set search_path = '' as $$
  select case when public.is_accepted_circle_member(requested_circle_id) then
    (select coalesce(jsonb_agg(jsonb_build_object('id', m.user_id,
      'name', split_part(u.email, '@', 1)) order by u.email), '[]'::jsonb)
      from public.circle_members m join auth.users u on u.id = m.user_id
      where m.circle_id = requested_circle_id and m.status = 'accepted')
    else '[]'::jsonb end;
$$;
revoke all on function public.circle_mention_candidates(uuid) from public, anon;
grant execute on function public.circle_mention_candidates(uuid) to authenticated;

create function public.valid_circle_mentions(requested_circle_id uuid, requested_ids uuid[])
returns boolean language sql stable security definer set search_path = '' as $$
  select coalesce(cardinality(requested_ids), 0) <= 25
    and not exists(select 1 from unnest(coalesce(requested_ids, '{}'::uuid[])) id
      where id is null or not exists(select 1 from public.circle_members m
        where m.circle_id = requested_circle_id and m.user_id = id and m.status = 'accepted'));
$$;
revoke all on function public.valid_circle_mentions(uuid, uuid[]) from public, anon, authenticated;

create or replace function public.notify_circle_post(requested_post public.circle_posts)
returns void language sql security definer set search_path = '' as $$
  insert into public.notifications(recipient_id, circle_id, actor_id, kind, title, target_path, event_key)
  select a.user_id, requested_post.circle_id, auth.uid(),
    case when a.user_id = any(requested_post.mentioned_user_ids) then 'circle_mention'
      when requested_post.kind = 'message' then 'circle_message' else 'circle_share' end,
    case when a.user_id = any(requested_post.mentioned_user_ids) then 'A friend mentioned you in a meal circle'
      when requested_post.kind = 'week' then 'A friend shared a weekly meal plan'
      when requested_post.kind = 'recipe' then 'A friend shared a recipe'
      when requested_post.kind = 'meal' then 'A friend shared a saved meal'
      else 'A friend sent a circle message' end,
    '/app?view=circles&share=' || requested_post.id::text, 'circle-share:' || requested_post.id::text
  from public.circle_post_recipients a where a.post_id = requested_post.id
    and a.user_id <> auth.uid() on conflict(recipient_id, event_key) do nothing;
$$;

-- Replace the two-argument function; defaults preserve existing callers.
drop function public.send_circle_message(uuid, text);
create function public.send_circle_message(requested_circle_id uuid, requested_body text,
  requested_attachment_kind text default null, requested_attachment_id uuid default null,
  requested_mention_ids uuid[] default '{}'::uuid[], requested_audience text[] default null)
returns jsonb language plpgsql security definer set search_path = '' as $$
declare h uuid := public.active_household_id(); p public.circle_posts%rowtype;
  meal_row public.meals%rowtype; snap jsonb; actual_audience text[];
  clean_body text := trim(coalesce(requested_body, ''));
begin
  if char_length(clean_body) > 2000 or (clean_body = '' and requested_attachment_kind is null) then
    raise exception 'Enter a message of 1 to 2000 characters'; end if;
  if requested_attachment_kind not in ('recipe', 'meal') and requested_attachment_kind is not null
    or (requested_attachment_kind is null) <> (requested_attachment_id is null) then
    raise exception 'Choose one recipe or meal attachment'; end if;
  if h is null then raise exception 'Household required'; end if;
  perform 1 from public.friend_circles where id = requested_circle_id and room_type = 'group' for update;
  if not found or not public.is_accepted_circle_member(requested_circle_id) then raise exception 'Circle is not available'; end if;
  if requested_audience is not null then
    select coalesce(array_agg(m.user_id::text || ':' || m.membership_id::text order by m.user_id), '{}'::text[])
      into actual_audience from public.circle_members m
      where m.circle_id = requested_circle_id and m.status = 'accepted';
    if actual_audience is distinct from requested_audience then raise exception 'Circle audience changed'; end if;
  end if;
  if not public.valid_circle_mentions(requested_circle_id, requested_mention_ids) then
    raise exception 'Mentioned friend is not in this circle'; end if;
  if (select count(*) from public.circle_posts where circle_id = requested_circle_id and created_by = auth.uid()
      and created_at >= now() - interval '1 day') >= 100 then raise exception 'Daily share limit reached'; end if;
  if requested_attachment_kind = 'recipe' then
    snap := public.circle_recipe_snapshot(requested_attachment_id, h);
    if snap is null then raise exception 'Recipe was not found'; end if;
    snap := jsonb_build_object('recipe', snap, 'caption', clean_body);
  elsif requested_attachment_kind = 'meal' then
    select * into meal_row from public.meals where id = requested_attachment_id
      and household_id = h and archived_at is null;
    if not found then raise exception 'Meal was not found'; end if;
    snap := jsonb_build_object('meal', jsonb_build_object('id', meal_row.id, 'name', meal_row.name,
      'servings', meal_row.servings, 'notes', meal_row.notes,
      'components', (select coalesce(jsonb_agg(jsonb_build_object('name', c.value->>'name',
        'quantity', c.value->'quantity', 'unit', c.value->>'unit', 'source', c.value->>'source',
        'action', c.value->>'action', 'recipeId', c.value->>'recipeId') order by c.ordinality), '[]'::jsonb)
        from jsonb_array_elements(meal_row.components) with ordinality c(value, ordinality))),
      'recipes', (select coalesce(jsonb_agg(public.circle_recipe_snapshot(r.id, h, true) order by r.title), '[]'::jsonb)
        from public.recipes r where r.household_id = h and r.id in
          (select (c->>'recipeId')::uuid from jsonb_array_elements(meal_row.components) c where c->>'recipeId' is not null)),
      'caption', clean_body);
  else
    snap := jsonb_build_object('text', clean_body);
  end if;
  insert into public.circle_posts(circle_id, source_household_id, created_by, kind, snapshot, mentioned_user_ids)
    values(requested_circle_id, h, auth.uid(), coalesce(requested_attachment_kind, 'message'), snap,
      coalesce(requested_mention_ids, '{}'::uuid[])) returning * into p;
  perform public.capture_circle_audience(p);
  perform public.notify_circle_post(p);
  return public.circle_post_summary(p);
end;
$$;
revoke all on function public.send_circle_message(uuid, text, text, uuid, uuid[], text[]) from public, anon;
grant execute on function public.send_circle_message(uuid, text, text, uuid, uuid[], text[]) to authenticated;

create function public.share_week_with_audience(requested_circle_id uuid,
  requested_week_start text, requested_audience text[])
returns jsonb language plpgsql security definer set search_path = '' as $$
declare actual_audience text[];
begin
  if requested_audience is null then raise exception 'Review the circle audience'; end if;
  perform 1 from public.friend_circles where id = requested_circle_id and room_type = 'group' for update;
  if not found or not public.is_accepted_circle_member(requested_circle_id) then raise exception 'Circle is not available'; end if;
  select coalesce(array_agg(m.user_id::text || ':' || m.membership_id::text order by m.user_id), '{}'::text[])
    into actual_audience from public.circle_members m
    where m.circle_id = requested_circle_id and m.status = 'accepted';
  if actual_audience is distinct from requested_audience then raise exception 'Circle audience changed'; end if;
  return public.share_week_to_circle(requested_circle_id, requested_week_start);
end;
$$;
revoke all on function public.share_week_with_audience(uuid, text, text[]) from public, anon;
grant execute on function public.share_week_with_audience(uuid, text, text[]) to authenticated;

-- Keep the existing thread behavior and add exact mention metadata and targeted
-- notification titles, without allowing cross-circle user IDs.
drop function public.comment_on_circle_share(uuid, text, text, uuid);
create or replace function public.comment_on_circle_share(requested_share_id uuid, requested_body text,
  requested_target_type text default 'post', requested_target_id uuid default null,
  requested_mention_ids uuid[] default '{}'::uuid[])
returns jsonb language plpgsql security definer set search_path = '' as $$
declare p public.circle_posts%rowtype; c public.circle_comments%rowtype; valid_target boolean;
begin
  perform 1 from public.friend_circles where id =
    (select circle_id from public.circle_posts where id = requested_share_id) for update;
  select * into p from public.circle_posts cp where cp.id = requested_share_id and cp.revoked_at is null
    and public.is_accepted_circle_member(cp.circle_id)
    and exists(select 1 from public.circle_post_recipients a join public.circle_members m
      on m.circle_id = cp.circle_id and m.user_id = a.user_id and m.membership_id = a.membership_id
      where a.post_id = requested_share_id and a.user_id = auth.uid()) for update;
  if not found then raise exception 'Shared item was not found'; end if;
  if char_length(trim(coalesce(requested_body, ''))) not between 1 and 2000 then
    raise exception 'Enter a comment of 1 to 2000 characters'; end if;
  if not public.valid_circle_mentions(p.circle_id, requested_mention_ids)
    or exists(select 1 from unnest(coalesce(requested_mention_ids, '{}'::uuid[])) id
      where not exists(select 1 from public.circle_post_recipients a
        join public.circle_members m on m.circle_id = p.circle_id and m.user_id = a.user_id
          and m.membership_id = a.membership_id and m.status = 'accepted'
        where a.post_id = p.id and a.user_id = id)) then
    raise exception 'Mentioned friend is not in this circle'; end if;
  if (select count(*) from public.circle_comments where post_id = requested_share_id and author_id = auth.uid()
      and created_at >= now() - interval '1 hour') >= 30 then raise exception 'Comment rate limit reached'; end if;
  valid_target := case requested_target_type
    when 'post' then requested_target_id is null
    when 'meal' then p.kind = 'week' and exists(select 1 from jsonb_array_elements(p.snapshot->'entries') e
      where e->>'id' = requested_target_id::text)
    when 'recipe' then exists(select 1 from jsonb_array_elements(
      case when p.kind in ('week', 'meal') then p.snapshot->'recipes'
        when p.kind = 'recipe' then jsonb_build_array(p.snapshot->'recipe') else '[]'::jsonb end) r
      where r->>'id' = requested_target_id::text)
    else false end;
  if not coalesce(valid_target, false) then raise exception 'Comment target was not found'; end if;
  insert into public.circle_comments(post_id, author_id, body, target_type, target_id, mentioned_user_ids)
    values(p.id, auth.uid(), trim(requested_body), requested_target_type, requested_target_id,
      coalesce(requested_mention_ids, '{}'::uuid[])) returning * into c;
  insert into public.notifications(recipient_id, circle_id, actor_id, kind, title, target_path, event_key)
    select m.user_id, p.circle_id, auth.uid(),
      case when m.user_id = any(c.mentioned_user_ids) then 'circle_mention' else 'circle_comment' end,
      case when m.user_id = any(c.mentioned_user_ids) then 'A friend mentioned you in a meal thread'
        else 'A friend replied to a meal share' end,
      '/app?view=circles&share=' || p.id::text, 'circle-comment:' || c.id::text
    from public.circle_members m join public.circle_post_recipients a on a.post_id = p.id and a.user_id = m.user_id
      and a.membership_id = m.membership_id
    where m.circle_id = p.circle_id and m.status = 'accepted'
      and m.user_id <> auth.uid() on conflict(recipient_id, event_key) do nothing;
  return jsonb_build_object('id', c.id, 'authorId', c.author_id,
    'authorName', (select split_part(email, '@', 1) from auth.users where id = c.author_id), 'body', c.body,
    'targetType', c.target_type, 'targetId', c.target_id, 'createdAt', c.created_at,
    'mentionedUserIds', c.mentioned_user_ids);
end;
$$;
revoke all on function public.comment_on_circle_share(uuid, text, text, uuid, uuid[]) from public, anon;
grant execute on function public.comment_on_circle_share(uuid, text, text, uuid, uuid[]) to authenticated;

create or replace function public.get_circle_share(requested_share_id uuid)
returns jsonb language plpgsql stable security definer set search_path = '' as $$
declare p public.circle_posts%rowtype;
begin
  select * into p from public.circle_posts cp where cp.id = requested_share_id and cp.revoked_at is null
    and public.is_accepted_circle_member(cp.circle_id)
    and exists(select 1 from public.circle_post_recipients a join public.circle_members m
      on m.circle_id = cp.circle_id and m.user_id = a.user_id and m.membership_id = a.membership_id
      where a.post_id = requested_share_id and a.user_id = auth.uid());
  if not found then raise exception 'Shared item was not found'; end if;
  return public.circle_post_summary(p) || jsonb_build_object(
    'recipientUserIds', (select coalesce(jsonb_agg(a.user_id), '[]'::jsonb)
      from public.circle_post_recipients a join public.circle_members m
        on m.circle_id = p.circle_id and m.user_id = a.user_id
          and m.membership_id = a.membership_id and m.status = 'accepted'
      where a.post_id = p.id),
    'comments', (select coalesce(jsonb_agg(jsonb_build_object('id', c.id, 'authorId', c.author_id,
      'authorName', split_part(u.email, '@', 1),
      'body', c.body, 'targetType', c.target_type, 'targetId', c.target_id, 'createdAt', c.created_at)
      order by c.created_at, c.id), '[]'::jsonb) from public.circle_comments c
      join auth.users u on u.id = c.author_id where c.post_id = p.id and c.deleted_at is null),
    'savedRecipeIds', (select coalesce(jsonb_object_agg(r.source_snapshot->>'sourceRecipeId', r.id::text), '{}'::jsonb)
      from public.recipes r where r.household_id = public.active_household_id() and r.source_type = 'shared'
        and r.archived_at is null and r.source_snapshot->>'sourceRecipeId' in (
          select recipe->>'id' from jsonb_array_elements(case when p.kind in ('week', 'meal')
            then p.snapshot->'recipes' else jsonb_build_array(p.snapshot->'recipe') end) recipe))
  );
end;
$$;

create or replace function public.save_circle_recipe(requested_share_id uuid, requested_recipe_id uuid)
returns jsonb language plpgsql security definer set search_path = '' as $$
declare p public.circle_posts%rowtype; h uuid := public.active_household_id(); snap jsonb;
  existing uuid; copied uuid;
begin
  if h is null then raise exception 'Household required'; end if;
  perform 1 from public.friend_circles where id =
    (select circle_id from public.circle_posts where id = requested_share_id) for update;
  select * into p from public.circle_posts cp where cp.id = requested_share_id and cp.revoked_at is null
    and public.is_accepted_circle_member(cp.circle_id)
    and exists(select 1 from public.circle_post_recipients a join public.circle_members m
      on m.circle_id = cp.circle_id and m.user_id = a.user_id and m.membership_id = a.membership_id
      where a.post_id = requested_share_id and a.user_id = auth.uid()) for update;
  if not found then raise exception 'Shared item was not found'; end if;
  select value into snap from jsonb_array_elements(case when p.kind in ('week', 'meal') then p.snapshot->'recipes'
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

create function public.share_meal_to_circle(requested_circle_id uuid, requested_meal_id uuid)
returns jsonb language plpgsql security definer set search_path = '' as $$
declare h uuid := public.active_household_id(); m public.meals%rowtype; p public.circle_posts%rowtype; snap jsonb;
begin
  perform 1 from public.friend_circles where id = requested_circle_id for update;
  if not public.is_accepted_circle_member(requested_circle_id) then raise exception 'Circle is not available'; end if;
  if (select count(*) from public.circle_posts where circle_id = requested_circle_id and created_by = auth.uid()
      and created_at >= now() - interval '1 day') >= 100 then raise exception 'Daily share limit reached'; end if;
  select * into m from public.meals where id = requested_meal_id and household_id = h and archived_at is null;
  if not found then raise exception 'Meal was not found'; end if;
  snap := jsonb_build_object('meal', jsonb_build_object('id', m.id, 'name', m.name, 'servings', m.servings,
    'notes', m.notes, 'components', (select coalesce(jsonb_agg(jsonb_build_object('name', c.value->>'name',
      'quantity', c.value->'quantity', 'unit', c.value->>'unit', 'source', c.value->>'source',
      'action', c.value->>'action', 'recipeId', c.value->>'recipeId') order by c.ordinality), '[]'::jsonb)
      from jsonb_array_elements(m.components) with ordinality c(value, ordinality))),
    'recipes', (select coalesce(jsonb_agg(public.circle_recipe_snapshot(r.id, h, true) order by r.title), '[]'::jsonb)
      from public.recipes r where r.household_id = h and r.id in
        (select (c->>'recipeId')::uuid from jsonb_array_elements(m.components) c where c->>'recipeId' is not null)));
  insert into public.circle_posts(circle_id, source_household_id, created_by, kind, snapshot)
    values(requested_circle_id, h, auth.uid(), 'meal', snap) returning * into p;
  perform public.capture_circle_audience(p);
  perform public.notify_circle_post(p);
  return public.circle_post_summary(p);
end;
$$;
revoke all on function public.share_meal_to_circle(uuid, uuid) from public, anon;
grant execute on function public.share_meal_to_circle(uuid, uuid) to authenticated;

drop function public.share_direct(text, text, uuid, text);
create function public.share_direct(requested_email text, requested_kind text,
  requested_recipe_id uuid default null, requested_week_start text default null,
  requested_meal_id uuid default null)
returns jsonb language plpgsql security definer set search_path = '' as $$
declare target_user uuid; room_id uuid; post jsonb; clean_email text := lower(trim(coalesce(requested_email, '')));
begin
  if auth.uid() is null or public.active_household_id() is null then raise exception 'Household required'; end if;
  if requested_kind not in ('recipe', 'week', 'meal') then raise exception 'Choose a recipe, meal, or weekly plan'; end if;
  if (requested_kind = 'recipe' and (requested_recipe_id is null or requested_week_start is not null or requested_meal_id is not null))
    or (requested_kind = 'week' and (requested_week_start is null or requested_recipe_id is not null or requested_meal_id is not null))
    or (requested_kind = 'meal' and (requested_meal_id is null or requested_recipe_id is not null or requested_week_start is not null)) then
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
  elsif requested_kind = 'week' then
    post := public.share_week_to_circle(room_id, requested_week_start);
  else
    post := public.share_meal_to_circle(room_id, requested_meal_id);
  end if;
  return post;
end;
$$;
revoke all on function public.share_direct(text, text, uuid, text, uuid) from public, anon;
grant execute on function public.share_direct(text, text, uuid, text, uuid) to authenticated;

create or replace function public.list_shared_with_me(result_limit integer default 51, result_offset integer default 0,
  requested_kind text default null, requested_circle_id uuid default null)
returns jsonb language plpgsql stable security definer set search_path = '' as $$
begin
  if result_limit is null or result_limit not between 1 and 101 or result_offset is null or result_offset < 0 or
    requested_kind not in ('week', 'recipe', 'meal', 'message') and requested_kind is not null then
    raise exception 'Choose a valid share type, limit, and offset'; end if;
  return (
  select coalesce(jsonb_agg(public.circle_post_summary(p) order by p.created_at desc, p.id desc), '[]'::jsonb)
  from (select p.* from public.circle_posts p join public.circle_members m on m.circle_id = p.circle_id
    join public.circle_post_recipients a on a.post_id = p.id and a.user_id = m.user_id
      and a.membership_id = m.membership_id
    where m.user_id = auth.uid() and m.status = 'accepted' and p.revoked_at is null
      and (requested_kind is null or p.kind = requested_kind)
      and (requested_circle_id is null or p.circle_id = requested_circle_id)
    order by p.created_at desc, p.id desc limit result_limit offset result_offset) p);
end;
$$;
