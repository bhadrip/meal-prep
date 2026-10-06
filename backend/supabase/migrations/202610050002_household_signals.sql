-- Optional reported signals extend the existing unified feedback model.
-- The history records domain writes, not page views, chat transcripts or inferred outcomes.
create function public.valid_reported_signals(s jsonb)
returns boolean language plpgsql immutable set search_path = '' as $$
declare k text; v jsonb; n numeric; r jsonb; seen text[] := '{}';
begin
  if s is null or jsonb_typeof(s) <> 'object' or octet_length(s::text) > 16000 then return false; end if;
  for k, v in select * from jsonb_each(s) loop
    if k not in ('goal','goalNote','actualMinutes','effort','stressBefore','stressAfter','planStatus','actualMeal','whoCooked','changeReason','context','responses','leftovers','wasteQuantity','wasteUnit','actualCost','currency','startedAt','finishedAt') then return false; end if;
    if v = 'null'::jsonb then continue; end if;
    if k in ('actualMinutes','effort','stressBefore','stressAfter','wasteQuantity','actualCost') then
      if jsonb_typeof(v) <> 'number' then return false; end if;
      n := (v #>> '{}')::numeric;
      if n < 0 or n > 100000 then return false; end if;
      if k in ('actualMinutes','effort','stressBefore','stressAfter') and (v #>> '{}') !~ '^[0-9]+$' then return false; end if;
      if k = 'actualMinutes' and n > 1440 then return false; end if;
      if k in ('effort','stressBefore','stressAfter') and n not between 1 and 5 then return false; end if;
    elsif k = 'context' then
      if jsonb_typeof(v) <> 'array' or jsonb_array_length(v) > 8 then return false; end if;
      if exists (select 1 from jsonb_array_elements(v) x where jsonb_typeof(x) <> 'string'
        or x #>> '{}' not in ('guests','illness','late_schedule','travel','school_break','missing_ingredient','equipment_problem','other')) then return false; end if;
      if (select count(distinct x) from jsonb_array_elements(v) x) <> jsonb_array_length(v) then return false; end if;
    elsif k = 'responses' then
      if jsonb_typeof(v) <> 'array' or jsonb_array_length(v) > 20 then return false; end if;
      for r in select * from jsonb_array_elements(v) loop
        if jsonb_typeof(r) <> 'object' or (select count(*) from jsonb_object_keys(r)) <> 2
          or jsonb_typeof(r->'audience') is distinct from 'string'
          or length(trim(r->>'audience')) not between 1 and 80
          or jsonb_typeof(r->'response') is distinct from 'string'
          or r->>'response' not in ('liked','mixed','disliked','not_tried') then return false; end if;
        if lower(trim(r->>'audience')) = any(seen) then return false; end if;
        seen := array_append(seen, lower(trim(r->>'audience')));
      end loop;
    else
      if jsonb_typeof(v) <> 'string' or length(trim(v #>> '{}')) < 1 then return false; end if;
      if k in ('goalNote','changeReason') and length(v #>> '{}') > 200 then return false; end if;
      if k = 'actualMeal' and length(v #>> '{}') > 180 then return false; end if;
      if k = 'whoCooked' and length(v #>> '{}') > 120 then return false; end if;
      if k = 'goal' and v #>> '{}' not in ('time','stress','kids_enjoyment','waste','cost','shared_work','variety','other') then return false; end if;
      if k = 'planStatus' and v #>> '{}' not in ('followed','changed','skipped','not_planned') then return false; end if;
      if k = 'leftovers' and v #>> '{}' not in ('none','saved','discarded') then return false; end if;
      if k = 'wasteUnit' and v #>> '{}' not in ('g','kg','ml','l','portion','item') then return false; end if;
      if k = 'currency' and v #>> '{}' !~ '^[A-Z]{3}$' then return false; end if;
      if k in ('startedAt','finishedAt') then
        if length(v #>> '{}') > 50 or v #>> '{}' !~ '(Z|[+-][0-9]{2}:[0-9]{2})$' then return false; end if;
        perform (v #>> '{}')::timestamptz;
      end if;
    end if;
  end loop;
  if s->>'goal' = 'other' and coalesce(length(trim(s->>'goalNote')),0) = 0 then return false; end if;
  if (s->>'wasteQuantity' is null) <> (s->>'wasteUnit' is null) then return false; end if;
  if (s->>'actualCost' is null) <> (s->>'currency' is null) then return false; end if;
  if s->>'startedAt' is not null and s->>'finishedAt' is not null
    and (s->>'finishedAt')::timestamptz < (s->>'startedAt')::timestamptz then return false; end if;
  return true;
exception when others then return false;
end $$;

alter table public.feedback_entries
  add column signals jsonb not null default '{}' check (public.valid_reported_signals(signals)),
  add column occurred_on date,
  add column input_source text not null default 'unknown' check (input_source in ('website','mcp','api','unknown')),
  add column plan_snapshot jsonb not null default '{}';
alter table public.feedback_entries drop constraint feedback_entries_feedback_type_check;
alter table public.feedback_entries add constraint feedback_entries_feedback_type_check
  check (feedback_type in ('worked_well','change_next_time','problem','preference_signal','context_update'));

-- Freeze the linked intention when the report is first saved; corrections retain it.
create function public.capture_feedback_plan() returns trigger
language plpgsql security invoker set search_path = '' as $$
begin
  if tg_op = 'UPDATE' and old.occurrence_id is not distinct from new.occurrence_id
    and old.week_start is not distinct from new.week_start then
    new.plan_snapshot := old.plan_snapshot;
  else
    select coalesce(to_jsonb(e) - 'meal_plan_id', '{}') into new.plan_snapshot
      from public.meal_occurrences o join public.meal_plan_entries e on e.id = o.meal_plan_entry_id
      where o.id = new.occurrence_id;
    new.plan_snapshot := coalesce(new.plan_snapshot, '{}');
  end if;
  return new;
end $$;
create trigger feedback_capture_plan before insert or update on public.feedback_entries
  for each row execute function public.capture_feedback_plan();

create table public.household_signal_history (
  id uuid primary key default gen_random_uuid(),
  household_id uuid not null references public.households(id) on delete cascade,
  schema_version integer not null default 1,
  source_table text not null,
  source_id uuid not null,
  operation text not null check (operation in ('insert','update','delete')),
  recorded_at timestamptz not null default clock_timestamp(),
  occurred_on date,
  actor_id uuid,
  input_source text not null default 'backend',
  before_snapshot jsonb,
  after_snapshot jsonb
);
create index household_signal_history_page on public.household_signal_history(household_id, recorded_at desc, id desc);
create index household_signal_history_source on public.household_signal_history(household_id, source_table, recorded_at desc, id desc);
alter table public.household_signal_history enable row level security;
revoke all on public.household_signal_history from public, anon, authenticated;
grant select on public.household_signal_history to authenticated;
create policy household_signal_history_read on public.household_signal_history for select to authenticated
  using (public.is_household_member(household_id));

-- Runs in the same transaction as the domain write. Failed writes leave no history.
create function public.capture_household_signal() returns trigger
language plpgsql security definer set search_path = '' as $$
declare b jsonb; a jsonb; row_value jsonb; h uuid; sid uuid;
begin
  if tg_op <> 'INSERT' then b := to_jsonb(old) - 'updated_at' - 'created_by' - 'object_path' - 'source_file_id'; end if;
  if tg_op <> 'DELETE' then a := to_jsonb(new) - 'updated_at' - 'created_by' - 'object_path' - 'source_file_id'; end if;
  if tg_op = 'UPDATE' and (b - 'version') is not distinct from (a - 'version') then return new; end if;
  row_value := coalesce(a,b);
  h := (row_value->>'household_id')::uuid;
  if tg_table_name = 'meal_plan_entries' then
    select household_id into h from public.meal_plans where id = (row_value->>'meal_plan_id')::uuid;
  elsif tg_table_name = 'shopping_items' then
    select household_id into h from public.shopping_lists where id = (row_value->>'shopping_list_id')::uuid;
  end if;
  -- A cascading household deletion must not recreate its deleted evidence.
  if h is null or not exists (select 1 from public.households where id = h) then
    return coalesce(new,old);
  end if;
  sid := coalesce(row_value->>'id',row_value->>'household_id')::uuid;
  insert into public.household_signal_history(household_id,source_table,source_id,operation,occurred_on,actor_id,input_source,before_snapshot,after_snapshot)
    values(h,tg_table_name,sid,lower(tg_op),case when tg_table_name = 'feedback_entries' then (row_value->>'occurred_on')::date end,
      auth.uid(),coalesce(row_value->>'input_source','backend'),b - 'household_id',a - 'household_id');
  return coalesce(new,old);
end $$;
revoke all on function public.capture_household_signal() from public, anon, authenticated;
do $$ declare t text; begin
  foreach t in array array['feedback_entries','meal_plans','meal_plan_entries','weekly_schedules','pantry_items','pantry_uses','plan_activities','shopping_items','pantry_photo_evidence','household_preferences','household_memories','recipes'] loop
    execute format('create trigger capture_signal after insert or update or delete on public.%I for each row execute function public.capture_household_signal()',t);
  end loop;
end $$;

create function public.get_household_signal_history(before_id uuid default null, requested_source text default null, result_limit integer default 50)
returns jsonb language plpgsql stable security invoker set search_path = '' as $$
declare h uuid := public.active_household_id(); anchor public.household_signal_history%rowtype; result jsonb;
begin
  if h is null then raise exception 'Household required'; end if;
  if before_id is not null then
    select * into anchor from public.household_signal_history where id = before_id and household_id = h;
    if not found then raise exception 'History cursor was not found in this household'; end if;
  end if;
  select coalesce(jsonb_agg(jsonb_build_object('id',e.id,'schemaVersion',e.schema_version,'sourceTable',e.source_table,'sourceId',e.source_id,
    'operation',e.operation,'recordedAt',e.recorded_at,'occurredOn',e.occurred_on,'actorId',e.actor_id,'inputSource',e.input_source,
    'before',e.before_snapshot,'after',e.after_snapshot) order by e.recorded_at desc,e.id desc),'[]') into result
    from (select * from public.household_signal_history where household_id = h
      and (requested_source is null or source_table = requested_source)
      and (before_id is null or (recorded_at,id) < (anchor.recorded_at,anchor.id))
      order by recorded_at desc,id desc limit least(greatest(result_limit,1),101)) e;
  return result;
end $$;
revoke all on function public.get_household_signal_history(uuid,text,integer) from public, anon;
grant execute on function public.get_household_signal_history(uuid,text,integer) to authenticated;

create or replace function public.save_experience_feedback(feedback jsonb)
returns jsonb
language plpgsql
security invoker
as $$
declare
  target_household_id uuid;
  target_feedback_id uuid := coalesce(nullif(feedback->>'id', '')::uuid, gen_random_uuid());
  target_occurrence_id uuid;
  target_schedule_id uuid;
  target_recipe_id uuid := nullif(feedback->>'recipeId', '')::uuid;
  occurrence_recipe_id uuid;
  occurrence_week_start date;
  target_variant_id uuid;
  target_plan_entry_id uuid := nullif(feedback->>'mealPlanEntryId', '')::uuid;
  target_week_start date := nullif(feedback->>'weekStart', '')::date;
  target_occurred_on date := nullif(feedback->>'occurredOn', '')::date;
  target_slot text := nullif(trim(feedback->>'slot'), '');
  target_title text := nullif(trim(feedback->>'mealTitle'), '');
  variant_name text := nullif(trim(feedback->>'variantName'), '');
  variant_adaptations jsonb := coalesce(feedback->'adaptations', '[]'::jsonb);
  tag_record jsonb;
  target_tag_id uuid;
  result jsonb;
begin
  target_household_id := public.active_household_id();
  if target_household_id is null then raise exception 'household required'; end if;

  target_occurrence_id := nullif(feedback->>'occurrenceId', '')::uuid;
  if target_occurrence_id is null and nullif(feedback->>'id', '') is not null then
    select occurrence_id into target_occurrence_id
    from public.feedback_entries
    where id = target_feedback_id and household_id = target_household_id;
  end if;
  if target_occurrence_id is not null then
    select
      o.recipe_id, o.week_start, coalesce(target_occurred_on, o.occurred_on),
      coalesce(target_slot, o.slot), coalesce(target_title, o.title)
    into occurrence_recipe_id, occurrence_week_start, target_occurred_on, target_slot, target_title
    from public.meal_occurrences o
    where o.id = target_occurrence_id and o.household_id = target_household_id;
    if not found then raise exception 'meal occurrence was not found'; end if;
    if target_plan_entry_id is not null and not exists (
      select 1 from public.meal_occurrences o where o.id = target_occurrence_id and o.meal_plan_entry_id = target_plan_entry_id
    ) then raise exception 'planned meal does not match meal occurrence'; end if;
    if target_recipe_id is not null and occurrence_recipe_id is distinct from target_recipe_id then
      raise exception 'recipe does not match meal occurrence';
    end if;
    if target_week_start is not null and occurrence_week_start is not null
      and occurrence_week_start <> target_week_start then
      raise exception 'week does not match meal occurrence';
    end if;
    target_recipe_id := coalesce(target_recipe_id, occurrence_recipe_id);
    target_week_start := coalesce(target_week_start, occurrence_week_start);
  end if;

  if target_plan_entry_id is not null then
    select coalesce(target_recipe_id, e.recipe_id,
      case when (select count(*) from jsonb_array_elements(e.components) c where c->>'recipeId' is not null) = 1
        then (select (c->>'recipeId')::uuid from jsonb_array_elements(e.components) c where c->>'recipeId' is not null limit 1) end),
      e.title, coalesce(target_occurred_on, e.planned_for), e.slot, p.week_start
      into target_recipe_id, target_title, target_occurred_on, target_slot, occurrence_week_start
    from public.meal_plan_entries e
    join public.meal_plans p on p.id = e.meal_plan_id
    where e.id = target_plan_entry_id and p.household_id = target_household_id;
    if not found then raise exception 'meal-plan entry was not found'; end if;
    if target_week_start is not null and target_week_start <> occurrence_week_start then
      raise exception 'week does not match planned meal';
    end if;
    target_week_start := occurrence_week_start;
  end if;

  if target_recipe_id is not null then
    select coalesce(target_title, r.title) into target_title
    from public.recipes r
    where r.id = target_recipe_id and r.household_id = target_household_id;
    if not found then raise exception 'recipe was not found'; end if;
  end if;

  if target_week_start is not null then
    select id into target_schedule_id
    from public.weekly_schedules
    where household_id = target_household_id and week_start = target_week_start;
  end if;

  if variant_name is not null then
    if target_recipe_id is null then raise exception 'variant requires a recipe'; end if;
    insert into public.recipe_variants (household_id, recipe_id, name, adaptations, created_by)
    values (target_household_id, target_recipe_id, variant_name, variant_adaptations, auth.uid())
    on conflict (household_id, recipe_id, variant_key) do update
      set adaptations = case
        when jsonb_array_length(excluded.adaptations) > 0 then excluded.adaptations
        else public.recipe_variants.adaptations
      end,
      updated_at = now()
    returning id into target_variant_id;
    select adaptations into variant_adaptations
    from public.recipe_variants where id = target_variant_id;
  end if;

  if target_occurrence_id is null and (target_recipe_id is not null or target_plan_entry_id is not null) then
    if target_plan_entry_id is not null then
      select id into target_occurrence_id
      from public.meal_occurrences
      where meal_plan_entry_id = target_plan_entry_id;
    end if;
    if target_occurrence_id is null then
      insert into public.meal_occurrences (
        household_id, meal_plan_entry_id, weekly_schedule_id, week_start,
        occurred_on, slot, title, recipe_id, recipe_variant_id, variation_snapshot
      ) values (
        target_household_id, target_plan_entry_id, target_schedule_id, target_week_start,
        target_occurred_on, target_slot, coalesce(target_title, 'Meal'), target_recipe_id,
        target_variant_id,
        case when target_variant_id is null then '{}'::jsonb else jsonb_build_object(
          'name', variant_name, 'adaptations', variant_adaptations
        ) end
      ) returning id into target_occurrence_id;
    end if;
  end if;

  if target_occurrence_id is not null and target_variant_id is not null then
    update public.meal_occurrences set
      recipe_variant_id = target_variant_id,
      variation_snapshot = jsonb_build_object(
        'name', variant_name, 'adaptations', variant_adaptations
      )
    where id = target_occurrence_id and household_id = target_household_id;
  end if;

  insert into public.feedback_entries (
    id, household_id, occurrence_id, weekly_schedule_id, week_start,
    feedback_type, note, next_time, rating, created_by, signals, occurred_on, input_source
  ) values (
    target_feedback_id, target_household_id, target_occurrence_id, target_schedule_id,
    target_week_start, coalesce(feedback->>'feedbackType', 'change_next_time'),
    trim(feedback->>'note'), coalesce(trim(feedback->>'nextTime'), ''),
    nullif(feedback->>'rating', '')::integer, auth.uid(),
    jsonb_strip_nulls(coalesce(feedback->'signals', '{}'::jsonb)),
    nullif(feedback->>'occurredOn', '')::date, coalesce(feedback->>'inputSource', 'unknown')
  )
  on conflict (id) do update set
    occurrence_id = excluded.occurrence_id,
    weekly_schedule_id = excluded.weekly_schedule_id,
    week_start = excluded.week_start,
    feedback_type = excluded.feedback_type,
    note = excluded.note,
    next_time = excluded.next_time,
    rating = excluded.rating,
    signals = case when feedback ? 'signals' then excluded.signals else public.feedback_entries.signals end,
    occurred_on = case when feedback ? 'occurredOn' then excluded.occurred_on else public.feedback_entries.occurred_on end,
    input_source = excluded.input_source,
    updated_at = now()
  where public.feedback_entries.household_id = target_household_id;

  delete from public.feedback_entry_tags where feedback_id = target_feedback_id;
  for tag_record in select value from jsonb_array_elements(coalesce(feedback->'tagRecords', '[]'::jsonb)) loop
    insert into public.feedback_tags (household_id, slug, label, facet)
    values (
      target_household_id, tag_record->>'slug', tag_record->>'label',
      coalesce(tag_record->>'facet', 'other')
    )
    on conflict (household_id, slug) do update set
      label = excluded.label, facet = excluded.facet, updated_at = now()
    returning id into target_tag_id;
    insert into public.feedback_entry_tags (feedback_id, tag_id)
    values (target_feedback_id, target_tag_id)
    on conflict do nothing;
  end loop;

  select (to_jsonb(f) - 'household_id' - 'created_by') || jsonb_build_object(
    'tags', coalesce((
      select jsonb_agg(jsonb_build_object(
        'id', t.id, 'slug', t.slug, 'label', t.label, 'facet', t.facet
      ) order by t.facet, t.slug)
      from public.feedback_entry_tags ft
      join public.feedback_tags t on t.id = ft.tag_id
      where ft.feedback_id = f.id
    ), '[]'::jsonb),
    'occurrence', case when o.id is null then null else
      (to_jsonb(o) - 'household_id') || jsonb_build_object(
        'variant', case when v.id is null then null else
          (to_jsonb(v) - 'household_id' - 'created_by')
        end
      )
    end
  ) into result
  from public.feedback_entries f
  left join public.meal_occurrences o on o.id = f.occurrence_id
  left join public.recipe_variants v on v.id = o.recipe_variant_id
  where f.id = target_feedback_id and f.household_id = target_household_id;

  if result is null then raise exception 'feedback could not be saved'; end if;
  return result;
end;
$$;

-- Prevent newer input fields being silently ignored during a partial rollout.
create function public.save_reported_feedback(feedback jsonb)
returns jsonb language sql security invoker set search_path = '' as $$
  select public.save_experience_feedback(feedback);
$$;
revoke all on function public.save_reported_feedback(jsonb) from public, anon;
grant execute on function public.save_reported_feedback(jsonb) to authenticated;
