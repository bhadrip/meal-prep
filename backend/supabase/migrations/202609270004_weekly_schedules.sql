create table public.weekly_schedules (
  id uuid primary key default gen_random_uuid(),
  household_id uuid not null references public.households(id) on delete cascade,
  week_start date not null,
  days jsonb not null default '[]'::jsonb check (jsonb_typeof(days) = 'array' and jsonb_array_length(days) = 7),
  is_normal_week boolean not null default true,
  remember_rhythm boolean not null default true,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (household_id, week_start)
);

create trigger weekly_schedules_touch before update on public.weekly_schedules
for each row execute function public.touch_updated_at();

alter table public.weekly_schedules enable row level security;
create policy weekly_schedules_all on public.weekly_schedules for all to authenticated
  using (public.is_household_member(household_id))
  with check (public.is_household_member(household_id));

grant select, insert, update, delete on table public.weekly_schedules to authenticated;
