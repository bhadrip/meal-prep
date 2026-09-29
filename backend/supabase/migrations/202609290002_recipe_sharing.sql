-- Share records contain only deliberately published recipe fields. Raw link
-- tokens are returned once to the creator; only their hashes are persisted.
create table public.share_links (
  id uuid primary key default gen_random_uuid(),
  household_id uuid not null references public.households(id) on delete cascade,
  created_by uuid not null references auth.users(id) on delete cascade,
  artifact_type text not null check (artifact_type = 'recipe'),
  source_recipe_id uuid references public.recipes(id) on delete set null,
  snapshot jsonb not null check (jsonb_typeof(snapshot) = 'object'),
  token_hash bytea not null unique,
  expires_at timestamptz,
  revoked_at timestamptz,
  created_at timestamptz not null default now()
);

create index share_links_household_created_idx on public.share_links (household_id, created_at desc);
alter table public.share_links enable row level security;
-- Deliberately no table grants or RLS policies: access is through narrow RPCs.
revoke all on table public.share_links from public, anon, authenticated;

create function public.create_recipe_share(requested_recipe_id uuid, requested_expires_at timestamptz default null)
returns jsonb
language plpgsql
security definer
set search_path = pg_catalog, extensions, public
as $$
declare
  recipe_row public.recipes%rowtype;
  raw_token text;
  new_id uuid;
begin
  if auth.uid() is null then raise exception 'authentication required'; end if;
  if requested_expires_at is not null and requested_expires_at <= now() then
    raise exception 'expiration must be in the future';
  end if;
  select r.* into recipe_row
    from public.recipes r
    where r.id = requested_recipe_id and r.archived_at is null
      and public.is_household_member(r.household_id);
  if not found then raise exception 'recipe not found'; end if;

  raw_token := encode(gen_random_bytes(32), 'hex');
  insert into public.share_links (
    household_id, created_by, artifact_type, source_recipe_id,
    snapshot, token_hash, expires_at
  ) values (
    recipe_row.household_id, auth.uid(), 'recipe', recipe_row.id,
    jsonb_build_object(
      'title', recipe_row.title,
      'description', recipe_row.description,
      'servings', recipe_row.servings,
      'activeMinutes', recipe_row.active_minutes,
      'totalMinutes', recipe_row.total_minutes,
      'tags', recipe_row.tags,
      'ingredients', recipe_row.ingredients,
      'instructions', recipe_row.instructions,
      'sourceType', recipe_row.source_type,
      'sourceUrl', recipe_row.source_url
    ),
    digest(raw_token, 'sha256'), requested_expires_at
  ) returning id into new_id;
  return jsonb_build_object('id', new_id, 'token', raw_token, 'expiresAt', requested_expires_at);
end;
$$;

create function public.list_recipe_shares()
returns jsonb
language sql
stable
security definer
set search_path = pg_catalog, extensions, public
as $$
  select coalesce(jsonb_agg(jsonb_build_object(
    'id', s.id,
    'recipeId', s.source_recipe_id,
    'title', s.snapshot->>'title',
    'createdAt', s.created_at,
    'expiresAt', s.expires_at,
    'revokedAt', s.revoked_at
  ) order by s.created_at desc), '[]'::jsonb)
  from public.share_links s
  where s.created_by = auth.uid() and public.is_household_member(s.household_id);
$$;

create function public.revoke_recipe_share(requested_share_id uuid)
returns boolean
language plpgsql
security definer
set search_path = pg_catalog, extensions, public
as $$
begin
  if auth.uid() is null then raise exception 'authentication required'; end if;
  update public.share_links s set revoked_at = coalesce(s.revoked_at, now())
    where s.id = requested_share_id and s.created_by = auth.uid()
      and public.is_household_member(s.household_id);
  return found;
end;
$$;

create function public.read_shared_recipe(raw_token text)
returns jsonb
language sql
stable
security definer
set search_path = pg_catalog, extensions, public
as $$
  select jsonb_build_object(
    'id', s.id,
    'kind', s.artifact_type,
    'recipe', s.snapshot,
    'createdAt', s.created_at
  )
  from public.share_links s
  where s.token_hash = digest(raw_token, 'sha256')
    and s.artifact_type = 'recipe'
    and s.revoked_at is null
    and (s.expires_at is null or s.expires_at > now());
$$;

create function public.copy_shared_recipe(raw_token text)
returns uuid
language plpgsql
security definer
set search_path = pg_catalog, extensions, public
as $$
declare
  shared public.share_links%rowtype;
  target_household_id uuid;
  new_recipe_id uuid;
begin
  if auth.uid() is null then raise exception 'authentication required'; end if;
  select * into shared from public.share_links s
    where s.token_hash = digest(raw_token, 'sha256')
      and s.artifact_type = 'recipe' and s.revoked_at is null
      and (s.expires_at is null or s.expires_at > now());
  if not found then raise exception 'share not found'; end if;
  select hm.household_id into target_household_id
    from public.household_members hm where hm.user_id = auth.uid()
    order by hm.joined_at limit 1;
  if target_household_id is null then raise exception 'household required'; end if;
  insert into public.recipes (
    household_id, title, description, servings, active_minutes, total_minutes,
    tags, ingredients, instructions, source_type, source_url, source_snapshot
  ) values (
    target_household_id,
    shared.snapshot->>'title',
    coalesce(shared.snapshot->>'description', ''),
    coalesce((shared.snapshot->>'servings')::numeric, 4),
    (shared.snapshot->>'activeMinutes')::integer,
    (shared.snapshot->>'totalMinutes')::integer,
    coalesce(array(select jsonb_array_elements_text(shared.snapshot->'tags')), '{}'::text[]),
    coalesce(shared.snapshot->'ingredients', '[]'::jsonb),
    coalesce(shared.snapshot->'instructions', '[]'::jsonb),
    'shared',
    shared.snapshot->>'sourceUrl',
    jsonb_build_object('shareId', shared.id, 'sharedAt', now())
  ) returning id into new_recipe_id;
  return new_recipe_id;
end;
$$;

revoke all on function public.create_recipe_share(uuid, timestamptz) from public;
revoke all on function public.list_recipe_shares() from public;
revoke all on function public.revoke_recipe_share(uuid) from public;
revoke all on function public.read_shared_recipe(text) from public;
revoke all on function public.copy_shared_recipe(text) from public;
grant execute on function public.create_recipe_share(uuid, timestamptz) to authenticated;
grant execute on function public.list_recipe_shares() to authenticated;
grant execute on function public.revoke_recipe_share(uuid) to authenticated;
grant usage on schema public to anon;
grant execute on function public.read_shared_recipe(text) to anon, authenticated;
grant execute on function public.copy_shared_recipe(text) to authenticated;
