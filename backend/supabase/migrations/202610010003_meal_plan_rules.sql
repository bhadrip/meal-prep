-- English planning instructions, saved as immutable household revisions.
create table public.meal_plan_rule_revisions (
  id uuid primary key default gen_random_uuid(),
  household_id uuid not null references public.households(id) on delete cascade,
  revision integer not null check (revision > 0),
  text text not null check (char_length(text) <= 10000),
  created_by uuid not null default auth.uid() references auth.users(id) on delete restrict,
  created_at timestamptz not null default now(),
  unique (household_id, revision), unique (household_id, id)
);
alter table public.meal_plan_rule_revisions enable row level security;
revoke all on public.meal_plan_rule_revisions from public, anon, authenticated;
grant select on public.meal_plan_rule_revisions to authenticated;
create policy rule_revisions_select on public.meal_plan_rule_revisions for select to authenticated
  using (public.is_household_member(household_id));

create function public.save_meal_plan_rules(rule_text text, expected_revision integer)
returns jsonb language plpgsql security definer set search_path = '' as $$
declare
  target_id uuid := public.active_household_id();
  current_row public.meal_plan_rule_revisions%rowtype;
  saved_row public.meal_plan_rule_revisions%rowtype;
  clean_text text := btrim(rule_text);
begin
  if target_id is null or not public.is_household_member(target_id) then raise exception 'Household required'; end if;
  if clean_text is null or char_length(rule_text) > 10000 then raise exception 'Rules must be text of at most 10000 characters'; end if;
  if expected_revision is null or expected_revision < 0 then raise exception 'expectedRevision must be a nonnegative integer'; end if;
  -- Serialize saves, including the first revision of a household document.
  perform 1 from public.households where id = target_id for update;
  select * into current_row from public.meal_plan_rule_revisions
    where household_id = target_id order by revision desc limit 1;
  if expected_revision <> coalesce(current_row.revision, 0) then
    raise exception 'Meal plan rules changed. Reload the current rules before saving.';
  end if;
  if current_row.id is not null and current_row.text = clean_text then
    saved_row := current_row;
  else
    insert into public.meal_plan_rule_revisions(household_id, revision, text)
      values (target_id, expected_revision + 1, clean_text) returning * into saved_row;
  end if;
  return jsonb_build_object('id', saved_row.id, 'revision', saved_row.revision,
    'text', saved_row.text, 'createdAt', saved_row.created_at);
end;
$$;
revoke all on function public.save_meal_plan_rules(text, integer) from public;
grant execute on function public.save_meal_plan_rules(text, integer) to authenticated;

alter table public.weekly_schedules add column notes text not null default '' check (char_length(notes) <= 3000);
alter table public.meal_plans add column rule_revision_id uuid;
alter table public.meal_plans add constraint meal_plan_rule_household_fk
  foreign key (household_id, rule_revision_id) references public.meal_plan_rule_revisions(household_id, id);

create or replace function public.get_meal_plan(requested_week_start text default null)
returns jsonb language sql stable security invoker set search_path = '' as $$
  select jsonb_build_object(
    'id', p.id, 'weekStart', p.week_start, 'status', p.status, 'version', p.version,
    'ruleRevisionId', p.rule_revision_id,
    'ruleRevision', (select jsonb_build_object('id', r.id, 'revision', r.revision, 'text', r.text, 'createdAt', r.created_at)
      from public.meal_plan_rule_revisions r where r.id = p.rule_revision_id),
    'entries', coalesce((select jsonb_agg(jsonb_build_object(
      'id', e.id, 'date', e.planned_for, 'day', trim(to_char(e.planned_for, 'Day')),
      'slot', e.slot, 'meal', e.title, 'recipeId', e.recipe_id, 'servings', e.servings, 'notes', e.notes
    ) order by e.planned_for, e.position) from public.meal_plan_entries e where e.meal_plan_id = p.id), '[]'::jsonb)
  ) from public.meal_plans p
  where p.household_id = public.active_household_id()
    and (requested_week_start is null or p.week_start = requested_week_start::date)
  order by p.week_start desc, p.version desc limit 1;
$$;

create or replace function public.save_meal_plan(plan jsonb)
returns jsonb language plpgsql security invoker set search_path = '' as $$
declare
  target_household_id uuid := public.active_household_id();
  target_plan_id uuid;
  target_week_start date := (plan->>'weekStart')::date;
  target_rule_id uuid;
  entry jsonb;
  entry_index integer := 0;
begin
  if target_household_id is null then raise exception 'Household required'; end if;
  target_plan_id := nullif(plan->>'id', '')::uuid;
  if target_plan_id is null then
    select id into target_plan_id from public.meal_plans
      where household_id = target_household_id and week_start = target_week_start order by version desc limit 1;
  end if;
  target_plan_id := coalesce(target_plan_id, gen_random_uuid());
  if plan ? 'ruleRevisionId' then target_rule_id := nullif(plan->>'ruleRevisionId', '')::uuid;
  else select rule_revision_id into target_rule_id from public.meal_plans where id = target_plan_id; end if;
  if target_rule_id is not null and not exists (select 1 from public.meal_plan_rule_revisions
    where id = target_rule_id and household_id = target_household_id) then
    raise exception 'Meal plan rule revision was not found';
  end if;
  insert into public.meal_plans(id, household_id, week_start, status, created_by, rule_revision_id)
    values (target_plan_id, target_household_id, target_week_start, coalesce(plan->>'status', 'draft'), auth.uid(), target_rule_id)
    on conflict (id) do update set week_start = excluded.week_start, status = excluded.status,
      version = public.meal_plans.version + 1, rule_revision_id = excluded.rule_revision_id, updated_at = now()
    where public.meal_plans.household_id = target_household_id;
  delete from public.meal_plan_entries where meal_plan_id = target_plan_id;
  for entry in select value from jsonb_array_elements(coalesce(plan->'entries', '[]'::jsonb)) loop
    insert into public.meal_plan_entries(meal_plan_id, planned_for, slot, title, recipe_id, servings, notes, position)
    values (target_plan_id, coalesce((entry->>'date')::date, target_week_start + entry_index),
      coalesce(entry->>'slot', 'dinner'), coalesce(entry->>'meal', entry->>'title'),
      nullif(entry->>'recipeId', '')::uuid, nullif(entry->>'servings', '')::numeric, entry->>'notes', entry_index);
    entry_index := entry_index + 1;
  end loop;
  return public.get_meal_plan(target_week_start::text);
end;
$$;

create function public.get_recent_meal_plans(before_week date, result_limit integer default 2)
returns jsonb language sql stable security invoker set search_path = '' as $$
  select coalesce(jsonb_agg(public.get_meal_plan(weeks.week_start::text) order by weeks.week_start desc), '[]'::jsonb)
  from (select distinct week_start from public.meal_plans
    where household_id = public.active_household_id() and week_start < before_week
    order by week_start desc limit least(greatest(result_limit, 1), 10)) weeks;
$$;
revoke all on function public.get_recent_meal_plans(date, integer) from public;
grant execute on function public.get_recent_meal_plans(date, integer) to authenticated;
