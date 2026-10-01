-- Tags remain canonical on recipes; cuisines and recipe-to-recipe edges are explicit.
alter table public.recipes add column cuisines text[] not null default '{}'
  check (cardinality(cuisines) <= 12);
create unique index recipes_household_identity on public.recipes(household_id, id);

create table public.recipe_relationships (
  id uuid primary key default gen_random_uuid(),
  household_id uuid not null references public.households(id) on delete cascade,
  source_recipe_id uuid not null,
  target_recipe_id uuid not null,
  relationship_type text not null check (relationship_type in ('variant_of', 'pairs_with')),
  check (source_recipe_id <> target_recipe_id),
  check (relationship_type <> 'pairs_with' or source_recipe_id < target_recipe_id),
  foreign key (household_id, source_recipe_id) references public.recipes(household_id, id) on delete cascade,
  foreign key (household_id, target_recipe_id) references public.recipes(household_id, id) on delete cascade,
  unique (household_id, source_recipe_id, relationship_type, target_recipe_id)
);
alter table public.recipe_relationships enable row level security;
create policy recipe_relationships_read on public.recipe_relationships for select to authenticated
  using (public.is_household_member(household_id));
revoke insert, update, delete on public.recipe_relationships from authenticated;
grant select on public.recipe_relationships to authenticated;

create function public.get_recipe_graph_data()
returns jsonb language sql stable security invoker set search_path = '' as $$
  select jsonb_build_object(
    'recipes', coalesce((select jsonb_agg(jsonb_build_object('id', r.id, 'title', r.title,
      'tags', r.tags, 'cuisines', r.cuisines) order by lower(r.title), r.id)
      from public.recipes r where r.household_id = public.active_household_id() and r.archived_at is null), '[]'::jsonb),
    'relationships', coalesce((select jsonb_agg(jsonb_build_object('id', e.id,
      'sourceRecipeId', e.source_recipe_id, 'targetRecipeId', e.target_recipe_id,
      'type', e.relationship_type, 'label', null) order by e.id)
      from public.recipe_relationships e
      join public.recipes a on a.id = e.source_recipe_id and a.archived_at is null
      join public.recipes b on b.id = e.target_recipe_id and b.archived_at is null
      where e.household_id = public.active_household_id()), '[]'::jsonb));
$$;

create function public.delete_recipe_relationship(requested_id text)
returns boolean language plpgsql security definer set search_path = '' as $$
declare
  h uuid := public.active_household_id();
  kind text := split_part(requested_id, ':', 1);
  source_id uuid;
  category text;
  changed integer;
begin
  perform 1 from public.households where id = h and public.is_household_member(h) for update;
  if not found then raise exception 'Household required'; end if;
  if kind in ('tag', 'cuisine') then
    source_id := split_part(requested_id, ':', 2)::uuid;
    category := substring(requested_id from length(kind) + 39);
    if kind = 'tag' then
      update public.recipes set tags = array_remove(tags, category)
      where id = source_id and household_id = h and archived_at is null and category = any(tags);
    else
      update public.recipes set cuisines = array_remove(cuisines, category)
      where id = source_id and household_id = h and archived_at is null and category = any(cuisines);
    end if;
  else
    delete from public.recipe_relationships where id = requested_id::uuid and household_id = h;
  end if;
  get diagnostics changed = row_count;
  if changed = 0 then raise exception 'Relationship was not found'; end if;
  return true;
end;
$$;

create function public.save_recipe_relationship(requested_relationship jsonb)
returns jsonb language plpgsql security definer set search_path = '' as $$
declare
  h uuid := public.active_household_id();
  source_id uuid := (requested_relationship->>'sourceRecipeId')::uuid;
  target_id uuid := (requested_relationship->>'targetRecipeId')::uuid;
  kind text := requested_relationship->>'type';
  category text := lower(regexp_replace(btrim(requested_relationship->>'label'), '\s+', ' ', 'g'));
  old_id text := requested_relationship->>'id';
  new_id text;
  swap_id uuid;
  values_array text[];
begin
  -- Serialize relationship edits per household so two concurrent variant edits cannot form a cycle.
  perform 1 from public.households where id = h and public.is_household_member(h) for update;
  if not found then raise exception 'Household required'; end if;
  if kind is null or kind not in ('tag', 'cuisine', 'variant_of', 'pairs_with') then
    raise exception 'Choose a valid relationship type';
  end if;
  perform 1 from public.recipes where id = source_id and household_id = h and archived_at is null for update;
  if not found then raise exception 'Source recipe was not found'; end if;
  if kind in ('variant_of', 'pairs_with') then
    if source_id = target_id then raise exception 'Choose two different recipes'; end if;
    perform 1 from public.recipes where id = target_id and household_id = h and archived_at is null;
    if not found then raise exception 'Target recipe was not found'; end if;
    if kind = 'pairs_with' and source_id > target_id then
      swap_id := source_id; source_id := target_id; target_id := swap_id;
    end if;
  elsif jsonb_typeof(requested_relationship->'label') is distinct from 'string'
    or category is null or char_length(category) not between 1 and 48 then
    raise exception 'Category must be text of 1–48 characters';
  end if;
  if old_id is not null then perform public.delete_recipe_relationship(old_id); end if;
  if kind in ('tag', 'cuisine') then
    select case when kind = 'tag' then tags else cuisines end into values_array from public.recipes where id = source_id;
    if category = any(values_array) then raise exception 'This relationship already exists'; end if;
    if cardinality(values_array) >= 12 then raise exception 'A recipe can have at most 12 tags or cuisines'; end if;
    if kind = 'tag' then update public.recipes set tags = array_append(tags, category) where id = source_id;
    else update public.recipes set cuisines = array_append(cuisines, category) where id = source_id; end if;
    new_id := kind || ':' || source_id::text || ':' || category;
    target_id := null;
  else
    category := null;
    if kind = 'variant_of' and exists (
      with recursive ancestors(id) as (
        select target_id union
        select e.target_recipe_id from public.recipe_relationships e join ancestors a on a.id = e.source_recipe_id
        where e.household_id = h and e.relationship_type = 'variant_of'
      ) select 1 from ancestors where id = source_id
    ) then raise exception 'This would create a loop in the variations'; end if;
    if exists (select 1 from public.recipe_relationships where household_id = h and source_recipe_id = source_id
      and target_recipe_id = target_id and relationship_type = kind) then raise exception 'This relationship already exists'; end if;
    insert into public.recipe_relationships(id, household_id, source_recipe_id, target_recipe_id, relationship_type)
    values (case when old_id is not null and position(':' in old_id) = 0 then old_id::uuid else gen_random_uuid() end,
      h, source_id, target_id, kind) returning id::text into new_id;
  end if;
  return jsonb_build_object('id', new_id, 'sourceRecipeId', source_id, 'targetRecipeId', target_id, 'type', kind, 'label', category);
end;
$$;

revoke all on function public.get_recipe_graph_data() from public;
revoke all on function public.save_recipe_relationship(jsonb) from public;
revoke all on function public.delete_recipe_relationship(text) from public;
grant execute on function public.get_recipe_graph_data() to authenticated;
grant execute on function public.save_recipe_relationship(jsonb) to authenticated;
grant execute on function public.delete_recipe_relationship(text) to authenticated;
