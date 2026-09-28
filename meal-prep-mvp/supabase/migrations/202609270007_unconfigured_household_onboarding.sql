alter table public.household_preferences
  alter column household_size drop not null,
  alter column household_size drop default;

alter table public.household_preferences
  drop constraint if exists household_preferences_household_size_check;

alter table public.household_preferences
  add constraint household_preferences_household_size_check
  check (household_size is null or household_size between 1 and 30);

-- Earlier bootstrap code made these product defaults look like user-provided
-- preferences. Reset only untouched onboarding rows that still exactly match
-- that starter profile.
update public.household_preferences
set
  household_size = null,
  store_priority = '[]'::jsonb,
  planning_preferences = '{}'::jsonb
where onboarding_completed_at is null
  and household_size = 1
  and dietary_restrictions = '[]'::jsonb
  and store_priority = '[{"store":"Costco","priority":1},{"store":"Safeway","priority":2}]'::jsonb
  and planning_preferences = '{"weeknightMaxMinutes":30,"leftoversForLunch":true}'::jsonb;

create or replace function public.bootstrap_my_household(household_name text default 'My household')
returns uuid
language plpgsql
security definer
set search_path = public
as $$
declare
  existing_id uuid;
  created_id uuid;
begin
  if auth.uid() is null then raise exception 'authentication required'; end if;
  select household_id into existing_id from public.household_members where user_id = auth.uid() order by joined_at limit 1;
  if existing_id is not null then return existing_id; end if;
  insert into public.households(name, created_by) values (coalesce(nullif(trim(household_name), ''), 'My household'), auth.uid()) returning id into created_id;
  insert into public.household_members(household_id, user_id, role) values (created_id, auth.uid(), 'owner');
  insert into public.household_preferences(household_id) values (created_id);
  return created_id;
end;
$$;

create or replace function public.get_household_context()
returns jsonb
language sql
stable
security invoker
as $$
  select jsonb_build_object(
    'householdId', h.id,
    'householdName', h.name,
    'role', hm.role,
    'householdSize', p.household_size,
    'dietaryRestrictions', p.dietary_restrictions,
    'storePriority', p.store_priority,
    'planningPreferences', p.planning_preferences,
    'onboardingCompletedAt', p.onboarding_completed_at,
    'onboardingComplete', p.onboarding_completed_at is not null
  )
  from public.household_members hm
  join public.households h on h.id = hm.household_id
  join public.household_preferences p on p.household_id = h.id
  where hm.user_id = auth.uid()
  order by hm.joined_at
  limit 1;
$$;

revoke all on function public.bootstrap_my_household(text) from public;
revoke all on function public.get_household_context() from public;
grant execute on function public.bootstrap_my_household(text) to authenticated;
grant execute on function public.get_household_context() to authenticated;
