-- Archive is personal and reversible; existing recipient/access RLS applies.
alter table public.notifications add column archived_at timestamptz;
grant update (archived_at) on public.notifications to authenticated;
