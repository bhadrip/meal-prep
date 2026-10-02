-- Meals describe eating; tasks describe work. Preserve stable IDs for both.
alter table public.meal_plans add column tasks jsonb not null default '[]'::jsonb
  check (jsonb_typeof(tasks) = 'array');
alter table public.meal_plan_entries add column components jsonb not null default '[]'::jsonb
  check (jsonb_typeof(components) = 'array');
alter table public.meal_plan_entries add column slot_name text;
alter table public.meal_plan_entries add column completed_at timestamptz;

create table public.plan_activities (
  id uuid primary key default gen_random_uuid(),
  household_id uuid not null references public.households(id) on delete cascade,
  meal_plan_id uuid not null references public.meal_plans(id) on delete cascade,
  item_id uuid not null,
  kind text not null check (kind in ('meal', 'task')),
  inputs jsonb not null default '[]'::jsonb,
  outputs jsonb not null default '[]'::jsonb,
  completed_at timestamptz not null default now(),
  unique (household_id, item_id)
);
alter table public.plan_activities enable row level security;
create policy plan_activity_read on public.plan_activities for select to authenticated
  using (public.is_household_member(household_id));
revoke all on public.plan_activities from public, anon, authenticated;
grant select on public.plan_activities to authenticated;

alter table public.shopping_items add column received_pantry_item_id uuid references public.pantry_items(id) on delete set null;
alter table public.shopping_items add column received_at timestamptz;

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
      'servings', e.servings, 'notes', e.notes, 'components', e.components, 'completedAt', e.completed_at
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
    insert into public.meal_plan_entries(id, meal_plan_id, planned_for, slot, slot_name, title, servings, notes, components, position)
      values (coalesce((e->>'id')::uuid, gen_random_uuid()), target_id, (e->>'date')::date, e->>'slot', e->>'slotName',
        e->>'meal', nullif(e->>'servings', '')::numeric, e->>'notes', coalesce(e->'components', '[]'::jsonb), position_index)
      on conflict (id) do update set planned_for = excluded.planned_for, slot = excluded.slot, slot_name = excluded.slot_name,
        title = excluded.title, servings = excluded.servings, notes = excluded.notes, components = excluded.components, position = excluded.position;
    position_index := position_index + 1;
  end loop;
  return public.get_meal_plan(w::text);
end;
$$;

create function public.complete_plan_item(requested_week text, item_kind text, item_id uuid,
  used_inputs jsonb default '[]'::jsonb, made_outputs jsonb default '[]'::jsonb)
returns jsonb language plpgsql security definer set search_path = '' as $$
declare
  h uuid := public.active_household_id();
  p public.meal_plans%rowtype;
  item jsonb;
  activity public.plan_activities%rowtype;
  value jsonb;
  stock public.pantry_items%rowtype;
  amount numeric;
  output_records jsonb := '[]'::jsonb;
  item_title text;
begin
  if h is null or not public.is_household_member(h) then raise exception 'Household required'; end if;
  if item_kind not in ('meal', 'task') then raise exception 'Item kind must be meal or task'; end if;
  perform 1 from public.households where id = h for update;
  select * into p from public.meal_plans where household_id = h and week_start = requested_week::date order by version desc limit 1 for update;
  if p.id is null then raise exception 'Plan was not found'; end if;
  if item_kind = 'task' then
    select task into item from jsonb_array_elements(p.tasks) task where task->>'id' = item_id::text;
    item_title := item->>'title';
  else
    select jsonb_build_object('id', e.id, 'title', e.title) into item from public.meal_plan_entries e
      where e.id = item_id and e.meal_plan_id = p.id;
    item_title := item->>'title';
  end if;
  if item is null then raise exception 'Plan item was not found'; end if;
  select * into activity from public.plan_activities a where a.household_id = h and a.item_id = complete_plan_item.item_id;
  if activity.id is not null then
    return jsonb_build_object('plan', public.get_meal_plan(requested_week), 'activity',
      jsonb_build_object('itemId', activity.item_id, 'kind', activity.kind, 'completedAt', activity.completed_at, 'inputs', activity.inputs, 'outputs', activity.outputs));
  end if;
  if jsonb_typeof(used_inputs) <> 'array' or jsonb_typeof(made_outputs) <> 'array'
    or jsonb_array_length(used_inputs) > 50 or jsonb_array_length(made_outputs) > 30 then raise exception 'Invalid activity inputs or outputs'; end if;
  if (select count(*) <> count(distinct j.value->>'itemId') from jsonb_array_elements(used_inputs) j) then raise exception 'Combine repeated pantry inputs'; end if;
  -- Deterministic row locking, and all changes roll back on any invalid input/output.
  perform 1 from public.pantry_items where household_id = h and id in
    (select (j.value->>'itemId')::uuid from jsonb_array_elements(used_inputs) j) order by id for update;
  for value in select * from jsonb_array_elements(used_inputs) loop
    amount := (value->>'quantity')::numeric;
    if amount is null or amount <= 0 or amount <> round(amount, 3) or amount::text in ('NaN', 'Infinity', '-Infinity') then raise exception 'Invalid actual quantity'; end if;
    perform public.record_pantry_use((value->>'itemId')::uuid, amount, null, item_title);
  end loop;
  for value in select * from jsonb_array_elements(made_outputs) loop
    amount := (value->>'quantity')::numeric;
    if amount is null or amount <= 0 or amount <> round(amount, 3) or amount::text in ('NaN', 'Infinity', '-Infinity')
      or nullif(trim(value->>'name'), '') is null or nullif(trim(value->>'unit'), '') is null
      or coalesce(value->>'storageLocation', 'fridge') not in ('pantry', 'fridge', 'freezer', 'other') then raise exception 'Invalid prepared output'; end if;
    insert into public.pantry_items(household_id, name, quantity, unit, storage_location, quantity_confidence, category, provenance)
      values (h, trim(value->>'name'), amount, trim(value->>'unit'), coalesce(value->>'storageLocation', 'fridge'), 'exact',
        coalesce(value->>'category', 'uncategorized'), jsonb_build_object('sourceType', 'plan_activity', 'planItemId', item_id, 'recipeId', item->>'recipeId'))
      returning * into stock;
    output_records := output_records || jsonb_build_array(jsonb_build_object('itemId', stock.id, 'name', stock.name,
      'quantity', stock.quantity, 'unit', stock.unit, 'storageLocation', stock.storage_location, 'category', stock.category));
  end loop;
  insert into public.plan_activities(household_id, meal_plan_id, item_id, kind, inputs, outputs)
    values (h, p.id, item_id, item_kind, used_inputs, output_records) returning * into activity;
  if item_kind = 'task' then
    update public.meal_plans set tasks = (select jsonb_agg(case when task->>'id' = item_id::text then
      task || jsonb_build_object('completedAt', activity.completed_at, 'stockOutputs', output_records) else task end)
      from jsonb_array_elements(p.tasks) task), version = version + 1 where id = p.id;
  else
    update public.meal_plan_entries set completed_at = activity.completed_at where id = item_id;
    update public.meal_plans set version = version + 1 where id = p.id;
  end if;
  return jsonb_build_object('plan', public.get_meal_plan(requested_week), 'activity',
    jsonb_build_object('itemId', item_id, 'kind', item_kind, 'completedAt', activity.completed_at, 'inputs', used_inputs, 'outputs', output_records));
end;
$$;
revoke all on function public.complete_plan_item(text, text, uuid, jsonb, jsonb) from public;
grant execute on function public.complete_plan_item(text, text, uuid, jsonb, jsonb) to authenticated;

create function public.receive_shopping_item(shopping_item_id uuid, received_quantity numeric,
  received_unit text, received_location text default 'pantry')
returns jsonb language plpgsql security definer set search_path = '' as $$
declare
  h uuid := public.active_household_id();
  item public.shopping_items%rowtype;
  stock public.pantry_items%rowtype;
begin
  if h is null or not public.is_household_member(h) then raise exception 'Household required'; end if;
  select i.* into item from public.shopping_items i join public.shopping_lists l on l.id = i.shopping_list_id
    where i.id = shopping_item_id and l.household_id = h for update of i;
  if item.id is null then raise exception 'Shopping item was not found'; end if;
  if item.received_at is not null then
    select * into stock from public.pantry_items where id = item.received_pantry_item_id and household_id = h;
    return jsonb_build_object('item', to_jsonb(item), 'pantryItem', to_jsonb(stock));
  end if;
  if received_quantity is null or received_quantity <= 0 or received_quantity <> round(received_quantity, 3)
    or received_quantity::text in ('NaN', 'Infinity', '-Infinity') or nullif(trim(received_unit), '') is null
    or char_length(received_unit) > 40 or received_location not in ('pantry', 'fridge', 'freezer', 'other') then raise exception 'Invalid received quantity, unit, or location'; end if;
  insert into public.pantry_items(household_id, name, quantity, unit, storage_location, quantity_confidence, acquired_at, provenance)
    values (h, item.name, received_quantity, trim(received_unit), received_location, 'exact',
      (now() at time zone 'America/Los_Angeles')::date, jsonb_build_object('sourceType', 'shopping_receipt', 'shoppingItemId', item.id)) returning * into stock;
  update public.shopping_items set purchased = true, purchased_quantity = received_quantity, purchased_at = now(),
    received_at = now(), received_pantry_item_id = stock.id where id = item.id returning * into item;
  return jsonb_build_object('item', to_jsonb(item), 'pantryItem', to_jsonb(stock));
end;
$$;
revoke all on function public.receive_shopping_item(uuid, numeric, text, text) from public;
grant execute on function public.receive_shopping_item(uuid, numeric, text, text) to authenticated;

create or replace function public.get_shopping_list(requested_list_id text default null)
returns jsonb language sql stable security invoker set search_path = '' as $$
  select jsonb_build_object('id', l.id, 'name', l.name, 'status', l.status, 'mealPlanId', l.meal_plan_id,
    'items', coalesce((select jsonb_agg(jsonb_build_object('id', i.id, 'name', i.name, 'quantity', i.quantity,
      'unit', i.unit, 'store', i.store_name, 'storePriority', i.store_priority, 'source', i.source,
      'purchased', i.purchased, 'purchasedQuantity', i.purchased_quantity, 'receivedPantryItemId', i.received_pantry_item_id)
      order by i.store_priority nulls last, i.position) from public.shopping_items i where i.shopping_list_id = l.id), '[]'::jsonb))
  from public.shopping_lists l where l.household_id = public.active_household_id()
    and (requested_list_id is null or l.id = requested_list_id::uuid) order by l.updated_at desc limit 1;
$$;

create or replace function public.save_shopping_list(shopping_list jsonb)
returns jsonb language plpgsql security invoker set search_path = '' as $$
declare h uuid := public.active_household_id(); target_id uuid; value jsonb; item_id uuid; position_index integer := 0;
begin
  if h is null then raise exception 'Household required'; end if;
  target_id := coalesce(nullif(shopping_list->>'id', '')::uuid, gen_random_uuid());
  insert into public.shopping_lists(id, household_id, name, status, meal_plan_id, created_by)
    values (target_id, h, coalesce(shopping_list->>'name', 'Weekly groceries'), coalesce(shopping_list->>'status', 'draft'),
      nullif(shopping_list->>'mealPlanId', '')::uuid, auth.uid())
    on conflict (id) do update set name = excluded.name, status = excluded.status, meal_plan_id = excluded.meal_plan_id
      where public.shopping_lists.household_id = h;
  if not found then raise exception 'Shopping list was not found'; end if;
  if shopping_list->>'mealPlanId' is not null and not exists (select 1 from public.meal_plans
    where id = (shopping_list->>'mealPlanId')::uuid and household_id = h) then raise exception 'Plan was not found'; end if;
  -- Received/purchased lines are actual history and survive plan-driven regeneration.
  delete from public.shopping_items old where old.shopping_list_id = target_id and old.received_at is null
    and not exists (select 1 from jsonb_array_elements(shopping_list->'items') new where new->>'id' = old.id::text);
  for value in select * from jsonb_array_elements(shopping_list->'items') loop
    item_id := coalesce(nullif(value->>'id', '')::uuid, gen_random_uuid());
    if exists (select 1 from public.shopping_items where id = item_id and shopping_list_id <> target_id) then
      raise exception 'Shopping item belongs to another list'; end if;
    insert into public.shopping_items(id, shopping_list_id, name, quantity, unit, store_name, store_priority, source, purchased, purchased_quantity, position)
      values (item_id, target_id, value->>'name', nullif(value->>'quantity', '')::numeric, value->>'unit', value->>'store',
        nullif(value->>'storePriority', '')::integer, coalesce(value->'source', '{}'::jsonb), coalesce((value->>'purchased')::boolean, false),
        nullif(value->>'purchasedQuantity', '')::numeric, position_index)
      on conflict (id) do update set name = excluded.name, quantity = excluded.quantity, unit = excluded.unit,
        store_name = excluded.store_name, store_priority = excluded.store_priority, source = excluded.source,
        purchased = case when public.shopping_items.received_at is not null then true else excluded.purchased end,
        position = excluded.position;
    position_index := position_index + 1;
  end loop;
  return public.get_shopping_list(target_id::text);
end;
$$;
