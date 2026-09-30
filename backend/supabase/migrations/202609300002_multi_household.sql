-- One selected household per account. Membership remains many-to-many.
create table public.user_active_households (
  user_id uuid primary key references auth.users(id) on delete cascade,
  household_id uuid not null,
  foreign key (household_id, user_id)
    references public.household_members(household_id, user_id) on delete cascade
);
alter table public.user_active_households enable row level security;
revoke all on table public.user_active_households from public, anon, authenticated;

create function public.active_household_id()
returns uuid language sql stable security definer set search_path = '' as $$
  select coalesce(
    (select s.household_id from public.user_active_households s
      join public.household_members m on m.household_id = s.household_id and m.user_id = s.user_id
      where s.user_id = auth.uid()),
    (select m.household_id from public.household_members m
      where m.user_id = auth.uid() order by m.joined_at, m.household_id limit 1)
  );
$$;
revoke all on function public.active_household_id() from public;
grant execute on function public.active_household_id() to authenticated;

-- Existing RLS policies already call this helper. Scoping it to the selected
-- household also scopes direct table and ID-based requests.
create or replace function public.is_household_member(target_household_id uuid)
returns boolean language sql stable security definer set search_path = '' as $$
  select target_household_id = public.active_household_id() and exists (
    select 1 from public.household_members m
    where m.household_id = target_household_id and m.user_id = auth.uid()
  );
$$;

drop policy households_update on public.households;
create policy households_update on public.households for update to authenticated
  using (created_by = auth.uid() and public.is_household_member(id))
  with check (created_by = auth.uid() and public.is_household_member(id));

create function public.list_my_households()
returns jsonb language sql stable security definer set search_path = '' as $$
  select jsonb_build_object(
    'activeHouseholdId', public.active_household_id(),
    'households', coalesce((select jsonb_agg(jsonb_build_object(
      'id', h.id, 'name', h.name, 'role', m.role, 'joinedAt', m.joined_at
    ) order by m.joined_at, h.id)
      from public.household_members m join public.households h on h.id = m.household_id
      where m.user_id = auth.uid()), '[]'::jsonb)
  );
$$;

create function public.set_active_household(requested_household_id uuid)
returns jsonb language plpgsql security definer set search_path = '' as $$
begin
  if not exists (select 1 from public.household_members
    where user_id = auth.uid() and household_id = requested_household_id) then
    raise exception 'Household is not available to this account';
  end if;
  insert into public.user_active_households(user_id, household_id)
  values (auth.uid(), requested_household_id)
  on conflict (user_id) do update set household_id = excluded.household_id;
  return public.list_my_households();
end;
$$;

create function public.create_my_household(requested_name text)
returns jsonb language plpgsql security definer set search_path = '' as $$
declare new_id uuid; clean_name text := trim(requested_name);
begin
  if auth.uid() is null then raise exception 'Authentication required'; end if;
  if clean_name is null or char_length(clean_name) < 1 or char_length(clean_name) > 120 then
    raise exception 'Enter a household name of 1 to 120 characters';
  end if;
  insert into public.households(name, created_by) values (clean_name, auth.uid()) returning id into new_id;
  insert into public.household_members(household_id, user_id, role) values (new_id, auth.uid(), 'owner');
  insert into public.household_preferences(household_id) values (new_id);
  insert into public.user_active_households(user_id, household_id) values (auth.uid(), new_id)
    on conflict (user_id) do update set household_id = excluded.household_id;
  return public.list_my_households();
end;
$$;

create function public.leave_active_household()
returns jsonb language plpgsql security definer set search_path = '' as $$
declare target_id uuid := public.active_household_id(); caller_role public.household_role;
begin
  select role into caller_role from public.household_members
    where user_id = auth.uid() and household_id = target_id for update;
  if caller_role is null then raise exception 'Household is not available to this account'; end if;
  if caller_role = 'owner' then raise exception 'An owner cannot leave a household'; end if;
  insert into public.decision_records(household_id, actor_id, action, decision)
    values (target_id, auth.uid(), 'household_member', 'left');
  delete from public.household_members where user_id = auth.uid() and household_id = target_id;
  update public.share_links set revoked_at = coalesce(revoked_at, now())
    where household_id = target_id and created_by = auth.uid() and revoked_at is null;
  return public.list_my_households();
end;
$$;

revoke all on function public.list_my_households() from public;
revoke all on function public.set_active_household(uuid) from public;
revoke all on function public.create_my_household(text) from public;
revoke all on function public.leave_active_household() from public;
grant execute on function public.list_my_households() to authenticated;
grant execute on function public.set_active_household(uuid) to authenticated;
grant execute on function public.create_my_household(text) to authenticated;
grant execute on function public.leave_active_household() to authenticated;

-- Membership management uses only the selected household.
create or replace function public.household_access()
returns jsonb language plpgsql stable security definer set search_path = '' as $$
declare
  target_id uuid;
  caller_role public.household_role;
begin
  select household_id, role into target_id, caller_role
  from public.household_members where user_id = auth.uid()
    and household_id = public.active_household_id();
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
  where m.user_id = auth.uid() and m.role = 'owner'
    and m.household_id = public.active_household_id();
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
  where user_id = auth.uid() and role = 'owner'
    and household_id = public.active_household_id();
  if target_id is null then raise exception 'Only a household owner can revoke invitations'; end if;
  update public.household_invitations set revoked_at = now(), revoked_by = auth.uid()
  where id = invitation_id and household_id = target_id and revoked_at is null and accepted_at is null;
  if not found then raise exception 'Pending invitation was not found'; end if;
  return jsonb_build_object('revoked', true);
end;
$$;

create or replace function public.remove_household_member(member_id uuid)
returns jsonb language plpgsql security definer set search_path = '' as $$
declare target_id uuid;
begin
  select household_id into target_id from public.household_members
  where user_id = auth.uid() and role = 'owner'
    and household_id = public.active_household_id();
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

create or replace function public.copy_shared_recipe(raw_token text)
returns uuid
language plpgsql
security definer
set search_path = pg_catalog, extensions, public
as $$
declare
  shared public.share_links%rowtype;
  target_household_id uuid;
  new_recipe_id uuid;
begin
  if auth.uid() is null then raise exception 'authentication required'; end if;
  select * into shared from public.share_links s
    where s.token_hash = digest(raw_token, 'sha256')
      and s.artifact_type = 'recipe' and s.revoked_at is null
      and (s.expires_at is null or s.expires_at > now());
  if not found then raise exception 'share not found'; end if;
  target_household_id := public.active_household_id();
  if target_household_id is null then raise exception 'household required'; end if;
  insert into public.recipes (
    household_id, title, description, servings, active_minutes, total_minutes,
    tags, ingredients, instructions, source_type, source_url, source_snapshot
  ) values (
    target_household_id,
    shared.snapshot->>'title',
    coalesce(shared.snapshot->>'description', ''),
    coalesce((shared.snapshot->>'servings')::numeric, 4),
    (shared.snapshot->>'activeMinutes')::integer,
    (shared.snapshot->>'totalMinutes')::integer,
    coalesce(array(select jsonb_array_elements_text(shared.snapshot->'tags')), '{}'::text[]),
    coalesce(shared.snapshot->'ingredients', '[]'::jsonb),
    coalesce(shared.snapshot->'instructions', '[]'::jsonb),
    'shared',
    shared.snapshot->>'sourceUrl',
    jsonb_build_object('shareId', shared.id, 'sharedAt', now())
  ) returning id into new_recipe_id;
  return new_recipe_id;
end;
$$;

-- Joining preserves every existing household and selects the newly joined one.
create or replace function public.accept_household_invitation(invitation_id uuid)
returns jsonb language plpgsql security definer set search_path = '' as $$
declare target public.household_invitations%rowtype; verified_email text;
begin
  select lower(email) into verified_email from auth.users
    where id = auth.uid() and email_confirmed_at is not null;
  if verified_email is null then raise exception 'Sign in with a verified email to join'; end if;
  select * into target from public.household_invitations where id = invitation_id for update;
  if not found or target.revoked_at is not null or target.accepted_at is not null
    or target.expires_at <= now() then
    raise exception 'This invitation is no longer available';
  end if;
  if target.email <> verified_email then raise exception 'Sign in with the invited email address'; end if;
  insert into public.household_members(household_id, user_id, role)
    values (target.household_id, auth.uid(), 'adult') on conflict do nothing;
  insert into public.user_active_households(user_id, household_id)
    values (auth.uid(), target.household_id)
    on conflict (user_id) do update set household_id = excluded.household_id;
  update public.household_invitations set accepted_at = now(), accepted_by = auth.uid()
    where id = target.id;
  insert into public.decision_records(household_id, actor_id, action, decision)
    values (target.household_id, auth.uid(), 'household_invitation', 'accepted');
  return jsonb_build_object('householdId', target.household_id, 'joined', true);
end;
$$;
