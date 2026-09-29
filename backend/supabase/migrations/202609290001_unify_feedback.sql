-- Keep feedback as the single evidence model. A weekly check-in is a workflow
-- that creates week-linked feedback entries, not a second kind of record.

create temporary table migrated_weekly_feedback (
  id uuid primary key,
  household_id uuid not null,
  weekly_schedule_id uuid,
  week_start date not null,
  feedback_type text not null,
  note text not null,
  outcome_tag text not null,
  created_by uuid not null,
  created_at timestamptz not null,
  updated_at timestamptz not null,
  occurrence_id uuid,
  recipe_id uuid,
  occurrence_title text,
  variation_snapshot jsonb not null default '{}'::jsonb,
  next_time text not null default ''
);

insert into migrated_weekly_feedback
select
  gen_random_uuid(), wr.household_id, ws.id, wr.week_start,
  'worked_well',
  left(case when jsonb_typeof(item.value) = 'string' then item.value #>> '{}' else item.value::text end, 600),
  'worked-well', h.created_by, wr.created_at, wr.updated_at,
  null::uuid, null::uuid, null::text, '{}'::jsonb, ''::text
from public.weekly_retros wr
join public.households h on h.id = wr.household_id
left join public.weekly_schedules ws
  on ws.household_id = wr.household_id and ws.week_start = wr.week_start
cross join lateral jsonb_array_elements(wr.worked_well) item
where length(trim(case when jsonb_typeof(item.value) = 'string' then item.value #>> '{}' else item.value::text end)) > 0
union all
select
  gen_random_uuid(), wr.household_id, ws.id, wr.week_start,
  'problem',
  left(case when jsonb_typeof(item.value) = 'string' then item.value #>> '{}' else item.value::text end, 600),
  'did-not-work', h.created_by, wr.created_at, wr.updated_at,
  null::uuid, null::uuid, null::text, '{}'::jsonb, ''::text
from public.weekly_retros wr
join public.households h on h.id = wr.household_id
left join public.weekly_schedules ws
  on ws.household_id = wr.household_id and ws.week_start = wr.week_start
cross join lateral jsonb_array_elements(wr.stressors) item
where length(trim(case when jsonb_typeof(item.value) = 'string' then item.value #>> '{}' else item.value::text end)) > 0
union all
select
  gen_random_uuid(), wr.household_id, ws.id, wr.week_start,
  'change_next_time',
  left(
    case
      when jsonb_typeof(item.value) = 'object' then concat_ws(
        ': ', nullif(trim(item.value->>'meal'), ''), nullif(trim(item.value->>'outcome'), '')
      )
      when jsonb_typeof(item.value) = 'string' then item.value #>> '{}'
      else item.value::text
    end,
    600
  ),
  'change-next-time', h.created_by, wr.created_at, wr.updated_at,
  case when r.id is not null then gen_random_uuid() end,
  r.id,
  left(coalesce(nullif(trim(item.value->>'meal'), ''), r.title, 'Meal'), 180),
  case when jsonb_typeof(item.value) = 'object' then item.value else '{}'::jsonb end,
  coalesce(left(case
    when jsonb_typeof(item.value->'nextTime') = 'array' then (
      select string_agg(change.value, '; ' order by change.ordinality)
      from jsonb_array_elements_text(item.value->'nextTime') with ordinality as change(value, ordinality)
    )
    when jsonb_typeof(item.value->'nextTime') = 'string' then item.value->>'nextTime'
    else ''
  end, 600), '')
from public.weekly_retros wr
join public.households h on h.id = wr.household_id
left join public.weekly_schedules ws
  on ws.household_id = wr.household_id and ws.week_start = wr.week_start
cross join lateral jsonb_array_elements(wr.outcomes) item
left join public.recipes r
  on r.household_id = wr.household_id and r.id::text = item.value->>'recipeId'
where length(trim(
  case
    when jsonb_typeof(item.value) = 'object' then concat_ws(
      ': ', nullif(trim(item.value->>'meal'), ''), nullif(trim(item.value->>'outcome'), '')
    )
    when jsonb_typeof(item.value) = 'string' then item.value #>> '{}'
    else item.value::text
  end
)) > 0
union all
select
  gen_random_uuid(), wr.household_id, ws.id, wr.week_start,
  'change_next_time', left(wr.note, 600), 'change-next-time',
  h.created_by, wr.created_at, wr.updated_at,
  null::uuid, null::uuid, null::text, '{}'::jsonb, ''::text
from public.weekly_retros wr
join public.households h on h.id = wr.household_id
left join public.weekly_schedules ws
  on ws.household_id = wr.household_id and ws.week_start = wr.week_start
where length(trim(wr.note)) > 0;

-- Recipe-linked review outcomes need an occurrence so recipe feedback queries
-- can find them. Preserve the source JSON, including preparation details.
insert into public.meal_occurrences (
  id, household_id, weekly_schedule_id, week_start, title, recipe_id,
  variation_snapshot, created_at, updated_at
)
select
  occurrence_id, household_id, weekly_schedule_id, week_start,
  occurrence_title, recipe_id, variation_snapshot, created_at, updated_at
from migrated_weekly_feedback
where occurrence_id is not null;

insert into public.feedback_entries (
  id, household_id, occurrence_id, weekly_schedule_id, week_start,
  feedback_type, note, next_time, created_by, created_at, updated_at
)
select
  id, household_id, occurrence_id, weekly_schedule_id, week_start,
  feedback_type, note, next_time, created_by, created_at, updated_at
from migrated_weekly_feedback;

insert into public.feedback_tags (household_id, slug, label, facet)
select distinct
  household_id,
  outcome_tag,
  case outcome_tag
    when 'worked-well' then 'Worked Well'
    when 'did-not-work' then 'Did Not Work'
    else 'Change Next Time'
  end,
  'outcome'
from migrated_weekly_feedback
on conflict (household_id, slug) do update set
  label = excluded.label,
  facet = excluded.facet,
  updated_at = now();

insert into public.feedback_tags (household_id, slug, label, facet)
select distinct household_id, 'weekly-check-in', 'Weekly Check-In', 'other'
from migrated_weekly_feedback
on conflict (household_id, slug) do update set
  label = excluded.label,
  facet = excluded.facet,
  updated_at = now();

insert into public.feedback_entry_tags (feedback_id, tag_id)
select migrated.id, tags.id
from migrated_weekly_feedback migrated
join public.feedback_tags tags
  on tags.household_id = migrated.household_id
  and tags.slug in (migrated.outcome_tag, 'weekly-check-in')
on conflict do nothing;

alter table public.feedback_entries
  drop constraint feedback_entries_feedback_type_check;

update public.feedback_entries
set feedback_type = 'preference_signal'
where feedback_type = 'preference';

alter table public.feedback_entries
  add constraint feedback_entries_feedback_type_check
  check (feedback_type in ('worked_well', 'change_next_time', 'problem', 'preference_signal'));

insert into public.feedback_tags (household_id, slug, label, facet)
select household_id, 'preference-signal', 'Preference Signal', 'outcome'
from public.feedback_tags
where slug = 'preference'
on conflict (household_id, slug) do update set
  label = excluded.label,
  facet = excluded.facet,
  updated_at = now();

insert into public.feedback_entry_tags (feedback_id, tag_id)
select old_links.feedback_id, replacement.id
from public.feedback_entry_tags old_links
join public.feedback_tags old_tag
  on old_tag.id = old_links.tag_id and old_tag.slug = 'preference'
join public.feedback_tags replacement
  on replacement.household_id = old_tag.household_id
  and replacement.slug = 'preference-signal'
on conflict do nothing;

delete from public.feedback_entry_tags
where tag_id in (select id from public.feedback_tags where slug = 'preference');

delete from public.feedback_tags where slug = 'preference';

alter table public.household_memories
  drop constraint household_memories_source_type_check;

update public.household_memories
set source_type = 'feedback'
where source_type = 'retro';

alter table public.household_memories
  add constraint household_memories_source_type_check
  check (source_type in ('user', 'onboarding', 'schedule', 'feedback', 'observation'));

drop table migrated_weekly_feedback;
-- Retain the original review rows until the backfill has been checked in production.
comment on table public.weekly_retros is
  'Legacy weekly reviews retained for verification after feedback migration.';
