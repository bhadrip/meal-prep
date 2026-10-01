-- Personal inbox entries are created in the same transaction as household writes.
-- No mail, push subscription, scheduler, or service-role credential is involved.
create table public.notifications (
  id uuid primary key default gen_random_uuid(),
  recipient_id uuid not null references auth.users(id) on delete cascade,
  household_id uuid references public.households(id) on delete cascade,
  actor_id uuid references auth.users(id) on delete set null,
  kind text not null,
  title text not null,
  target_path text not null check (target_path = '/invite' or target_path like '/app?view=%'),
  event_key text not null,
  created_at timestamptz not null default now(),
  expires_at timestamptz,
  read_at timestamptz,
  unique (recipient_id, event_key)
);

create index notifications_recipient_recent_idx
  on public.notifications (recipient_id, created_at desc, id desc);

-- Keep storage bounded without a scheduled worker. The website shows 100 entries;
-- retain another 100 so a busy household does not immediately lose older items.
create function public.trim_notification_history()
returns trigger language plpgsql security definer set search_path = '' as $$
begin
  delete from public.notifications
  where recipient_id = new.recipient_id and id in (
    select id from public.notifications
    where recipient_id = new.recipient_id
    order by created_at desc, id desc
    offset 200
  );
  return new;
end;
$$;
create trigger trim_notification_history after insert on public.notifications
  for each row execute function public.trim_notification_history();
revoke all on function public.trim_notification_history() from public;

alter table public.notifications enable row level security;
create function public.can_read_notification(target_household_id uuid)
returns boolean language sql stable security definer set search_path = '' as $$
  select exists (select 1 from public.household_members m
    where m.household_id = target_household_id and m.user_id = auth.uid());
$$;
revoke all on function public.can_read_notification(uuid) from public;
grant execute on function public.can_read_notification(uuid) to authenticated;
create policy notifications_read on public.notifications for select to authenticated
  using (recipient_id = auth.uid() and
    (expires_at is null or expires_at > now()) and
    (household_id is null or public.can_read_notification(household_id)));
create policy notifications_mark_read on public.notifications for update to authenticated
  using (recipient_id = auth.uid() and
    (expires_at is null or expires_at > now()) and
    (household_id is null or public.can_read_notification(household_id)))
  with check (recipient_id = auth.uid() and
    (expires_at is null or expires_at > now()) and
    (household_id is null or public.can_read_notification(household_id)));
grant select, update (read_at) on public.notifications to authenticated;

create function public.notify_household_change()
returns trigger language plpgsql security definer set search_path = '' as $$
declare
  changed jsonb := to_jsonb(new);
  old_value jsonb := case when tg_op = 'UPDATE' then to_jsonb(old) else null end;
  target_household uuid;
  event_title text;
  destination text;
begin
  if auth.uid() is null then return new; end if;
  if tg_op = 'UPDATE' and tg_table_name <> 'shopping_lists'
     and changed - 'updated_at' = old_value - 'updated_at' then return new; end if;
  target_household := (changed->>'household_id')::uuid;
  if tg_table_name = 'household_preferences' then
    event_title := 'Household settings changed'; destination := '/app?view=settings';
  elsif tg_table_name = 'recipes' then
    event_title := case when changed->>'archived_at' is not null then 'Recipe archived'
      when tg_op = 'INSERT' then 'Recipe added' else 'Recipe updated' end;
    destination := '/app?view=recipes';
    if changed->>'archived_at' is null then destination := destination || '&recipe=' || (changed->>'id'); end if;
  elsif tg_table_name = 'pantry_items' then
    event_title := 'Pantry updated'; destination := '/app?view=pantry';
  elsif tg_table_name = 'meal_plans' then
    event_title := 'Weekly plan updated'; destination := '/app?view=plan&week=' || (changed->>'week_start');
  elsif tg_table_name = 'weekly_schedules' then
    event_title := 'Weekly rhythm updated'; destination := '/app?view=plan&week=' || (changed->>'week_start');
  elsif tg_table_name = 'shopping_lists' then
    event_title := 'Shopping list updated'; destination := '/app?view=shopping';
  elsif tg_table_name = 'shopping_items' then
    if tg_op <> 'UPDATE' or changed->>'purchased' = old_value->>'purchased' then return new; end if;
    select household_id into target_household from public.shopping_lists
      where id = (changed->>'shopping_list_id')::uuid;
    event_title := 'Shopping progress changed'; destination := '/app?view=shopping';
  elsif tg_table_name = 'feedback_entries' then
    event_title := case when tg_op = 'INSERT' then 'Meal review added' else 'Meal review updated' end;
    destination := '/app?view=reviews';
  elsif tg_table_name = 'household_memories' then
    event_title := 'Household memory updated'; destination := '/app?view=reviews';
  else
    return new;
  end if;
  insert into public.notifications(recipient_id, household_id, actor_id, kind, title, target_path, event_key)
  select m.user_id, target_household, auth.uid(), tg_table_name, event_title, destination,
    tg_table_name || ':' || coalesce(changed->>'id', changed->>'household_id') || ':' || txid_current()::text
  from public.household_members m
  where m.household_id = target_household and m.user_id <> auth.uid()
  on conflict (recipient_id, event_key) do nothing;
  return new;
end;
$$;

create trigger notify_household_preferences after insert or update on public.household_preferences
  for each row execute function public.notify_household_change();
create trigger notify_recipes after insert or update on public.recipes
  for each row execute function public.notify_household_change();
create trigger notify_pantry_items after insert or update on public.pantry_items
  for each row execute function public.notify_household_change();
create trigger notify_meal_plans after insert or update on public.meal_plans
  for each row execute function public.notify_household_change();
create trigger notify_weekly_schedules after insert or update on public.weekly_schedules
  for each row execute function public.notify_household_change();
create trigger notify_shopping_lists after insert or update on public.shopping_lists
  for each row execute function public.notify_household_change();
create trigger notify_shopping_items after update on public.shopping_items
  for each row execute function public.notify_household_change();
create trigger notify_feedback_entries after insert or update on public.feedback_entries
  for each row execute function public.notify_household_change();
create trigger notify_household_memories after insert or update on public.household_memories
  for each row execute function public.notify_household_change();

create function public.notify_invitation_change()
returns trigger language plpgsql security definer set search_path = '' as $$
declare invitee_id uuid;
begin
  if tg_op = 'UPDATE' and new.revoked_at is not null and old.revoked_at is null then
    delete from public.notifications where event_key = 'invitation:' || new.id::text;
    return new;
  end if;
  if tg_op = 'UPDATE' and new.accepted_at is not null and old.accepted_at is null then
    update public.notifications set read_at = coalesce(read_at, now()),
      household_id = new.household_id, expires_at = null,
      title = 'Joined household', target_path = '/app?view=settings'
      where event_key = 'invitation:' || new.id::text;
    return new;
  end if;
  if tg_op = 'UPDATE' and new.expires_at is distinct from old.expires_at then
    update public.notifications set expires_at = new.expires_at
      where event_key = 'invitation:' || new.id::text;
    return new;
  end if;
  if tg_op <> 'INSERT' then return new; end if;
  select id into invitee_id from auth.users
    where lower(email) = new.email and email_confirmed_at is not null;
  if invitee_id is not null then
    insert into public.notifications(recipient_id, actor_id, kind, title, target_path, event_key, expires_at)
    values (invitee_id, new.invited_by, 'invitation', 'Household invitation', '/invite',
      'invitation:' || new.id::text, new.expires_at)
    on conflict (recipient_id, event_key) do nothing;
  end if;
  return new;
end;
$$;
create trigger notify_invitation after insert or update on public.household_invitations
  for each row execute function public.notify_invitation_change();

create function public.notify_membership_change()
returns trigger language plpgsql security definer set search_path = '' as $$
declare target_household uuid;
begin
  if tg_op = 'DELETE' then target_household := old.household_id;
  else target_household := new.household_id; end if;
  if auth.uid() is null then
    if tg_op = 'DELETE' then return old; else return new; end if;
  end if;
  insert into public.notifications(recipient_id, household_id, actor_id, kind, title, target_path, event_key)
  select m.user_id, target_household, auth.uid(), 'membership',
    case when tg_op = 'INSERT' then 'A member joined the household' else 'A member left the household' end,
    '/app?view=settings',
    'membership:' || tg_op || ':' ||
      (case when tg_op = 'DELETE' then old.user_id else new.user_id end)::text || ':' || txid_current()::text
  from public.household_members m
  where m.household_id = target_household and m.user_id <> auth.uid()
  on conflict (recipient_id, event_key) do nothing;
  if tg_op = 'DELETE' and old.user_id <> auth.uid() then
    insert into public.notifications(recipient_id, actor_id, kind, title, target_path, event_key)
    values (old.user_id, auth.uid(), 'access_removed', 'Household access removed',
      '/app?view=overview', 'access_removed:' || old.household_id::text || ':' || txid_current()::text);
  end if;
  if tg_op = 'DELETE' then return old; else return new; end if;
end;
$$;
create trigger notify_membership after insert or delete on public.household_members
  for each row execute function public.notify_membership_change();

revoke all on function public.notify_household_change() from public;
revoke all on function public.notify_invitation_change() from public;
revoke all on function public.notify_membership_change() from public;
