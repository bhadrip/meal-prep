-- Retrieval tools read these records by household and newest week/update first.
-- Keep the indexes in a separate migration so existing installations can add
-- them after migrations 004-006 create the feature tables.
create index if not exists weekly_schedules_household_week_idx
  on public.weekly_schedules (household_id, week_start desc);

create index if not exists weekly_retros_household_week_idx
  on public.weekly_retros (household_id, week_start desc);

create index if not exists household_memories_visible_idx
  on public.household_memories (household_id, active, status, updated_at desc);
