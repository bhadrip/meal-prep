-- Scope each conversation timeline before paging, while keeping the audience
-- captured at publication time. Share summaries include thread counts.
alter table public.circle_posts drop constraint circle_posts_kind_check;
alter table public.circle_posts add constraint circle_posts_kind_check
  check (kind in ('week', 'recipe', 'message'));

create or replace function public.circle_post_summary(p public.circle_posts)
returns jsonb language sql stable security definer set search_path = '' as $$
  select jsonb_build_object('id', p.id, 'circleId', p.circle_id, 'circleName', c.name,
    'kind', p.kind, 'createdBy', p.created_by, 'createdByName', split_part(u.email, '@', 1),
    'createdAt', p.created_at, 'snapshot', p.snapshot,
    'commentCount', (select count(*) from public.circle_comments co
      where co.post_id = p.id and co.deleted_at is null))
  from public.friend_circles c join auth.users u on u.id = p.created_by where c.id = p.circle_id;
$$;

drop function public.list_shared_with_me(integer, integer, text);
create function public.list_shared_with_me(result_limit integer default 51, result_offset integer default 0,
  requested_kind text default null, requested_circle_id uuid default null)
returns jsonb language plpgsql stable security definer set search_path = '' as $$
begin
  if result_limit is null or result_limit not between 1 and 101 or result_offset is null or result_offset < 0 or
    requested_kind not in ('week', 'recipe', 'message') and requested_kind is not null then
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
revoke all on function public.list_shared_with_me(integer, integer, text, uuid) from public, anon;
grant execute on function public.list_shared_with_me(integer, integer, text, uuid) to authenticated;

create or replace function public.notify_circle_post(requested_post public.circle_posts)
returns void language sql security definer set search_path = '' as $$
  insert into public.notifications(recipient_id, circle_id, actor_id, kind, title, target_path, event_key)
  select a.user_id, requested_post.circle_id, auth.uid(),
    case when requested_post.kind = 'message' then 'circle_message' else 'circle_share' end,
    case requested_post.kind when 'week' then 'A friend shared a weekly meal plan'
      when 'recipe' then 'A friend shared a recipe' else 'A friend sent a circle message' end,
    '/app?view=circles&share=' || requested_post.id::text, 'circle-share:' || requested_post.id::text
  from public.circle_post_recipients a where a.post_id = requested_post.id
    and a.user_id <> auth.uid() on conflict(recipient_id, event_key) do nothing;
$$;

create function public.send_circle_message(requested_circle_id uuid, requested_body text)
returns jsonb language plpgsql security definer set search_path = '' as $$
declare h uuid := public.active_household_id(); p public.circle_posts%rowtype;
begin
  if char_length(trim(coalesce(requested_body, ''))) not between 1 and 2000 then
    raise exception 'Enter a message of 1 to 2000 characters'; end if;
  if h is null then raise exception 'Household required'; end if;
  perform 1 from public.friend_circles where id = requested_circle_id for update;
  if not public.is_accepted_circle_member(requested_circle_id) then raise exception 'Circle is not available'; end if;
  if (select count(*) from public.circle_posts where circle_id = requested_circle_id and created_by = auth.uid()
      and created_at >= now() - interval '1 day') >= 100 then raise exception 'Daily share limit reached'; end if;
  insert into public.circle_posts(circle_id, source_household_id, created_by, kind, snapshot)
    values(requested_circle_id, h, auth.uid(), 'message', jsonb_build_object('text', trim(requested_body))) returning * into p;
  perform public.capture_circle_audience(p);
  perform public.notify_circle_post(p);
  return public.circle_post_summary(p);
end;
$$;
revoke all on function public.send_circle_message(uuid, text) from public, anon;
grant execute on function public.send_circle_message(uuid, text) to authenticated;

create or replace function public.comment_on_circle_share(requested_share_id uuid, requested_body text,
  requested_target_type text default 'post', requested_target_id uuid default null)
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
  if (select count(*) from public.circle_comments where post_id = requested_share_id and author_id = auth.uid()
      and created_at >= now() - interval '1 hour') >= 30 then raise exception 'Comment rate limit reached'; end if;
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
    select m.user_id, p.circle_id, auth.uid(), 'circle_comment', case when p.kind = 'message' then 'A friend replied in your circle' else 'A friend replied to a meal share' end,
      '/app?view=circles&share=' || p.id::text, 'circle-comment:' || c.id::text
    from public.circle_members m join public.circle_post_recipients a on a.post_id = p.id and a.user_id = m.user_id
      and a.membership_id = m.membership_id
    where m.circle_id = p.circle_id and m.status = 'accepted'
      and m.user_id <> auth.uid() on conflict(recipient_id, event_key) do nothing;
  return jsonb_build_object('id', c.id, 'authorId', c.author_id,
    'authorName', (select split_part(email, '@', 1) from auth.users where id = c.author_id), 'body', c.body,
    'targetType', c.target_type, 'targetId', c.target_id, 'createdAt', c.created_at);
end;
$$;
