-- Recipes and ready foods share library identity, links, and household access.
alter table public.recipes add column kind text not null default 'recipe'
  check (kind in ('recipe', 'ready_food'));
alter table public.recipes add constraint ready_food_no_ingredients
  check (kind <> 'ready_food' or ingredients = '[]'::jsonb);

-- Reusable meals are compositions, separate from dated plan occurrences.
create table public.meals (
  id uuid primary key default gen_random_uuid(),
  household_id uuid not null references public.households(id) on delete cascade,
  name text not null check (char_length(trim(name)) between 1 and 180),
  servings numeric not null check (servings > 0 and servings = round(servings, 3) and servings::text not in ('NaN', 'Infinity', '-Infinity')),
  notes text not null default '' check (char_length(notes) <= 4000),
  components jsonb not null check (jsonb_typeof(components) = 'array' and jsonb_array_length(components) between 1 and 30),
  revision integer not null default 1 check (revision > 0),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  archived_at timestamptz
);
create index meals_household_updated on public.meals(household_id, updated_at desc, id desc) where archived_at is null;
alter table public.meals enable row level security;
create policy meals_read on public.meals for select to authenticated using (public.is_household_member(household_id));
create policy meals_insert on public.meals for insert to authenticated with check (public.is_household_member(household_id));
create policy meals_update on public.meals for update to authenticated using (public.is_household_member(household_id)) with check (public.is_household_member(household_id));
revoke all on public.meals from public, anon, authenticated;
grant select, insert, update on public.meals to authenticated;

-- Validate direct table writes too; JSON references do not have foreign keys.
create function public.validate_saved_meal() returns trigger language plpgsql security invoker set search_path = '' as $$
declare c jsonb; ids uuid[] := '{}'; component_id uuid;
begin
  if tg_op = 'UPDATE' then
    if new.household_id <> old.household_id or new.id <> old.id then raise exception 'Meal identity cannot change'; end if;
    if old.archived_at is not null and new is distinct from old then raise exception 'Archived meals cannot be edited'; end if;
    new.created_at := old.created_at;
    new.revision := old.revision + case when (new.name, new.servings, new.notes, new.components) is distinct from (old.name, old.servings, old.notes, old.components) then 1 else 0 end;
  else
    new.revision := 1;
    new.created_at := now();
  end if;
  new.updated_at := now();
  -- Archiving must remain possible even when a referenced recipe has been archived.
  if tg_op = 'UPDATE' and (new.name, new.servings, new.notes, new.components) is not distinct from (old.name, old.servings, old.notes, old.components) then return new; end if;
  for c in select value from jsonb_array_elements(new.components) loop
    component_id := (c->>'id')::uuid;
    if jsonb_typeof(c) <> 'object' or component_id is null or component_id = any(ids)
      or nullif(trim(c->>'name'), '') is null or char_length(c->>'name') > 180
      or coalesce(c->>'source', '') not in ('ready', 'cook', 'external')
      or coalesce(c->>'action', '') not in ('cook', 'heat', 'serve')
      or c->>'taskId' is not null or c->>'pantryItemId' is not null
      or char_length(coalesce(c->>'unit', '')) > 40 or char_length(coalesce(c->>'notes', '')) > 4000 then
      raise exception 'Invalid saved meal component';
    end if;
    ids := array_append(ids, component_id);
    if c->>'quantity' is not null and ((c->>'quantity')::numeric <= 0
      or (c->>'quantity')::numeric <> round((c->>'quantity')::numeric, 3)
      or (c->>'quantity')::numeric::text in ('NaN', 'Infinity', '-Infinity')) then raise exception 'Invalid component quantity'; end if;
    if (c->>'source' = 'cook' and c->>'recipeId' is null)
      or (c->>'source' not in ('cook', 'ready') and c->>'recipeId' is not null) then raise exception 'Cook components require a recipe'; end if;
    if c->>'recipeId' is not null and not exists (select 1 from public.recipes where id = (c->>'recipeId')::uuid
      and household_id = new.household_id and archived_at is null) then raise exception 'Recipe was not found or is archived in this household'; end if;
    if c->>'recipeId' is not null and not exists (select 1 from public.recipes where id = (c->>'recipeId')::uuid
      and ((kind = 'ready_food' and c->>'source' = 'ready') or (kind = 'recipe' and c->>'source' = 'cook'))) then raise exception 'Component source must match recipe kind'; end if;
  end loop;
  return new;
end;
$$;
create trigger validate_saved_meal before insert or update on public.meals for each row execute function public.validate_saved_meal();

create function public.meal_document(meal public.meals) returns jsonb language sql stable security invoker set search_path = '' as $$
  select jsonb_build_object('id', meal.id, 'name', meal.name, 'servings', meal.servings, 'notes', meal.notes,
    'components', meal.components, 'revision', meal.revision, 'createdAt', meal.created_at,
    'updatedAt', meal.updated_at, 'archivedAt', meal.archived_at);
$$;
create function public.get_meal(requested_meal_id uuid) returns jsonb language sql stable security invoker set search_path = '' as $$
  select public.meal_document(m) from public.meals m where id = requested_meal_id and household_id = public.active_household_id();
$$;
create function public.search_meals(search_text text default '', result_limit integer default 50, result_offset integer default 0)
returns jsonb language plpgsql stable security invoker set search_path = '' as $$
declare result jsonb;
begin
  if result_limit is null or result_limit not between 1 and 100 or result_offset is null or result_offset not between 0 and 10000
    or char_length(coalesce(search_text, '')) > 200 then raise exception 'Invalid meal search or pagination'; end if;
  with matches as (
    select m.* from public.meals m where m.household_id = public.active_household_id() and m.archived_at is null
      and position(lower(coalesce(search_text, '')) in lower(m.name || ' ' || m.notes || ' ' || m.components::text)) > 0
  ), page as (select * from matches order by updated_at desc, id desc limit result_limit offset result_offset)
  select jsonb_build_object('items', coalesce((select jsonb_agg(public.meal_document(p) order by updated_at desc, id desc) from page p), '[]'::jsonb),
    'total', (select count(*) from matches), 'query', coalesce(search_text, ''), 'limit', result_limit, 'offset', result_offset) into result;
  return result;
end;
$$;
create function public.save_meal(meal jsonb) returns jsonb language plpgsql security invoker set search_path = '' as $$
declare h uuid := public.active_household_id(); target_id uuid := coalesce((meal->>'id')::uuid, gen_random_uuid());
begin
  if h is null or not public.is_household_member(h) then raise exception 'Household required'; end if;
  insert into public.meals(id, household_id, name, servings, notes, components)
    values (target_id, h, trim(meal->>'name'), (meal->>'servings')::numeric, coalesce(meal->>'notes', ''), meal->'components')
    on conflict (id) do update set name = excluded.name, servings = excluded.servings, notes = excluded.notes, components = excluded.components
      where public.meals.household_id = h and public.meals.archived_at is null;
  if not found then raise exception 'Meal was not found or is archived in this household'; end if;
  return public.get_meal(target_id);
end;
$$;
create function public.archive_meal(requested_meal_id uuid) returns jsonb language plpgsql security invoker set search_path = '' as $$
begin
  update public.meals set archived_at = now() where id = requested_meal_id and household_id = public.active_household_id() and archived_at is null;
  if public.get_meal(requested_meal_id) is null then raise exception 'Meal was not found in this household'; end if;
  return public.get_meal(requested_meal_id);
end;
$$;
revoke all on function public.validate_saved_meal(), public.meal_document(public.meals), public.get_meal(uuid), public.search_meals(text, integer, integer), public.save_meal(jsonb), public.archive_meal(uuid) from public, anon;
grant execute on function public.meal_document(public.meals), public.get_meal(uuid), public.search_meals(text, integer, integer), public.save_meal(jsonb), public.archive_meal(uuid) to authenticated;

alter table public.meal_plan_entries add column source_meal jsonb check (source_meal is null or jsonb_typeof(source_meal) = 'object');
create function public.validate_plan_meal_origin() returns trigger language plpgsql security invoker set search_path = '' as $$
declare h uuid; origin public.meals%rowtype; existing public.meal_plan_entries%rowtype;
begin
  if tg_op = 'UPDATE' and new.meal_plan_id <> old.meal_plan_id then raise exception 'Planned meals cannot move between plans'; end if;
  if tg_op = 'UPDATE' and new.source_meal is not distinct from old.source_meal then return new; end if;
  -- BEFORE INSERT runs before ON CONFLICT chooses UPDATE. Preserve old provenance
  -- during an upsert even when the reusable meal was edited or archived later.
  if tg_op = 'INSERT' then
    select * into existing from public.meal_plan_entries where id = new.id;
    if existing.id is not null and existing.meal_plan_id = new.meal_plan_id
      and existing.source_meal is not distinct from new.source_meal then return new; end if;
  end if;
  if tg_op = 'UPDATE' and old.source_meal is not null then raise exception 'Planned meal origin cannot change'; end if;
  if new.source_meal is null then return new; end if;
  select household_id into h from public.meal_plans where id = new.meal_plan_id;
  select * into origin from public.meals where id = (new.source_meal->>'id')::uuid and household_id = h and archived_at is null;
  if origin.id is null or new.source_meal is distinct from jsonb_build_object('id', origin.id, 'name', origin.name, 'revision', origin.revision) then
    raise exception 'Saved meal changed or was not found in this household'; end if;
  return new;
end;
$$;
create trigger validate_plan_meal_origin before insert or update on public.meal_plan_entries for each row execute function public.validate_plan_meal_origin();
revoke all on function public.validate_plan_meal_origin() from public, anon;

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
      'sourceMeal', e.source_meal, 'servings', e.servings, 'notes', e.notes, 'components', e.components, 'completedAt', e.completed_at
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
    insert into public.meal_plan_entries(id, meal_plan_id, planned_for, slot, slot_name, title, servings, notes, components, source_meal, position)
      values (coalesce((e->>'id')::uuid, gen_random_uuid()), target_id, (e->>'date')::date, e->>'slot', e->>'slotName',
        e->>'meal', nullif(e->>'servings', '')::numeric, e->>'notes', coalesce(e->'components', '[]'::jsonb), nullif(e->'sourceMeal', 'null'::jsonb), position_index)
      on conflict (id) do update set planned_for = excluded.planned_for, slot = excluded.slot, slot_name = excluded.slot_name,
        title = excluded.title, servings = excluded.servings, notes = excluded.notes, components = excluded.components, source_meal = excluded.source_meal, position = excluded.position;
    position_index := position_index + 1;
  end loop;
  return public.get_meal_plan(w::text);
end;
$$;


create or replace function public.get_recipe_graph_data()
returns jsonb language sql stable security invoker set search_path = '' as $$
  select jsonb_build_object(
    'recipes', coalesce((select jsonb_agg(jsonb_build_object('id', r.id, 'title', r.title, 'kind', r.kind,
      'tags', r.tags, 'cuisines', r.cuisines, 'eating_goals', r.eating_goals,
      'meal_types', r.meal_types, 'diets', r.diets, 'description', r.description,
      'total_minutes', r.total_minutes, 'active_minutes', r.active_minutes, 'servings', r.servings, 'ingredients', r.ingredients) order by lower(r.title), r.id)
      from public.recipes r where r.household_id = public.active_household_id() and r.archived_at is null), '[]'::jsonb),
    'relationships', coalesce((select jsonb_agg(jsonb_build_object('id', e.id,
      'sourceRecipeId', e.source_recipe_id, 'targetRecipeId', e.target_recipe_id,
      'type', e.relationship_type, 'label', null) order by e.id)
      from public.recipe_relationships e
      join public.recipes a on a.id = e.source_recipe_id and a.archived_at is null
      join public.recipes b on b.id = e.target_recipe_id and b.archived_at is null
      where e.household_id = public.active_household_id()), '[]'::jsonb));
$$;

create or replace function public.create_recipe_share(requested_recipe_id uuid, requested_expires_at timestamptz default null)
returns jsonb
language plpgsql
security definer
set search_path = pg_catalog, extensions, public
as $$
declare
  recipe_row public.recipes%rowtype;
  raw_token text;
  new_id uuid;
begin
  if auth.uid() is null then raise exception 'authentication required'; end if;
  if requested_expires_at is not null and requested_expires_at <= now() then
    raise exception 'expiration must be in the future';
  end if;
  select r.* into recipe_row
    from public.recipes r
    where r.id = requested_recipe_id and r.archived_at is null
      and public.is_household_member(r.household_id);
  if not found then raise exception 'recipe not found'; end if;

  raw_token := encode(gen_random_bytes(32), 'hex');
  insert into public.share_links (
    household_id, created_by, artifact_type, source_recipe_id,
    snapshot, token_hash, expires_at
  ) values (
    recipe_row.household_id, auth.uid(), 'recipe', recipe_row.id,
    jsonb_build_object(
      'title', recipe_row.title,
      'kind', recipe_row.kind,
      'description', recipe_row.description,
      'servings', recipe_row.servings,
      'activeMinutes', recipe_row.active_minutes,
      'totalMinutes', recipe_row.total_minutes,
      'tags', recipe_row.tags,
      'ingredients', recipe_row.ingredients,
      'instructions', recipe_row.instructions,
      'sourceType', recipe_row.source_type,
      'sourceUrl', recipe_row.source_url
    ),
    digest(raw_token, 'sha256'), requested_expires_at
  ) returning id into new_id;
  return jsonb_build_object('id', new_id, 'token', raw_token, 'expiresAt', requested_expires_at);
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
    household_id, kind, title, description, servings, active_minutes, total_minutes,
    tags, ingredients, instructions, source_type, source_url, source_snapshot
  ) values (
    target_household_id,
    coalesce(shared.snapshot->>'kind', 'recipe'),
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
