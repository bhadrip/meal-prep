create table public.household_invitations (
  id uuid primary key default gen_random_uuid(),
  household_id uuid not null references public.households(id) on delete cascade,
  email text not null check (email = lower(trim(email)) and char_length(email) between 3 and 254),
  invited_by uuid not null references auth.users(id) on delete restrict,
  created_at timestamptz not null default now(),
  expires_at timestamptz not null default (now() + interval '7 days'),
  revoked_at timestamptz,
  revoked_by uuid references auth.users(id) on delete set null,
  accepted_at timestamptz,
  accepted_by uuid references auth.users(id) on delete set null
);

create index household_invitations_email_pending_idx
  on public.household_invitations (email, expires_at desc)
  where revoked_at is null and accepted_at is null;

alter table public.household_invitations enable row level security;
-- Membership changes and invitation details are available only through the
-- narrowly checked functions below. No table privileges are granted to clients.

create or replace function public.household_access()
returns jsonb language plpgsql stable security definer set search_path = '' as $$
declare
  target_id uuid;
  caller_role public.household_role;
begin
  select household_id, role into target_id, caller_role
  from public.household_members where user_id = auth.uid()
  order by joined_at limit 1;
  if target_id is null then return jsonb_build_object('members', '[]'::jsonb, 'invitations', '[]'::jsonb); end if;
  return jsonb_build_object(
    'role', caller_role,
    'members', coalesce((
      select jsonb_agg(jsonb_build_object('userId', m.user_id, 'email', u.email, 'role', m.role, 'joinedAt', m.joined_at) order by m.joined_at)
      from public.household_members m join auth.users u on u.id = m.user_id
      where m.household_id = target_id
    ), '[]'::jsonb),
    'invitations', case when caller_role = 'owner' then coalesce((
      select jsonb_agg(jsonb_build_object('id', i.id, 'email', i.email, 'createdAt', i.created_at,
        'expiresAt', i.expires_at, 'status', case when i.revoked_at is not null then 'revoked'
          when i.accepted_at is not null then 'accepted' when i.expires_at <= now() then 'expired' else 'pending' end)
        order by i.created_at desc)
      from public.household_invitations i where i.household_id = target_id
        and i.created_at > now() - interval '30 days'
    ), '[]'::jsonb) else '[]'::jsonb end
  );
end;
$$;

create or replace function public.create_household_invitation(invitee_email text)
returns jsonb language plpgsql security definer set search_path = '' as $$
declare
  target_id uuid;
  normalized_email text := lower(trim(invitee_email));
  invitation_id uuid;
  household_name text;
  reused boolean := false;
begin
  if auth.uid() is null then raise exception 'Authentication required'; end if;
  if normalized_email is null or normalized_email !~ '^[^[:space:]@]+@[^[:space:]@]+\.[^[:space:]@]+$'
     or char_length(normalized_email) > 254 then raise exception 'Enter a valid email address'; end if;
  select m.household_id into target_id from public.household_members m
  where m.user_id = auth.uid() and m.role = 'owner' order by m.joined_at limit 1;
  if target_id is null then raise exception 'Only a household owner can invite people'; end if;
  select h.name into household_name from public.households h where h.id = target_id for no key update;
  if exists (select 1 from public.household_members m join auth.users u on u.id = m.user_id
    where m.household_id = target_id and lower(u.email) = normalized_email) then
    raise exception 'This person is already a household member';
  end if;
  if not exists (select 1 from auth.users u where lower(u.email) = normalized_email
    and u.email_confirmed_at is not null) then
    raise exception 'Ask this person to sign up and verify their email before inviting them';
  end if;
  select id into invitation_id from public.household_invitations
  where household_id = target_id and email = normalized_email
    and revoked_at is null and accepted_at is null and expires_at > now()
  order by created_at desc limit 1;
  if invitation_id is null then
    insert into public.household_invitations(household_id, email, invited_by)
    values (target_id, normalized_email, auth.uid()) returning id into invitation_id;
  else
    reused := true;
    update public.household_invitations set expires_at = now() + interval '7 days'
    where id = invitation_id;
  end if;
  return jsonb_build_object('id', invitation_id, 'email', normalized_email, 'householdName', household_name, 'reused', reused);
end;
$$;

create or replace function public.revoke_household_invitation(invitation_id uuid)
returns jsonb language plpgsql security definer set search_path = '' as $$
declare target_id uuid;
begin
  select household_id into target_id from public.household_members
  where user_id = auth.uid() and role = 'owner' order by joined_at limit 1;
  if target_id is null then raise exception 'Only a household owner can revoke invitations'; end if;
  update public.household_invitations set revoked_at = now(), revoked_by = auth.uid()
  where id = invitation_id and household_id = target_id and revoked_at is null and accepted_at is null;
  if not found then raise exception 'Pending invitation was not found'; end if;
  return jsonb_build_object('revoked', true);
end;
$$;

create or replace function public.pending_household_invitations()
returns jsonb language plpgsql stable security definer set search_path = '' as $$
declare verified_email text;
begin
  select lower(email) into verified_email from auth.users
  where id = auth.uid() and email_confirmed_at is not null;
  if verified_email is null then return jsonb_build_object('invitations', '[]'::jsonb, 'hasHousehold', false); end if;
  return jsonb_build_object(
    'hasHousehold', exists (select 1 from public.household_members where user_id = auth.uid()),
    'invitations', coalesce((
      select jsonb_agg(jsonb_build_object('id', i.id, 'householdName', h.name, 'expiresAt', i.expires_at)
        order by i.created_at desc)
      from public.household_invitations i join public.households h on h.id = i.household_id
      where i.email = verified_email and i.revoked_at is null and i.accepted_at is null
        and i.expires_at > now()
    ), '[]'::jsonb)
  );
end;
$$;

create or replace function public.accept_household_invitation(invitation_id uuid)
returns jsonb language plpgsql security definer set search_path = '' as $$
declare
  target public.household_invitations%rowtype;
  verified_email text;
  existing_household uuid;
  empty_household boolean;
begin
  select lower(email) into verified_email from auth.users
  where id = auth.uid() and email_confirmed_at is not null;
  if verified_email is null then raise exception 'Sign in with a verified email to join'; end if;
  select * into target from public.household_invitations where id = invitation_id for update;
  if not found or target.revoked_at is not null or target.accepted_at is not null or target.expires_at <= now() then
    raise exception 'This invitation is no longer available';
  end if;
  if target.email <> verified_email then raise exception 'Sign in with the invited email address'; end if;
  select household_id into existing_household from public.household_members
  where user_id = auth.uid() order by joined_at limit 1;
  if existing_household is not null and existing_household <> target.household_id then
    -- Only discard an untouched personal household made by automatic bootstrap.
    perform 1 from public.households where id = existing_household for update;
    select h.created_by = auth.uid() and h.name = 'My household'
      and p.onboarding_completed_at is null and p.household_size is null
      and p.dietary_restrictions = '[]'::jsonb and p.store_priority = '[]'::jsonb
      and p.planning_preferences = '{}'::jsonb
      and (select count(*) from public.household_members where household_id = h.id) = 1
      and not exists (select 1 from public.recipes where household_id = h.id)
      and not exists (select 1 from public.pantry_items where household_id = h.id)
      and not exists (select 1 from public.meal_plans where household_id = h.id)
      and not exists (select 1 from public.shopping_lists where household_id = h.id)
      and not exists (select 1 from public.decision_records where household_id = h.id)
      and not exists (select 1 from public.weekly_schedules where household_id = h.id)
      and not exists (select 1 from public.household_memories where household_id = h.id)
      and not exists (select 1 from public.recipe_variants where household_id = h.id)
      and not exists (select 1 from public.meal_occurrences where household_id = h.id)
      and not exists (select 1 from public.feedback_entries where household_id = h.id)
      and not exists (select 1 from public.feedback_tags where household_id = h.id)
      and not exists (select 1 from public.share_links where household_id = h.id)
      and not exists (select 1 from public.household_invitations where household_id = h.id and accepted_at is null and revoked_at is null and expires_at > now())
    into empty_household
    from public.households h join public.household_preferences p on p.household_id = h.id
    where h.id = existing_household;
    if not coalesce(empty_household, false) then
      raise exception 'This account already has a household with data. Household switching is not available yet';
    end if;
    delete from public.households where id = existing_household;
  end if;
  insert into public.household_members(household_id, user_id, role)
  values (target.household_id, auth.uid(), 'adult') on conflict do nothing;
  update public.household_invitations set accepted_at = now(), accepted_by = auth.uid()
  where id = target.id;
  insert into public.decision_records(household_id, actor_id, action, decision)
  values (target.household_id, auth.uid(), 'household_invitation', 'accepted');
  return jsonb_build_object('householdId', target.household_id, 'joined', true);
end;
$$;

create or replace function public.remove_household_member(member_id uuid)
returns jsonb language plpgsql security definer set search_path = '' as $$
declare target_id uuid;
begin
  select household_id into target_id from public.household_members
  where user_id = auth.uid() and role = 'owner' order by joined_at limit 1;
  if target_id is null then raise exception 'Only a household owner can remove people'; end if;
  delete from public.household_members where household_id = target_id and user_id = member_id and role <> 'owner';
  if not found then raise exception 'Collaborator was not found'; end if;
  update public.share_links set revoked_at = coalesce(revoked_at, now())
  where household_id = target_id and created_by = member_id and revoked_at is null;
  insert into public.decision_records(household_id, actor_id, action, decision, context)
  values (target_id, auth.uid(), 'household_member', 'removed', jsonb_build_object('memberId', member_id));
  return jsonb_build_object('removed', true);
end;
$$;

-- A new invitee who opens the app before accepting must not acquire a second
-- household. The invitation page calls pending_household_invitations first.
create or replace function public.bootstrap_my_household(household_name text default 'My household')
returns uuid language plpgsql security definer set search_path = '' as $$
declare existing_id uuid; created_id uuid; verified_email text;
begin
  if auth.uid() is null then raise exception 'Authentication required'; end if;
  select household_id into existing_id from public.household_members where user_id = auth.uid() order by joined_at limit 1;
  if existing_id is not null then return existing_id; end if;
  select lower(email) into verified_email from auth.users where id = auth.uid() and email_confirmed_at is not null;
  if exists (select 1 from public.household_invitations where email = verified_email
    and revoked_at is null and accepted_at is null and expires_at > now()) then
    raise exception 'Accept your pending household invitation first';
  end if;
  insert into public.households(name, created_by)
  values (coalesce(nullif(trim(household_name), ''), 'My household'), auth.uid()) returning id into created_id;
  insert into public.household_members(household_id, user_id, role) values (created_id, auth.uid(), 'owner');
  insert into public.household_preferences(household_id) values (created_id);
  return created_id;
end;
$$;

revoke all on function public.household_access() from public;
revoke all on function public.create_household_invitation(text) from public;
revoke all on function public.revoke_household_invitation(uuid) from public;
revoke all on function public.pending_household_invitations() from public;
revoke all on function public.accept_household_invitation(uuid) from public;
revoke all on function public.remove_household_member(uuid) from public;
revoke all on function public.bootstrap_my_household(text) from public;
grant execute on function public.household_access() to authenticated;
grant execute on function public.create_household_invitation(text) to authenticated;
grant execute on function public.revoke_household_invitation(uuid) to authenticated;
grant execute on function public.pending_household_invitations() to authenticated;
grant execute on function public.accept_household_invitation(uuid) to authenticated;
grant execute on function public.remove_household_member(uuid) to authenticated;
grant execute on function public.bootstrap_my_household(text) to authenticated;
