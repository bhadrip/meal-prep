create table public.household_memories (
  id uuid primary key default gen_random_uuid(),
  household_id uuid not null references public.households(id) on delete cascade,
  category text not null default 'planning' check (char_length(category) between 1 and 40),
  content text not null check (char_length(content) between 1 and 240),
  source_type text not null default 'user' check (source_type in ('user', 'onboarding', 'schedule', 'retro', 'observation')),
  source_detail text not null default '',
  status text not null default 'suggested' check (status in ('suggested', 'confirmed', 'forgotten')),
  scope text not null default 'persistent' check (scope in ('persistent', 'this_week')),
  evidence_count integer not null default 1 check (evidence_count > 0),
  active boolean not null default true,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create trigger household_memories_touch before update on public.household_memories
for each row execute function public.touch_updated_at();

alter table public.household_memories enable row level security;
create policy household_memories_all on public.household_memories for all to authenticated
  using (public.is_household_member(household_id))
  with check (public.is_household_member(household_id));

grant select, insert, update, delete on table public.household_memories to authenticated;
