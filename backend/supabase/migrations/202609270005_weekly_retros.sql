create table public.weekly_retros (
  id uuid primary key default gen_random_uuid(),
  household_id uuid not null references public.households(id) on delete cascade,
  week_start date not null,
  outcomes jsonb not null default '[]'::jsonb check (jsonb_typeof(outcomes) = 'array'),
  worked_well jsonb not null default '[]'::jsonb check (jsonb_typeof(worked_well) = 'array'),
  stressors jsonb not null default '[]'::jsonb check (jsonb_typeof(stressors) = 'array'),
  note text not null default '' check (char_length(note) <= 600),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (household_id, week_start)
);

create trigger weekly_retros_touch before update on public.weekly_retros
for each row execute function public.touch_updated_at();

alter table public.weekly_retros enable row level security;
create policy weekly_retros_all on public.weekly_retros for all to authenticated
  using (public.is_household_member(household_id))
  with check (public.is_household_member(household_id));

grant select, insert, update, delete on table public.weekly_retros to authenticated;
