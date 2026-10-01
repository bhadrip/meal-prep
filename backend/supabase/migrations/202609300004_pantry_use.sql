-- Track a reference amount for a simple remaining-quantity bar.
alter table public.pantry_items
  add column reference_quantity numeric(12,3)
  check (reference_quantity is null or reference_quantity > 0);

update public.pantry_items
set reference_quantity = quantity
where quantity > 0;

create function public.set_pantry_reference_quantity()
returns trigger language plpgsql as $$
begin
  if new.quantity is not null and new.quantity > 0
     and (new.reference_quantity is null or new.quantity > new.reference_quantity) then
    new.reference_quantity := new.quantity;
  end if;
  return new;
end;
$$;

create trigger pantry_reference_quantity
before insert or update of quantity on public.pantry_items
for each row execute function public.set_pantry_reference_quantity();

create table public.pantry_uses (
  id uuid primary key default gen_random_uuid(),
  household_id uuid not null references public.households(id) on delete cascade,
  pantry_item_id uuid not null references public.pantry_items(id) on delete cascade,
  quantity_used numeric(12,3) not null check (quantity_used > 0),
  quantity_before numeric(12,3) not null,
  quantity_remaining numeric(12,3) not null check (quantity_remaining >= 0),
  unit text,
  recipe_id uuid references public.recipes(id) on delete set null,
  meal_title text check (meal_title is null or char_length(meal_title) between 1 and 180),
  used_at timestamptz not null default now(),
  created_by uuid not null default auth.uid() references auth.users(id) on delete restrict
);

create index pantry_uses_item_idx on public.pantry_uses (pantry_item_id, used_at desc);
alter table public.pantry_uses enable row level security;
create policy pantry_uses_select on public.pantry_uses for select to authenticated
  using (public.is_household_member(household_id));
grant select on public.pantry_uses to authenticated;

create function public.record_pantry_use(
  requested_item_id uuid,
  amount_used numeric,
  requested_recipe_id uuid default null,
  requested_meal_title text default null
)
returns jsonb language plpgsql security definer set search_path = '' as $$
declare
  target_household_id uuid := public.active_household_id();
  item_row public.pantry_items%rowtype;
  recipe_title text;
  use_row public.pantry_uses%rowtype;
  clean_meal_title text := nullif(trim(requested_meal_title), '');
begin
  if target_household_id is null then raise exception 'Household required'; end if;
  if amount_used is null or amount_used <= 0 or amount_used <> round(amount_used, 3) then
    raise exception 'Amount used must be positive with at most 3 decimal places';
  end if;
  if clean_meal_title is not null and char_length(clean_meal_title) > 180 then
    raise exception 'Meal title is too long';
  end if;

  select * into item_row from public.pantry_items
  where id = requested_item_id and household_id = target_household_id for update;
  if not found then raise exception 'Pantry item was not found'; end if;
  if item_row.quantity is null then raise exception 'Set a remaining quantity before recording use'; end if;
  if amount_used > item_row.quantity then raise exception 'Amount used exceeds the remaining quantity'; end if;

  if requested_recipe_id is not null then
    select title into recipe_title from public.recipes
    where id = requested_recipe_id and household_id = target_household_id and archived_at is null;
    if not found then raise exception 'Recipe was not found'; end if;
  end if;

  update public.pantry_items set quantity = quantity - amount_used
  where id = requested_item_id returning * into item_row;

  insert into public.pantry_uses (
    household_id, pantry_item_id, quantity_used, quantity_before,
    quantity_remaining, unit, recipe_id, meal_title
  ) values (
    target_household_id, requested_item_id, amount_used,
    item_row.quantity + amount_used, item_row.quantity, item_row.unit,
    requested_recipe_id, clean_meal_title
  ) returning * into use_row;

  return jsonb_build_object(
    'id', use_row.id, 'itemId', item_row.id, 'name', item_row.name,
    'quantityUsed', use_row.quantity_used, 'quantityBefore', use_row.quantity_before,
    'quantityRemaining', use_row.quantity_remaining, 'unit', use_row.unit,
    'recipeId', use_row.recipe_id, 'recipeTitle', recipe_title,
    'mealTitle', use_row.meal_title, 'item', to_jsonb(item_row)
  );
end;
$$;

revoke all on function public.record_pantry_use(uuid, numeric, uuid, text) from public;
grant execute on function public.record_pantry_use(uuid, numeric, uuid, text) to authenticated;
