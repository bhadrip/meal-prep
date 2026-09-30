create or replace function public.add_shopping_item(item jsonb, requested_list_id text default null)
returns jsonb
language plpgsql
security invoker
as $$
declare
  target_household_id uuid;
  target_list_id uuid;
  next_position integer;
begin
  select household_id into target_household_id
  from public.household_members
  where user_id = auth.uid()
  order by joined_at
  limit 1;
  if target_household_id is null then raise exception 'household required'; end if;
  if nullif(trim(item->>'name'), '') is null then raise exception 'item name required'; end if;
  if nullif(item->>'quantity', '')::numeric <= 0 then raise exception 'item quantity must be positive'; end if;

  if requested_list_id is not null then
    select id into target_list_id
    from public.shopping_lists
    where id = requested_list_id::uuid and household_id = target_household_id
    for update;
    if target_list_id is null then raise exception 'shopping list not found'; end if;
  else
    select id into target_list_id
    from public.shopping_lists
    where household_id = target_household_id and status in ('draft', 'active')
    order by updated_at desc
    limit 1
    for update;
    if target_list_id is null then
      insert into public.shopping_lists(household_id, name, created_by)
      values (target_household_id, 'Shopping list', auth.uid())
      returning id into target_list_id;
    end if;
  end if;

  select coalesce(max(position) + 1, 0) into next_position
  from public.shopping_items where shopping_list_id = target_list_id;

  insert into public.shopping_items(shopping_list_id, name, quantity, unit, store_name, position)
  values (
    target_list_id,
    trim(item->>'name'),
    nullif(item->>'quantity', '')::numeric,
    nullif(trim(item->>'unit'), ''),
    nullif(trim(item->>'store'), ''),
    next_position
  );
  update public.shopping_lists set updated_at = now() where id = target_list_id;
  return public.get_shopping_list(target_list_id::text);
end;
$$;

revoke all on function public.add_shopping_item(jsonb, text) from public;
grant execute on function public.add_shopping_item(jsonb, text) to authenticated;
