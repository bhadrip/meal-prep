-- One-time recovery for an existing project whose initial schema was created
-- before the GitHub migration runner began tracking it.
--
-- Run this in the Supabase SQL Editor only when the deployment fails because
-- household_role already exists. The preflight block aborts without changing
-- migration history when the expected 001-002 schema is incomplete. Migration
-- 003 is idempotently completed below before all three versions are recorded.

begin;

-- Some early production databases received migrations 001-002 before GitHub
-- migration tracking was enabled, but never received migration 003. Complete
-- that official migration before verifying and recording the baseline.
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

do $$
declare
  relation_name text;
begin
  if to_regtype('public.household_role') is null then
    raise exception 'Migration 001 is not fully installed: public.household_role is missing';
  end if;

  foreach relation_name in array array[
    'households',
    'household_members',
    'household_preferences',
    'recipes',
    'pantry_items',
    'meal_plans',
    'meal_plan_entries',
    'shopping_lists',
    'shopping_items',
    'decision_records'
  ] loop
    if to_regclass('public.' || relation_name) is null then
      raise exception 'Migration 001 is not fully installed: public.% is missing', relation_name;
    end if;
  end loop;

  if to_regprocedure('public.bootstrap_my_household(text)') is null
     or to_regprocedure('public.get_household_context()') is null
     or to_regprocedure('public.save_meal_plan(jsonb)') is null
     or to_regprocedure('public.get_meal_plan(text)') is null
     or to_regprocedure('public.save_shopping_list(jsonb)') is null
     or to_regprocedure('public.get_shopping_list(text)') is null then
    raise exception 'Migration 001 is not fully installed: one or more data functions are missing';
  end if;

  if not has_schema_privilege('authenticated', 'public', 'USAGE')
     or not has_table_privilege('authenticated', 'public.household_preferences', 'SELECT')
     or not has_table_privilege('authenticated', 'public.recipes', 'SELECT')
     or not has_table_privilege('authenticated', 'public.pantry_items', 'SELECT') then
    raise exception 'Migration 002 is not fully installed: authenticated API grants are missing';
  end if;

  if not exists (
    select 1
    from information_schema.columns
    where table_schema = 'public'
      and table_name = 'household_preferences'
      and column_name = 'onboarding_completed_at'
  ) then
    raise exception 'Migration 003 is not fully installed: onboarding_completed_at is missing';
  end if;

  if to_regclass('supabase_migrations.schema_migrations') is null then
    raise exception 'Supabase migration history table is missing; stop and use Supabase support to initialize it';
  end if;

  if not exists (
    select 1
    from information_schema.columns
    where table_schema = 'supabase_migrations'
      and table_name = 'schema_migrations'
      and column_name = 'statements'
  ) or not exists (
    select 1
    from information_schema.columns
    where table_schema = 'supabase_migrations'
      and table_name = 'schema_migrations'
      and column_name = 'name'
  ) then
    raise exception 'Supabase migration history has an unexpected shape; stop instead of altering it';
  end if;

  if has_schema_privilege('anon', 'supabase_migrations', 'USAGE')
     or has_schema_privilege('authenticated', 'supabase_migrations', 'USAGE') then
    raise exception 'Client roles can use supabase_migrations; revoke that access before repairing history';
  end if;
end
$$;

insert into supabase_migrations.schema_migrations (version, name, statements)
values
  (
    '202609270001',
    'initial_schema',
    array['Verified as already applied by repair_initial_migration_history.sql']::text[]
  ),
  (
    '202609270002',
    'data_api_grants',
    array['Verified as already applied by repair_initial_migration_history.sql']::text[]
  ),
  (
    '202609270003',
    'onboarding',
    array['Verified as already applied by repair_initial_migration_history.sql']::text[]
  )
on conflict (version) do update
set name = excluded.name,
    statements = excluded.statements;

commit;

select version, name
from supabase_migrations.schema_migrations
where version between '202609270001' and '202609270003'
order by version;
