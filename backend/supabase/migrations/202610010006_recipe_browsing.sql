-- Explicit browsing categories; existing tags and cuisines retain their meaning.
alter table public.recipes
  add column eating_goals text[] not null default '{}' check (cardinality(eating_goals) <= 12),
  add column meal_types text[] not null default '{}' check (cardinality(meal_types) <= 12),
  add column diets text[] not null default '{}' check (cardinality(diets) <= 12);

create or replace function public.get_recipe_graph_data()
returns jsonb language sql stable security invoker set search_path = '' as $$
  select jsonb_build_object(
    'recipes', coalesce((select jsonb_agg(jsonb_build_object('id', r.id, 'title', r.title,
      'tags', r.tags, 'cuisines', r.cuisines, 'eating_goals', r.eating_goals,
      'meal_types', r.meal_types, 'diets', r.diets, 'description', r.description,
      'total_minutes', r.total_minutes, 'active_minutes', r.active_minutes, 'servings', r.servings, 'ingredients', r.ingredients) order by lower(r.title), r.id)
      from public.recipes r where r.household_id = public.active_household_id() and r.archived_at is null), '[]'::jsonb),
    'relationships', coalesce((select jsonb_agg(jsonb_build_object('id', e.id,
      'sourceRecipeId', e.source_recipe_id, 'targetRecipeId', e.target_recipe_id,
      'type', e.relationship_type, 'label', null) order by e.id)
      from public.recipe_relationships e
      join public.recipes a on a.id = e.source_recipe_id and a.archived_at is null
      join public.recipes b on b.id = e.target_recipe_id and b.archived_at is null
      where e.household_id = public.active_household_id()), '[]'::jsonb));
$$;

create or replace function public.delete_recipe_relationship(requested_id text)
returns boolean language plpgsql security definer set search_path = '' as $$
declare
  h uuid := public.active_household_id();
  kind text := split_part(requested_id, ':', 1);
  source_id uuid;
  category text;
  changed integer;
  category_field text;
begin
  perform 1 from public.households where id = h and public.is_household_member(h) for update;
  if not found then raise exception 'Household required'; end if;
  if kind in ('tag', 'cuisine', 'goal', 'meal', 'diet') then
    source_id := split_part(requested_id, ':', 2)::uuid;
    category := substring(requested_id from length(kind) + 39);
    category_field := case kind when 'tag' then 'tags' when 'cuisine' then 'cuisines'
      when 'goal' then 'eating_goals' when 'meal' then 'meal_types' when 'diet' then 'diets' end;
    execute format('update public.recipes set %1$I = array_remove(%1$I, $1)
      where id = $2 and household_id = $3 and archived_at is null and $1 = any(%1$I)', category_field)
      using category, source_id, h;
  else
    delete from public.recipe_relationships where id = requested_id::uuid and household_id = h;
  end if;
  get diagnostics changed = row_count;
  if changed = 0 then raise exception 'Relationship was not found'; end if;
  return true;
end;
$$;

create or replace function public.save_recipe_relationship(requested_relationship jsonb)
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
  category_field text;
begin
  -- Serialize relationship edits per household so two concurrent variant edits cannot form a cycle.
  perform 1 from public.households where id = h and public.is_household_member(h) for update;
  if not found then raise exception 'Household required'; end if;
  if kind is null or kind not in ('tag', 'cuisine', 'goal', 'meal', 'diet', 'variant_of', 'pairs_with') then
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
  if kind in ('tag', 'cuisine', 'goal', 'meal', 'diet') then
    category_field := case kind when 'tag' then 'tags' when 'cuisine' then 'cuisines'
      when 'goal' then 'eating_goals' when 'meal' then 'meal_types' when 'diet' then 'diets' end;
    execute format('select %I from public.recipes where id = $1 and household_id = $2', category_field)
      into values_array using source_id, h;
    if category = any(values_array) then raise exception 'This relationship already exists'; end if;
    if cardinality(values_array) >= 12 then raise exception 'A recipe can have at most 12 categories of each kind'; end if;
    execute format('update public.recipes set %1$I = array_append(%1$I, $1) where id = $2 and household_id = $3', category_field)
      using category, source_id, h;
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
