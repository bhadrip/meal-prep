-- Search the active household's entire recipe library, including partial tag text.
create function public.find_recipes(
  search_query text default '',
  filter_tag text default '',
  result_limit integer default 25
)
returns table (
  id uuid,
  title text,
  description text,
  servings numeric,
  active_minutes integer,
  total_minutes integer,
  tags text[],
  ingredients jsonb,
  instructions jsonb,
  source_url text,
  created_at timestamptz,
  updated_at timestamptz
)
language sql stable security invoker set search_path = '' as $$
  select r.id, r.title, r.description, r.servings, r.active_minutes,
    r.total_minutes, r.tags, r.ingredients, r.instructions, r.source_url,
    r.created_at, r.updated_at
  from public.recipes r
  where r.household_id = public.active_household_id()
    and r.archived_at is null
    and (nullif(btrim(filter_tag), '') is null or exists (
      select 1 from unnest(r.tags) as t(value)
      where lower(t.value) = lower(btrim(filter_tag))
    ))
    and (nullif(btrim(search_query), '') is null or
      strpos(lower(r.title), lower(btrim(search_query))) > 0 or
      strpos(lower(r.description), lower(btrim(search_query))) > 0 or
      exists (select 1 from unnest(r.tags) as t(value)
        where strpos(lower(t.value), lower(btrim(search_query))) > 0))
  order by r.updated_at desc, r.id
  limit least(greatest(result_limit, 1), 25);
$$;

create function public.list_recipe_tags()
returns table (tag text, recipe_count bigint)
language sql stable security invoker set search_path = '' as $$
  select lower(btrim(t.value)) as tag, count(distinct r.id) as recipe_count
  from public.recipes r
  cross join lateral unnest(r.tags) as t(value)
  where r.household_id = public.active_household_id()
    and r.archived_at is null and btrim(t.value) <> ''
  group by lower(btrim(t.value))
  order by recipe_count desc, tag;
$$;

revoke all on function public.find_recipes(text, text, integer) from public;
revoke all on function public.list_recipe_tags() from public;
grant execute on function public.find_recipes(text, text, integer) to authenticated;
grant execute on function public.list_recipe_tags() to authenticated;
