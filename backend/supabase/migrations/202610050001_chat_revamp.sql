-- Persistent conversations and authorized incremental chat operations.
-- Legacy rooms/posts and frozen membership epochs are retained unchanged.
create table public.chat_profiles (
 user_id uuid primary key references auth.users(id) on delete cascade,
 name text not null check(char_length(trim(name)) between 1 and 60)
);
create table public.chat_states (
 user_id uuid not null references auth.users(id) on delete cascade,
 circle_id uuid not null references public.friend_circles(id) on delete cascade,
 last_read_id uuid references public.circle_posts(id) on delete set null,
 last_read_at timestamptz, muted boolean not null default false,
 primary key(user_id,circle_id)
);
create table public.chat_reactions (
 post_id uuid not null references public.circle_posts(id) on delete cascade,
 user_id uuid not null references auth.users(id) on delete cascade,
 emoji text not null check(emoji in ('👍','❤️','😋','🎉')),
 primary key(post_id,user_id,emoji)
);
create table public.chat_sends (
 user_id uuid not null references auth.users(id) on delete cascade,
 client_id uuid not null, fingerprint jsonb not null,
 post_id uuid not null references public.circle_posts(id) on delete cascade,
 primary key(user_id,client_id)
);
-- A durable per-user invalidation counter contains no conversation content.
create table public.chat_versions (
 user_id uuid primary key references auth.users(id) on delete cascade,
 version bigint not null default 0
);
alter table public.circle_posts add column edited_at timestamptz;
alter table public.chat_profiles enable row level security;
alter table public.chat_states enable row level security;
alter table public.chat_reactions enable row level security;
alter table public.chat_sends enable row level security;
alter table public.chat_versions enable row level security;
revoke all on public.chat_profiles,public.chat_states,public.chat_reactions,public.chat_sends,public.chat_versions from public,anon,authenticated;

create function public.chat_can_read_post(post_id uuid)
returns boolean language sql stable security definer set search_path='' as $$
 select exists(select 1 from public.circle_posts p
 join public.circle_post_recipients a on a.post_id=p.id
 join public.circle_members m on m.circle_id=p.circle_id and m.user_id=a.user_id and m.membership_id=a.membership_id
 where p.id=$1 and p.revoked_at is null and m.user_id=auth.uid() and m.status='accepted');
$$;
revoke all on function public.chat_can_read_post(uuid) from public,anon,authenticated;

create function public.chat_conversation_id(room_id uuid)
returns uuid language sql stable security definer set search_path='' as $$
 select case when f.room_type='direct' then coalesce((select r.id from public.friend_circles r
 where r.room_type='direct' and
   array(select user_id from public.circle_members where circle_id=r.id and status='accepted' order by user_id)
   =array(select user_id from public.circle_members where circle_id=f.id and status='accepted' order by user_id)
   and (select count(*) from public.circle_members where circle_id=r.id)=2
   and (select count(*) from public.circle_members where circle_id=f.id and status='accepted')=2
 order by r.created_at,r.id limit 1),f.id) else f.id end from public.friend_circles f where f.id=room_id;
$$;
revoke all on function public.chat_conversation_id(uuid) from public,anon,authenticated;

alter function public.circle_post_summary(public.circle_posts) rename to circle_post_summary_legacy;
create function public.circle_post_summary(p public.circle_posts)
returns jsonb language sql stable security definer set search_path='' as $$
 select public.circle_post_summary_legacy(p) || jsonb_build_object(
 'createdByName',coalesce((select name from public.chat_profiles where user_id=p.created_by),
   (select split_part(email,'@',1) from auth.users where id=p.created_by)),
 'editedAt',p.edited_at,'conversationId',public.chat_conversation_id(p.circle_id),
 'reactions',(select coalesce(jsonb_agg(r),'[]'::jsonb) from
   (select emoji,count(*) as count,bool_or(user_id=auth.uid()) as mine from public.chat_reactions where post_id=p.id
     and user_id in (select a.user_id from public.circle_post_recipients a join public.circle_members m
       on m.circle_id=p.circle_id and m.user_id=a.user_id and m.membership_id=a.membership_id
       where a.post_id=p.id and m.status='accepted') group by emoji order by emoji) r),
 'seenBy',(select count(*) from public.chat_states s join public.circle_post_recipients a on a.post_id=p.id and a.user_id=s.user_id
   join public.circle_members m on m.circle_id=p.circle_id and m.user_id=a.user_id and m.membership_id=a.membership_id
   where s.circle_id=public.chat_conversation_id(p.circle_id) and s.last_read_at>=p.created_at and s.user_id<>p.created_by and m.status='accepted'));
$$;
revoke all on function public.circle_post_summary(public.circle_posts) from public,anon,authenticated;

create function public.chat_history(requested_circle_id uuid, result_limit integer default 51,
 before_cursor text default null, search_text text default '', sender_id uuid default null,
 since_date date default null, post_kind text default null)
returns jsonb language plpgsql stable security definer set search_path='' as $$
begin
 if not public.is_accepted_circle_member(requested_circle_id) then raise exception 'Circle is not available'; end if;
 if result_limit not between 1 and 101 or char_length(search_text)>120
   or post_kind not in ('message','recipe','meal','week') and post_kind is not null then raise exception 'Choose valid history filters'; end if;
 return (select coalesce(jsonb_agg(public.circle_post_summary(p) order by p.created_at desc,p.id desc),'[]'::jsonb)
 from (select p.* from public.circle_posts p where p.circle_id in(select f.id from public.friend_circles f where public.chat_conversation_id(f.id)=public.chat_conversation_id(requested_circle_id)) and public.chat_can_read_post(p.id)
 and (before_cursor is null or (p.created_at,p.id)<(split_part(before_cursor,'|',1)::timestamptz,split_part(before_cursor,'|',2)::uuid))
 and (search_text='' or strpos(lower(p.snapshot::text),lower(search_text))>0
   or exists(select 1 from public.circle_comments c where c.post_id=p.id and c.deleted_at is null and strpos(lower(c.body),lower(search_text))>0))
 and (sender_id is null or p.created_by=sender_id) and (since_date is null or p.created_at>=since_date::timestamptz)
 and (post_kind is null or p.kind=post_kind) order by p.created_at desc,p.id desc limit result_limit) p);
end;
$$;

-- Room lists carry a title/caption only; full snapshots load in the conversation.
create function public.chat_preview(p public.circle_posts)
returns jsonb language sql stable security definer set search_path='' as $$
 select jsonb_build_object('id',p.id,'circleId',p.circle_id,'kind',p.kind,'createdAt',p.created_at,
 'createdBy',p.created_by,'snapshot',jsonb_strip_nulls(jsonb_build_object(
 'text',p.snapshot->'text','caption',p.snapshot->'caption','weekStart',p.snapshot->'weekStart',
 'recipe',case when p.kind='recipe' then jsonb_build_object('title',p.snapshot->'recipe'->'title') end,
 'meal',case when p.kind='meal' then jsonb_build_object('name',p.snapshot->'meal'->'name') end)));
$$;
revoke all on function public.chat_preview(public.circle_posts) from public,anon,authenticated;

create function public.chat_rooms()
returns jsonb language sql stable security definer set search_path='' as $$
 select coalesce(jsonb_agg(r order by r->'latest'->>'createdAt' desc nulls last,r->>'name'),'[]'::jsonb)
 from (select jsonb_build_object('id',f.id,'name',case when f.room_type='direct' then
   (select coalesce(cp.name,split_part(u.email,'@',1)) from public.circle_members peer
    join auth.users u on u.id=peer.user_id left join public.chat_profiles cp on cp.user_id=peer.user_id
    where peer.circle_id=f.id and peer.user_id<>auth.uid() limit 1) else f.name end,
 'roomType',f.room_type,'ownerId',f.owner_id,'myStatus','accepted',
 'memberCount',(select count(*) from public.circle_members where circle_id=f.id and status='accepted'),
 'members',(select coalesce(jsonb_agg(jsonb_build_object('userId',m.user_id,'name',coalesce(cp.name,split_part(u.email,'@',1)),
   'email',case when f.owner_id=auth.uid() then u.email else null end,'status',m.status)),'[]'::jsonb)
   from public.circle_members m join auth.users u on u.id=m.user_id left join public.chat_profiles cp on cp.user_id=m.user_id
   where m.circle_id=f.id and (m.status='accepted' or f.owner_id=auth.uid())),
 'audience',(select coalesce(jsonb_agg(jsonb_build_object('userId',m.user_id,'membershipId',m.membership_id,'name',coalesce(cp.name,split_part(u.email,'@',1)))),'[]'::jsonb)
   from public.circle_members m join auth.users u on u.id=m.user_id left join public.chat_profiles cp on cp.user_id=m.user_id where m.circle_id=f.id and m.status='accepted'),
 'memberNames',(select coalesce(jsonb_agg(coalesce(cp.name,split_part(u.email,'@',1))),'[]'::jsonb)
   from public.circle_members m join auth.users u on u.id=m.user_id left join public.chat_profiles cp on cp.user_id=m.user_id where m.circle_id=f.id and m.status='accepted'),
 'latest',(select public.chat_preview(p) from public.circle_posts p where p.circle_id in(select alias.id from public.friend_circles alias where public.chat_conversation_id(alias.id)=f.id) and public.chat_can_read_post(p.id) order by p.created_at desc,p.id desc limit 1),
 'unreadCount',(select count(*) from public.circle_posts p where p.circle_id in(select alias.id from public.friend_circles alias where public.chat_conversation_id(alias.id)=f.id) and public.chat_can_read_post(p.id) and p.created_by<>auth.uid() and (s.last_read_at is null or p.created_at>s.last_read_at)),
 'muted',coalesce(s.muted,false),'lastReadId',s.last_read_id,'lastReadAt',s.last_read_at) as r
 from public.friend_circles f join public.circle_members mine on mine.circle_id=f.id and mine.user_id=auth.uid() and mine.status='accepted'
 left join public.chat_states s on s.circle_id=f.id and s.user_id=auth.uid() where public.chat_conversation_id(f.id)=f.id) rooms;
$$;

create function public.chat_action(requested_action text,requested_target uuid,payload jsonb)
returns jsonb language plpgsql security definer set search_path='' as $$
declare p public.circle_posts%rowtype; s public.chat_states%rowtype; body text;
begin
 if auth.uid() is null then raise exception 'Sign in to continue'; end if;
 if requested_action='state' then
   if not public.is_accepted_circle_member(requested_target) then raise exception 'Circle is not available'; end if;
   requested_target:=public.chat_conversation_id(requested_target);
   if payload->>'lastReadId' is not null then
     select * into p from public.circle_posts where id=(payload->>'lastReadId')::uuid and public.chat_conversation_id(circle_id)=public.chat_conversation_id(requested_target) and public.chat_can_read_post(id);
     if not found then raise exception 'Read position belongs to another conversation'; end if;
   end if;
   insert into public.chat_states(user_id,circle_id,last_read_id,last_read_at,muted)
    values(auth.uid(),requested_target,p.id,p.created_at,coalesce((payload->>'muted')::boolean,false))
    on conflict(user_id,circle_id) do update set
      last_read_id=case when excluded.last_read_at>=coalesce(chat_states.last_read_at,'-infinity') then excluded.last_read_id else chat_states.last_read_id end,
      last_read_at=greatest(chat_states.last_read_at,excluded.last_read_at),
      muted=coalesce((payload->>'muted')::boolean,chat_states.muted) returning * into s;
   return jsonb_build_object('lastReadId',s.last_read_id,'lastReadAt',s.last_read_at,'muted',s.muted);
 end if;
 select * into p from public.circle_posts where id=requested_target and public.chat_can_read_post(id) for update;
 if not found then raise exception 'Shared item was not found'; end if;
 if requested_action='edit' then
   body:=trim(coalesce(payload->>'body',''));
   if p.created_by<>auth.uid() or p.kind<>'message' then raise exception 'Only your text messages can be edited'; end if;
   if char_length(body) not between 1 and 2000 then raise exception 'Enter a message of 1 to 2000 characters'; end if;
   update public.circle_posts set snapshot=jsonb_set(snapshot,'{text}',to_jsonb(body)),edited_at=now() where id=p.id returning * into p;
 elsif requested_action='reaction' then
   if payload->>'emoji' not in ('👍','❤️','😋','🎉') then raise exception 'Choose a supported reaction'; end if;
   if coalesce((payload->>'active')::boolean,true) then
     insert into public.chat_reactions(post_id,user_id,emoji) values(p.id,auth.uid(),payload->>'emoji') on conflict do nothing;
   else delete from public.chat_reactions where post_id=p.id and user_id=auth.uid() and emoji=payload->>'emoji'; end if;
 else raise exception 'Unsupported chat action'; end if;
 return public.circle_post_summary(p);
end;
$$;

create function public.chat_profile(requested_name text default null)
returns jsonb language plpgsql security definer set search_path='' as $$
declare display_name text;
begin
 if auth.uid() is null then raise exception 'Sign in to continue'; end if;
 if requested_name is not null then
   if char_length(trim(requested_name)) not between 1 and 60 then raise exception 'Enter a display name of 1 to 60 characters'; end if;
   insert into public.chat_profiles(user_id,name) values(auth.uid(),trim(requested_name)) on conflict(user_id) do update set name=excluded.name;
 end if;
 select coalesce(cp.name,split_part(u.email,'@',1)) into display_name from auth.users u left join public.chat_profiles cp on cp.user_id=u.id where u.id=auth.uid();
 return jsonb_build_object('userId',auth.uid(),'name',display_name);
end;
$$;

create function public.chat_send(requested_circle_id uuid,requested_body text,
 requested_attachment_kind text default null,requested_attachment_id uuid default null,
 requested_mention_ids uuid[] default '{}'::uuid[],requested_audience text[] default null,
 client_id uuid default null,reply_to uuid default null)
returns jsonb language plpgsql security definer set search_path='' as $$
declare fingerprint jsonb; prior public.chat_sends%rowtype; sent jsonb; quoted public.circle_posts%rowtype;
begin
 if not public.is_accepted_circle_member(requested_circle_id) then raise exception 'Circle is not available'; end if;
 -- Serialize retries for this sender, including across different rooms.
 perform 1 from auth.users where id=auth.uid() for update;
 fingerprint:=jsonb_build_array(requested_circle_id,requested_body,requested_attachment_kind,requested_attachment_id,requested_mention_ids,requested_audience,reply_to);
 if client_id is not null then
   select * into prior from public.chat_sends s where s.user_id=auth.uid() and s.client_id=chat_send.client_id;
   if found then
     if prior.fingerprint<>fingerprint then raise exception 'Retry content changed; use a new send identifier'; end if;
     if not public.chat_can_read_post(prior.post_id) then raise exception 'Shared item was not found'; end if;
     return (select public.circle_post_summary(p) from public.circle_posts p where p.id=prior.post_id);
   end if;
 end if;
 if reply_to is not null then
   select * into quoted from public.circle_posts where id=reply_to and public.chat_conversation_id(circle_id)=public.chat_conversation_id(requested_circle_id) and public.chat_can_read_post(id);
   if not found then raise exception 'Reply belongs to another conversation'; end if;
 end if;
 sent:=public.send_circle_message(requested_circle_id,requested_body,requested_attachment_kind,requested_attachment_id,requested_mention_ids,requested_audience);
 if reply_to is not null then
   update public.circle_posts set snapshot=snapshot||jsonb_build_object('replyTo',jsonb_build_object('id',quoted.id,
     'name',public.circle_post_summary(quoted)->>'createdByName','text',left(coalesce(quoted.snapshot->>'text',quoted.snapshot->>'caption',quoted.kind),160))) where id=(sent->>'id')::uuid;
 end if;
 if client_id is not null then insert into public.chat_sends values(auth.uid(),client_id,fingerprint,(sent->>'id')::uuid); end if;
 return (select public.circle_post_summary(p) from public.circle_posts p where p.id=(sent->>'id')::uuid);
end;
$$;

create function public.chat_invalidate()
returns trigger language plpgsql security definer set search_path='' as $$
declare room uuid; affected uuid;
begin
 if TG_TABLE_NAME='circle_members' then room:=coalesce(new.circle_id,old.circle_id); affected:=coalesce(new.user_id,old.user_id);
 elsif TG_TABLE_NAME in ('circle_posts','chat_states') then room:=coalesce(new.circle_id,old.circle_id);
 elsif TG_TABLE_NAME in ('circle_comments','chat_reactions') then
   select circle_id into room from public.circle_posts where id=coalesce(new.post_id,old.post_id);
 elsif TG_TABLE_NAME='chat_profiles' then affected:=coalesce(new.user_id,old.user_id); end if;
 insert into public.chat_versions(user_id,version)
 select distinct m.user_id,1 from public.circle_members m join auth.users u on u.id=m.user_id where m.status='accepted' and (m.circle_id=room or
   (TG_TABLE_NAME='chat_profiles' and m.circle_id in(select circle_id from public.circle_members where user_id=affected)))
 union select affected,1 where affected is not null and exists(select 1 from auth.users where id=affected)
 on conflict(user_id) do update set version=chat_versions.version+1;
 return coalesce(new,old);
end;
$$;
create function public.chat_sync()
returns jsonb language sql stable security definer set search_path='' as $$
 select jsonb_build_object('version',coalesce((select version from public.chat_versions where user_id=auth.uid()),0)::text);
$$;
revoke all on function public.chat_invalidate() from public,anon,authenticated;
create or replace function public.send_circle_message(requested_circle_id uuid, requested_body text,
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
  perform 1 from public.friend_circles where id = requested_circle_id for update;
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
create or replace function public.share_direct(requested_email text, requested_kind text,
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
  perform 1 from auth.users where id in(auth.uid(),target_user) order by id for update;
  if (select count(*) from public.circle_posts p join public.friend_circles f on f.id = p.circle_id
      where f.room_type = 'direct' and p.created_by = auth.uid()
        and p.created_at >= now() - interval '1 day') >= 20 then raise exception 'Daily share limit reached'; end if;
  select f.id into room_id from public.friend_circles f
    where f.room_type='direct' and exists(select 1 from public.circle_members where circle_id=f.id and user_id=auth.uid() and status='accepted')
      and exists(select 1 from public.circle_members where circle_id=f.id and user_id=target_user and status='accepted')
      and (select count(*) from public.circle_members where circle_id=f.id)=2
    order by f.created_at,f.id limit 1;
  if room_id is null then
    insert into public.friend_circles(name,owner_id,room_type) values('Direct chat',auth.uid(),'direct') returning id into room_id;
    insert into public.circle_members(circle_id,user_id,status) values(room_id,auth.uid(),'accepted'),(room_id,target_user,'accepted');
  end if;
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
create trigger chat_invalidate_circle_posts after insert or update or delete on public.circle_posts for each row execute function public.chat_invalidate();
create trigger chat_invalidate_circle_comments after insert or update or delete on public.circle_comments for each row execute function public.chat_invalidate();
create trigger chat_invalidate_circle_members after insert or update or delete on public.circle_members for each row execute function public.chat_invalidate();
create trigger chat_invalidate_chat_states after insert or update or delete on public.chat_states for each row execute function public.chat_invalidate();
create trigger chat_invalidate_chat_reactions after insert or update or delete on public.chat_reactions for each row execute function public.chat_invalidate();
create trigger chat_invalidate_chat_profiles after insert or update or delete on public.chat_profiles for each row execute function public.chat_invalidate();
revoke all on function public.chat_history(uuid,integer,text,text,uuid,date,text) from public,anon;
grant execute on function public.chat_history(uuid,integer,text,text,uuid,date,text) to authenticated;
revoke all on function public.chat_rooms() from public,anon;
grant execute on function public.chat_rooms() to authenticated;
revoke all on function public.chat_action(text,uuid,jsonb) from public,anon;
grant execute on function public.chat_action(text,uuid,jsonb) to authenticated;
revoke all on function public.chat_profile(text) from public,anon;
grant execute on function public.chat_profile(text) to authenticated;
revoke all on function public.chat_send(uuid,text,text,uuid,uuid[],text[],uuid,uuid) from public,anon;
grant execute on function public.chat_send(uuid,text,text,uuid,uuid[],text[],uuid,uuid) to authenticated;
revoke all on function public.chat_sync() from public,anon;
grant execute on function public.chat_sync() to authenticated;

-- Muting suppresses new chat notifications, without hiding the conversation.
create function public.chat_notification_filter()
returns trigger language plpgsql security definer set search_path='' as $$
begin
 if new.circle_id is not null and exists(select 1 from public.chat_states
    where user_id=new.recipient_id and circle_id=public.chat_conversation_id(new.circle_id) and muted) then return null; end if;
 return new;
end;
$$;
revoke all on function public.chat_notification_filter() from public,anon,authenticated;
create trigger chat_notification_filter before insert on public.notifications for each row execute function public.chat_notification_filter();
-- Names and mention suggestions share one profile source.
create or replace function public.circle_mention_candidates(requested_circle_id uuid)
returns jsonb language sql stable security definer set search_path='' as $$
 select case when public.is_accepted_circle_member(requested_circle_id) then
 (select coalesce(jsonb_agg(jsonb_build_object('id',m.user_id,'name',coalesce(cp.name,split_part(u.email,'@',1))) order by u.email),'[]'::jsonb)
 from public.circle_members m join auth.users u on u.id=m.user_id left join public.chat_profiles cp on cp.user_id=m.user_id
 where m.circle_id=requested_circle_id and m.status='accepted') else '[]'::jsonb end;
$$;
