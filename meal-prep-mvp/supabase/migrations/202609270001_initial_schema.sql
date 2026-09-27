create extension if not exists pgcrypto;

create type public.household_role as enum ('owner', 'adult', 'member', 'restricted');
create type public.quantity_confidence as enum ('exact', 'estimated', 'unknown');

create table public.households (
  id uuid primary key default gen_random_uuid(),
  name text not null check (char_length(name) between 1 and 120),
  created_by uuid not null references auth.users(id) on delete restrict,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table public.household_members (
  household_id uuid not null references public.households(id) on delete cascade,
  user_id uuid not null references auth.users(id) on delete cascade,
  role public.household_role not null default 'member',
  joined_at timestamptz not null default now(),
  primary key (household_id, user_id)
);

create table public.household_preferences (
  household_id uuid primary key references public.households(id) on delete cascade,
  household_size integer not null default 1 check (household_size between 1 and 30),
  dietary_restrictions jsonb not null default '[]'::jsonb check (jsonb_typeof(dietary_restrictions) = 'array'),
  store_priority jsonb not null default '[]'::jsonb check (jsonb_typeof(store_priority) = 'array'),
  planning_preferences jsonb not null default '{}'::jsonb check (jsonb_typeof(planning_preferences) = 'object'),
  updated_at timestamptz not null default now()
);

create table public.recipes (
  id uuid primary key default gen_random_uuid(),
  household_id uuid not null references public.households(id) on delete cascade,
  title text not null check (char_length(title) between 1 and 180),
  description text not null default '',
  servings numeric(8,2) not null default 4 check (servings > 0),
  active_minutes integer check (active_minutes is null or active_minutes >= 0),
  total_minutes integer check (total_minutes is null or total_minutes >= 0),
  tags text[] not null default '{}',
  ingredients jsonb not null default '[]'::jsonb check (jsonb_typeof(ingredients) = 'array'),
  instructions jsonb not null default '[]'::jsonb check (jsonb_typeof(instructions) = 'array'),
  source_type text not null default 'manual',
  source_url text,
  source_snapshot jsonb,
  archived_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table public.pantry_items (
  id uuid primary key default gen_random_uuid(),
  household_id uuid not null references public.households(id) on delete cascade,
  name text not null check (char_length(name) between 1 and 160),
  quantity numeric(12,3),
  unit text,
  storage_location text not null default 'pantry',
  quantity_confidence public.quantity_confidence not null default 'estimated',
  acquired_at date,
  use_by_date date,
  freshness_basis text,
  provenance jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table public.meal_plans (
  id uuid primary key default gen_random_uuid(),
  household_id uuid not null references public.households(id) on delete cascade,
  week_start date not null,
  status text not null default 'draft' check (status in ('draft', 'active', 'archived')),
  version integer not null default 1 check (version > 0),
  created_by uuid not null default auth.uid() references auth.users(id) on delete restrict,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (household_id, week_start, version)
);

create table public.meal_plan_entries (
  id uuid primary key default gen_random_uuid(),
  meal_plan_id uuid not null references public.meal_plans(id) on delete cascade,
  planned_for date not null,
  slot text not null default 'dinner',
  title text not null,
  recipe_id uuid references public.recipes(id) on delete set null,
  servings numeric(8,2) check (servings is null or servings > 0),
  notes text,
  position integer not null default 0,
  created_at timestamptz not null default now()
);

create table public.shopping_lists (
  id uuid primary key default gen_random_uuid(),
  household_id uuid not null references public.households(id) on delete cascade,
  meal_plan_id uuid references public.meal_plans(id) on delete set null,
  name text not null default 'Weekly groceries',
  status text not null default 'draft' check (status in ('draft', 'active', 'completed', 'archived')),
  created_by uuid not null default auth.uid() references auth.users(id) on delete restrict,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table public.shopping_items (
  id uuid primary key default gen_random_uuid(),
  shopping_list_id uuid not null references public.shopping_lists(id) on delete cascade,
  name text not null,
  quantity numeric(12,3),
  unit text,
  store_name text,
  store_priority integer,
  source jsonb not null default '{}'::jsonb,
  purchased boolean not null default false,
  purchased_quantity numeric(12,3),
  purchased_at timestamptz,
  position integer not null default 0,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table public.decision_records (
  id uuid primary key default gen_random_uuid(),
  household_id uuid not null references public.households(id) on delete cascade,
  actor_id uuid not null default auth.uid() references auth.users(id) on delete restrict,
  action text not null,
  decision text not null,
  context jsonb not null default '{}'::jsonb,
  outcome jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

create or replace function public.touch_updated_at()
returns trigger language plpgsql as $$
begin
  new.updated_at = now();
  return new;
end;
$$;

create trigger households_touch before update on public.households for each row execute function public.touch_updated_at();
create trigger household_preferences_touch before update on public.household_preferences for each row execute function public.touch_updated_at();
create trigger recipes_touch before update on public.recipes for each row execute function public.touch_updated_at();
create trigger pantry_items_touch before update on public.pantry_items for each row execute function public.touch_updated_at();
create trigger meal_plans_touch before update on public.meal_plans for each row execute function public.touch_updated_at();
create trigger shopping_lists_touch before update on public.shopping_lists for each row execute function public.touch_updated_at();
create trigger shopping_items_touch before update on public.shopping_items for each row execute function public.touch_updated_at();

create or replace function public.is_household_member(target_household_id uuid)
returns boolean
language sql
stable
security definer
set search_path = public
as $$
  select exists (
    select 1 from public.household_members
    where household_id = target_household_id and user_id = auth.uid()
  );
$$;

revoke all on function public.is_household_member(uuid) from public;
grant execute on function public.is_household_member(uuid) to authenticated;

alter table public.households enable row level security;
alter table public.household_members enable row level security;
alter table public.household_preferences enable row level security;
alter table public.recipes enable row level security;
alter table public.pantry_items enable row level security;
alter table public.meal_plans enable row level security;
alter table public.meal_plan_entries enable row level security;
alter table public.shopping_lists enable row level security;
alter table public.shopping_items enable row level security;
alter table public.decision_records enable row level security;

create policy households_select on public.households for select to authenticated using (public.is_household_member(id));
create policy households_update on public.households for update to authenticated using (created_by = auth.uid()) with check (created_by = auth.uid());
create policy members_select on public.household_members for select to authenticated using (public.is_household_member(household_id));
create policy preferences_all on public.household_preferences for all to authenticated using (public.is_household_member(household_id)) with check (public.is_household_member(household_id));
create policy recipes_all on public.recipes for all to authenticated using (public.is_household_member(household_id)) with check (public.is_household_member(household_id));
create policy pantry_all on public.pantry_items for all to authenticated using (public.is_household_member(household_id)) with check (public.is_household_member(household_id));
create policy plans_all on public.meal_plans for all to authenticated using (public.is_household_member(household_id)) with check (public.is_household_member(household_id));
create policy plan_entries_all on public.meal_plan_entries for all to authenticated
  using (exists (select 1 from public.meal_plans p where p.id = meal_plan_id and public.is_household_member(p.household_id)))
  with check (exists (select 1 from public.meal_plans p where p.id = meal_plan_id and public.is_household_member(p.household_id)));
create policy shopping_lists_all on public.shopping_lists for all to authenticated using (public.is_household_member(household_id)) with check (public.is_household_member(household_id));
create policy shopping_items_all on public.shopping_items for all to authenticated
  using (exists (select 1 from public.shopping_lists l where l.id = shopping_list_id and public.is_household_member(l.household_id)))
  with check (exists (select 1 from public.shopping_lists l where l.id = shopping_list_id and public.is_household_member(l.household_id)));
create policy decisions_select on public.decision_records for select to authenticated using (public.is_household_member(household_id));
create policy decisions_insert on public.decision_records for insert to authenticated with check (public.is_household_member(household_id) and actor_id = auth.uid());

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
  insert into public.household_preferences(household_id, household_size, store_priority, planning_preferences)
  values (
    created_id,
    1,
    '[{"store":"Costco","priority":1},{"store":"Safeway","priority":2}]'::jsonb,
    '{"weeknightMaxMinutes":30,"leftoversForLunch":true}'::jsonb
  );
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
    'planningPreferences', p.planning_preferences
  )
  from public.household_members hm
  join public.households h on h.id = hm.household_id
  join public.household_preferences p on p.household_id = h.id
  where hm.user_id = auth.uid()
  order by hm.joined_at
  limit 1;
$$;

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
  return public.get_meal_plan(target_week_start);
end;
$$;

create or replace function public.get_meal_plan(requested_week_start text default null)
returns jsonb
language sql
stable
security invoker
as $$
  select jsonb_build_object(
    'id', p.id,
    'weekStart', p.week_start,
    'status', p.status,
    'version', p.version,
    'entries', coalesce((
      select jsonb_agg(jsonb_build_object(
        'id', e.id,
        'date', e.planned_for,
        'day', trim(to_char(e.planned_for, 'Day')),
        'slot', e.slot,
        'meal', e.title,
        'recipeId', e.recipe_id,
        'servings', e.servings,
        'notes', e.notes
      ) order by e.planned_for, e.position)
      from public.meal_plan_entries e where e.meal_plan_id = p.id
    ), '[]'::jsonb)
  )
  from public.meal_plans p
  where public.is_household_member(p.household_id)
    and (requested_week_start is null or p.week_start = requested_week_start::date)
  order by p.week_start desc, p.version desc
  limit 1;
$$;

create or replace function public.save_shopping_list(shopping_list jsonb)
returns jsonb
language plpgsql
security invoker
as $$
declare
  target_household_id uuid;
  target_list_id uuid;
  item jsonb;
  item_index integer := 0;
begin
  select household_id into target_household_id from public.household_members where user_id = auth.uid() order by joined_at limit 1;
  if target_household_id is null then raise exception 'household required'; end if;
  target_list_id := coalesce((shopping_list->>'id')::uuid, gen_random_uuid());
  insert into public.shopping_lists(id, household_id, meal_plan_id, name, status, created_by)
  values (
    target_list_id,
    target_household_id,
    nullif(shopping_list->>'mealPlanId', '')::uuid,
    coalesce(shopping_list->>'name', 'Weekly groceries'),
    coalesce(shopping_list->>'status', 'draft'),
    auth.uid()
  )
  on conflict (id) do update set name = excluded.name, status = excluded.status, meal_plan_id = excluded.meal_plan_id, updated_at = now()
  where public.shopping_lists.household_id = target_household_id;
  delete from public.shopping_items where shopping_list_id = target_list_id;
  for item in select value from jsonb_array_elements(coalesce(shopping_list->'items', '[]'::jsonb)) loop
    insert into public.shopping_items(id, shopping_list_id, name, quantity, unit, store_name, store_priority, source, purchased, position)
    values (
      coalesce(nullif(item->>'id', '')::uuid, gen_random_uuid()),
      target_list_id,
      item->>'name',
      nullif(item->>'quantity', '')::numeric,
      item->>'unit',
      coalesce(item->>'store', item->>'storeName'),
      nullif(coalesce(item->>'storePriority', item->>'priority'), '')::integer,
      coalesce(item->'source', '{}'::jsonb),
      coalesce((item->>'purchased')::boolean, false),
      item_index
    );
    item_index := item_index + 1;
  end loop;
  return public.get_shopping_list(target_list_id::text);
end;
$$;

create or replace function public.get_shopping_list(requested_list_id text default null)
returns jsonb
language sql
stable
security invoker
as $$
  select jsonb_build_object(
    'id', l.id,
    'name', l.name,
    'status', l.status,
    'mealPlanId', l.meal_plan_id,
    'items', coalesce((
      select jsonb_agg(jsonb_build_object(
        'id', i.id,
        'name', i.name,
        'quantity', i.quantity,
        'unit', i.unit,
        'store', i.store_name,
        'storePriority', i.store_priority,
        'source', i.source,
        'purchased', i.purchased,
        'purchasedQuantity', i.purchased_quantity
      ) order by i.store_priority nulls last, i.position)
      from public.shopping_items i where i.shopping_list_id = l.id
    ), '[]'::jsonb)
  )
  from public.shopping_lists l
  where public.is_household_member(l.household_id)
    and (requested_list_id is null or l.id = requested_list_id::uuid)
  order by l.updated_at desc
  limit 1;
$$;

revoke all on function public.bootstrap_my_household(text) from public;
revoke all on function public.get_household_context() from public;
revoke all on function public.save_meal_plan(jsonb) from public;
revoke all on function public.get_meal_plan(text) from public;
revoke all on function public.save_shopping_list(jsonb) from public;
revoke all on function public.get_shopping_list(text) from public;
grant execute on function public.bootstrap_my_household(text) to authenticated;
grant execute on function public.get_household_context() to authenticated;
grant execute on function public.save_meal_plan(jsonb) to authenticated;
grant execute on function public.get_meal_plan(text) to authenticated;
grant execute on function public.save_shopping_list(jsonb) to authenticated;
grant execute on function public.get_shopping_list(text) to authenticated;
