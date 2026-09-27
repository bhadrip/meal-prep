alter table public.household_preferences
  add column if not exists onboarding_completed_at timestamptz;

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
    'onboardingCompletedAt', p.onboarding_completed_at
  )
  from public.household_members hm
  join public.households h on h.id = hm.household_id
  join public.household_preferences p on p.household_id = h.id
  where hm.user_id = auth.uid()
  order by hm.joined_at
  limit 1;
$$;

grant execute on function public.get_household_context() to authenticated;
