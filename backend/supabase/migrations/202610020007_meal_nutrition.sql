-- Recipe nutrition is optional and shares the per-serving contract with plans.
alter table public.recipes add column nutrition jsonb
  check (nutrition is null or jsonb_typeof(nutrition) = 'object');

-- Qualitative per-serving guidance is optional; existing plans remain unknown.
alter table public.meal_plan_entries add column nutrition jsonb
  check (nutrition is null or jsonb_typeof(nutrition) = 'object');

create or replace function public.get_meal_plan(requested_week_start text default null)
returns jsonb language sql stable security invoker set search_path = '' as $$
  select jsonb_build_object(
    'id', p.id, 'weekStart', p.week_start, 'status', p.status, 'version', p.version,
    'tasks', p.tasks, 'ruleRevisionId', p.rule_revision_id,
    'ruleRevision', (select jsonb_build_object('id', r.id, 'revision', r.revision, 'text', r.text, 'createdAt', r.created_at)
      from public.meal_plan_rule_revisions r where r.id = p.rule_revision_id),
    'entries', coalesce((select jsonb_agg(jsonb_build_object(
      'id', e.id, 'date', e.planned_for, 'day', trim(to_char(e.planned_for, 'Day')),
      'slot', e.slot, 'slotName', e.slot_name, 'meal', e.title,
      'nutrition', e.nutrition, 'sourceMeal', e.source_meal, 'servings', e.servings, 'notes', e.notes, 'components', e.components, 'completedAt', e.completed_at
    ) order by e.planned_for, e.position) from public.meal_plan_entries e where e.meal_plan_id = p.id), '[]'::jsonb)
  ) from public.meal_plans p
  where p.household_id = public.active_household_id()
    and (requested_week_start is null or p.week_start = requested_week_start::date)
  order by p.week_start desc, p.version desc limit 1;
$$;

create or replace function public.save_meal_plan(plan jsonb)
returns jsonb language plpgsql security invoker set search_path = '' as $$
declare
  h uuid := public.active_household_id();
  p public.meal_plans%rowtype;
  w date := (plan->>'weekStart')::date;
  target_id uuid;
  rule_id uuid;
  e jsonb;
  c jsonb;
  t jsonb;
  old_task jsonb;
  old_entry public.meal_plan_entries%rowtype;
  task_list jsonb := coalesce(plan->'tasks', '[]'::jsonb);
  slots jsonb;
  position_index integer := 0;
begin
  if h is null or not public.is_household_member(h) then raise exception 'Household required'; end if;
  if extract(isodow from w) <> 1 then raise exception 'weekStart must be a Monday'; end if;
  if jsonb_typeof(plan->'entries') <> 'array' or jsonb_typeof(task_list) <> 'array' then
    raise exception 'Meals and tasks must be arrays';
  end if;
  -- Serialize plan edits and actual activity in this household.
  perform 1 from public.households where id = h for update;
  select * into p from public.meal_plans where household_id = h and week_start = w order by version desc limit 1 for update;
  target_id := coalesce(p.id, nullif(plan->>'id', '')::uuid, gen_random_uuid());
  if plan->>'id' is not null and p.id is distinct from (plan->>'id')::uuid then raise exception 'Plan ID does not belong to this week'; end if;
  if plan ? 'ruleRevisionId' then rule_id := nullif(plan->>'ruleRevisionId', '')::uuid;
  else rule_id := p.rule_revision_id; end if;
  if rule_id is not null and not exists (select 1 from public.meal_plan_rule_revisions where id = rule_id and household_id = h) then
    raise exception 'Meal plan rule revision was not found';
  end if;
  select coalesce(planning_preferences->'mealSlots',
    '[{"id":"breakfast","name":"Breakfast","enabled":true},{"id":"lunch","name":"Lunch","enabled":true},{"id":"snack","name":"Snack","enabled":true},{"id":"dinner","name":"Dinner","enabled":true}]'::jsonb)
    into slots from public.household_preferences where household_id = h;
  for t in select value from jsonb_array_elements(task_list) loop
    if nullif(trim(t->>'title'), '') is null then raise exception 'Task title is required'; end if;
    perform (t->>'id')::uuid;
    if exists (select 1 from public.meal_plans other_plan, jsonb_array_elements(other_plan.tasks) other_task
      where other_plan.id <> target_id and other_task->>'id' = t->>'id') then raise exception 'Task ID belongs to another plan'; end if;
    if t->>'recipeId' is not null and not exists (select 1 from public.recipes where id = (t->>'recipeId')::uuid and household_id = h) then
      raise exception 'Recipe was not found in this household'; end if;
    select value into old_task from jsonb_array_elements(coalesce(p.tasks, '[]'::jsonb)) where value->>'id' = t->>'id';
    if old_task->>'completedAt' is not null and old_task <> t then raise exception 'Completed plan items cannot be edited'; end if;
    if old_task->>'completedAt' is null and t->>'completedAt' is not null then raise exception 'Use complete_plan_item to record completion'; end if;
    if exists (select 1 from jsonb_array_elements_text(coalesce(t->'mealIds', '[]'::jsonb)) linked
      where not exists (select 1 from jsonb_array_elements(plan->'entries') entry where entry->>'id' = linked)) then
      raise exception 'Task meal link was not found in this plan'; end if;
  end loop;
  if exists (select 1 from jsonb_array_elements(coalesce(p.tasks, '[]'::jsonb)) old
    where old->>'completedAt' is not null and not exists (select 1 from jsonb_array_elements(task_list) new where new->>'id' = old->>'id')) then
    raise exception 'Completed plan items cannot be removed'; end if;
  insert into public.meal_plans(id, household_id, week_start, status, created_by, rule_revision_id, tasks)
    values (target_id, h, w, coalesce(plan->>'status', 'draft'), auth.uid(), rule_id, task_list)
    on conflict (id) do update set status = excluded.status, version = public.meal_plans.version + 1,
      rule_revision_id = excluded.rule_revision_id, tasks = excluded.tasks
    where public.meal_plans.household_id = h;
  if not found then raise exception 'Plan was not found in this household'; end if;
  if exists (select 1 from public.meal_plan_entries old where old.meal_plan_id = target_id and old.completed_at is not null
    and not exists (select 1 from jsonb_array_elements(plan->'entries') entry where (entry->>'id')::uuid = old.id)) then
    raise exception 'Completed plan items cannot be removed'; end if;
  delete from public.meal_plan_entries old where old.meal_plan_id = target_id
    and not exists (select 1 from jsonb_array_elements(plan->'entries') entry where (entry->>'id')::uuid = old.id);
  for e in select value from jsonb_array_elements(plan->'entries') loop
    select * into old_entry from public.meal_plan_entries where id = (e->>'id')::uuid;
    if old_entry.id is not null and old_entry.meal_plan_id <> target_id then raise exception 'Meal ID belongs to another plan'; end if;
    if (e->>'date')::date < w or (e->>'date')::date >= w + 7 then raise exception 'Meal date must be in selected week'; end if;
    if not exists (select 1 from jsonb_array_elements(slots) slot where slot->>'id' = e->>'slot'
      and ((slot->>'enabled')::boolean or old_entry.slot = e->>'slot')) then raise exception 'Choose an enabled household meal slot'; end if;
    if old_entry.completed_at is not null and (old_entry.title <> e->>'meal' or old_entry.planned_for <> (e->>'date')::date
      or old_entry.slot <> e->>'slot' or old_entry.components <> e->'components' or old_entry.notes is distinct from e->>'notes'
      or old_entry.nutrition is distinct from nullif(e->'nutrition', 'null'::jsonb)
      or old_entry.source_meal is distinct from nullif(e->'sourceMeal', 'null'::jsonb)
      or old_entry.servings is distinct from nullif(e->>'servings', '')::numeric) then raise exception 'Completed plan items cannot be edited'; end if;
    for c in select value from jsonb_array_elements(coalesce(e->'components', '[]'::jsonb)) loop
      if c->>'recipeId' is not null and not exists (select 1 from public.recipes where id = (c->>'recipeId')::uuid and household_id = h) then
        raise exception 'Recipe was not found in this household'; end if;
      if c->>'pantryItemId' is not null and not exists (select 1 from public.pantry_items where id = (c->>'pantryItemId')::uuid and household_id = h) then
        raise exception 'Pantry item was not found in this household'; end if;
      if c->>'taskId' is not null and not exists (select 1 from jsonb_array_elements(task_list) task
        where task->>'id' = c->>'taskId' and (task->>'date' is null or (task->>'date')::date <= (e->>'date')::date)) then
        raise exception 'Component task was not found or is scheduled after the meal'; end if;
    end loop;
    insert into public.meal_plan_entries(id, meal_plan_id, planned_for, slot, slot_name, title, servings, notes, components, source_meal, nutrition, position)
      values (coalesce((e->>'id')::uuid, gen_random_uuid()), target_id, (e->>'date')::date, e->>'slot', e->>'slotName',
        e->>'meal', nullif(e->>'servings', '')::numeric, e->>'notes', coalesce(e->'components', '[]'::jsonb), nullif(e->'sourceMeal', 'null'::jsonb), nullif(e->'nutrition', 'null'::jsonb), position_index)
      on conflict (id) do update set planned_for = excluded.planned_for, slot = excluded.slot, slot_name = excluded.slot_name,
        title = excluded.title, servings = excluded.servings, notes = excluded.notes, components = excluded.components, source_meal = excluded.source_meal, nutrition = excluded.nutrition, position = excluded.position;
    position_index := position_index + 1;
  end loop;
  return public.get_meal_plan(w::text);
end;
$$;
