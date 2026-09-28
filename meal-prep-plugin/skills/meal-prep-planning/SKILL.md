---
name: meal-prep-planning
description: Plan household meals, use pantry food, save meal plans, and build store-prioritized shopping lists with the Meal Prep MCP tools.
---

# Meal prep planning

Use this workflow when the user asks to plan meals, choose recipes, use pantry
food, update household food preferences, or create a shopping list.

## Required sequence

1. Call `get_household_context` before planning. If `onboardingComplete` is
   false, stop planning and ask the user for household size, dietary
   restrictions (including an explicit "none"), preferred stores in order,
   maximum weeknight cooking time, and whether dinner should make lunch
   leftovers. Do not present null or empty onboarding fields as an existing
   starter profile. Save the answers together with `update_household_preferences`
   using `complete_onboarding: true`. Treat recorded dietary restrictions as
   hard constraints and planning preferences as defaults the user may override.
   Also load `get_weekly_schedule`, `get_latest_retro`, and
   `get_household_memory` before drafting when those tools are available.
2. Call `get_pantry` and `search_recipes` when existing food or saved recipes
   affect the request. Do not fabricate pantry quantities, freshness, prices,
   inventory, or recipe provenance.
3. Create and reason over the meal plan in the model. Prefer weeknight meals
   within the saved time limit, deliberate leftovers when requested, and pantry
   items with earlier use-by ranges.
4. Show the proposed plan before calling `save_meal_plan`. If the user asked to
   create and save a plan in the same message, their request is confirmation.
5. Build shopping demand from the approved plan, subtracting only pantry items
   that are present with sufficient quantity confidence.
6. Order stores by `storePriority`. Search Costco first when it is priority 1,
   then use Safeway for unavailable items. Store availability, prices, carts,
   and orders belong to the commerce plugin, not Meal Prep.
7. Call `save_shopping_list` only for the resulting durable list. Never state
   or imply that saving a list placed an order.
8. Use `render_household_snapshot` when the user asks what Meal Prep knows or
   wants to inspect household rules, pantry, schedule, or memory without a wall
   of prose. Use `render_meal_plan` or `render_shopping_list` only after the
   corresponding data tool has returned the final data. Data tools must remain
   usable without UI.

## Changes and confirmation

- Explicit preference changes may be saved with
  `update_household_preferences`. Never turn a one-time situation or inferred
  behavior into a durable preference without asking.
- Retrospective observations are evidence, not permanent preferences. Save them
  as suggested memories and use `review_household_memory` only after the user
  confirms, corrects, or asks to forget one.
- Recipe archival and external purchases require explicit confirmation.
- `mark_item_purchased` records shopping progress; it does not buy anything.
- If a proposed recipe conflicts with a hard restriction, reject it and offer
  a safe alternative instead of weakening the restriction.

## Result quality

Return a concise plan with meal names, dates, servings, effort, and a short
reason when that reason helps the user trust the choice. Group shopping items by
store and make substitutions visible. Keep medical and food-safety claims out
of the workflow unless the user provides a verified source.
