-- One private, S3-compatible Storage bucket for compact pantry photo evidence.
insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values ('pantry-evidence', 'pantry-evidence', false, 5242880, array['image/webp'])
on conflict (id) do update set
  public = false,
  file_size_limit = excluded.file_size_limit,
  allowed_mime_types = excluded.allowed_mime_types;

create table public.pantry_photo_evidence (
  id uuid primary key default gen_random_uuid(),
  household_id uuid not null references public.households(id) on delete cascade,
  object_path text not null unique,
  source_file_id text not null,
  note text not null default '',
  observations jsonb not null default '[]'::jsonb check (jsonb_typeof(observations) = 'array'),
  image_bytes integer not null check (image_bytes > 0),
  image_width integer not null check (image_width > 0),
  image_height integer not null check (image_height > 0),
  status text not null default 'captured' check (status in ('captured', 'applied')),
  applied_item_ids uuid[] not null default '{}',
  created_at timestamptz not null default now(),
  constraint pantry_photo_path_household check (split_part(object_path, '/', 1) = household_id::text)
);

create index pantry_photo_evidence_household_created
  on public.pantry_photo_evidence (household_id, created_at desc);

alter table public.pantry_photo_evidence enable row level security;
create policy pantry_photo_evidence_household on public.pantry_photo_evidence
  for all to authenticated
  using (public.is_household_member(household_id))
  with check (public.is_household_member(household_id));
grant select, insert, update on public.pantry_photo_evidence to authenticated;

-- Storage paths begin with household UUID. Do not grant public read access.
create policy pantry_evidence_object_insert on storage.objects
  for insert to authenticated
  with check (
    bucket_id = 'pantry-evidence'
    and exists (
      select 1 from public.household_members hm
      where hm.household_id::text = (storage.foldername(name))[1]
        and hm.user_id = auth.uid()
    )
  );
create policy pantry_evidence_object_select on storage.objects
  for select to authenticated
  using (
    bucket_id = 'pantry-evidence'
    and exists (
      select 1 from public.household_members hm
      where hm.household_id::text = (storage.foldername(name))[1]
        and hm.user_id = auth.uid()
    )
  );
create policy pantry_evidence_object_delete on storage.objects
  for delete to authenticated
  using (
    bucket_id = 'pantry-evidence'
    and exists (
      select 1 from public.household_members hm
      where hm.household_id::text = (storage.foldername(name))[1]
        and hm.user_id = auth.uid()
    )
  );
