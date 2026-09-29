-- Match the existing get_meal_plan(text) signature when returning a saved plan.
create or replace function public.save_meal_plan(plan jsonb)
returns jsonb
language plpgsql
security invoker
as $$
declare
  target_household_id uuid;
  target_plan_id uuid;
  target_week_start date;
  entry jsonb;
  entry_index integer := 0;
begin
  select household_id into target_household_id from public.household_members where user_id = auth.uid() order by joined_at limit 1;
  if target_household_id is null then raise exception 'household required'; end if;
  target_week_start := (plan->>'weekStart')::date;
  target_plan_id := coalesce((plan->>'id')::uuid, gen_random_uuid());
  insert into public.meal_plans(id, household_id, week_start, status, created_by)
  values (target_plan_id, target_household_id, target_week_start, coalesce(plan->>'status', 'draft'), auth.uid())
  on conflict (id) do update set week_start = excluded.week_start, status = excluded.status, version = public.meal_plans.version + 1, updated_at = now()
  where public.meal_plans.household_id = target_household_id;
  delete from public.meal_plan_entries where meal_plan_id = target_plan_id;
  for entry in select value from jsonb_array_elements(coalesce(plan->'entries', '[]'::jsonb)) loop
    insert into public.meal_plan_entries(meal_plan_id, planned_for, slot, title, recipe_id, servings, notes, position)
    values (
      target_plan_id,
      coalesce((entry->>'date')::date, target_week_start + entry_index),
      coalesce(entry->>'slot', 'dinner'),
      coalesce(entry->>'meal', entry->>'title'),
      nullif(entry->>'recipeId', '')::uuid,
      nullif(entry->>'servings', '')::numeric,
      entry->>'notes',
      entry_index
    );
    entry_index := entry_index + 1;
  end loop;
  return public.get_meal_plan(target_week_start::text);
end;
$$;
