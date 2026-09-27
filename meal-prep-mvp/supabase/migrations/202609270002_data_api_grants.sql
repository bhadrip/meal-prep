grant usage on schema public to authenticated;

grant select, update on table public.households to authenticated;
grant select on table public.household_members to authenticated;
grant select, insert, update, delete on table public.household_preferences to authenticated;
grant select, insert, update, delete on table public.recipes to authenticated;
grant select, insert, update, delete on table public.pantry_items to authenticated;
grant select, insert, update, delete on table public.meal_plans to authenticated;
grant select, insert, update, delete on table public.meal_plan_entries to authenticated;
grant select, insert, update, delete on table public.shopping_lists to authenticated;
grant select, insert, update, delete on table public.shopping_items to authenticated;
grant select, insert on table public.decision_records to authenticated;
