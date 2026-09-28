---
name: meal-prep-planning
description: Coordinate the household food week across breakfasts, lunches, dinners, prep, pantry inventory, and store-prioritized shopping lists with the Meal Prep MCP tools.
---

# Meal prep planning

Use this workflow when the user asks to plan any part of the household food
week, choose recipes, prepare food ahead, use pantry food, update household
food preferences, or create a shopping list.

## Required sequence

1. Call `get_planning_context` before drafting or revising a weekly plan,
   passing the requested `week_start` when known. It returns household
   preferences, the relevant weekly schedule and retrospective, and active
   household memories in one read. If `household.onboardingComplete` is false,
   call `render_onboarding` so the user can complete the MCP-served household
   setup. The form collects household size, dietary restrictions (including an
   explicit "none"), preferred stores in order, maximum weeknight cooking time,
   whether dinner should make lunch leftovers, and which planning areas they
   want coordinated: breakfasts, lunches, snacks, dinners, weekend prep, pantry
   inventory, or shopping. Do not present null or empty onboarding fields as an
   existing starter profile. The UI saves the answers together with
   `update_household_preferences` using `complete_onboarding: true`, storing the
   chosen areas in `planning_preferences.focusAreas`. Treat recorded dietary
   restrictions as hard constraints and planning preferences as defaults the
   user may override.
   Use the individual retrieval tools only when the user asks to inspect or
   refresh one record independently.
2. Call `get_pantry` and `search_recipes` when existing food or saved recipes
   affect the request. Do not fabricate pantry quantities, freshness, prices,
   inventory, or recipe provenance.
3. Create and reason over the meal plan in the model. Cover the requested
   planning areas without assuming the request is dinner-only. Give every saved
   meal-plan entry an explicit `slot`, such as `breakfast`, `lunch`, `snack`,
   `dinner`, or `prep`. Prefer weeknight meals within the saved time limit,
   deliberate leftovers when requested, and pantry items with earlier use-by
   ranges. Keep recurring breakfasts, packed lunches, and prep intentionally
   simple when the household has not asked for daily variety.
4. Show the proposed plan before calling `save_meal_plan`. If the user asked to
   create and save a plan in the same message, their request is confirmation.
5. Build shopping demand across every planned slot and prep task, subtracting
   only pantry items that are present with sufficient quantity confidence.
6. Order stores by `storePriority`. Search Costco first when it is priority 1,
   then use Safeway for unavailable items. Store availability, prices, carts,
   and orders belong to the commerce plugin, not Meal Prep.
7. Call `save_shopping_list` only for the resulting durable list. Never state
   or imply that saving a list placed an order.
8. Use `render_onboarding` for incomplete household setup. Use
   `render_household_snapshot` when the user asks what Meal Prep knows or wants
   to inspect household rules, pantry, schedule, or memory without a wall of
   prose. Use `render_meal_plan` or `render_shopping_list` only after the
   corresponding data tool has returned the final data. Data tools must remain
   usable without UI.

## Changes and confirmation

- Explicit preference changes may be saved with
  `update_household_preferences`. Never turn a one-time situation or inferred
  behavior into a durable preference without asking.
- Retrospective observations are evidence, not permanent preferences. Save them
  as suggested memories and use `review_household_memory` only after the user
  confirms, corrects, or asks to forget one.
- Use confirmed household memories as planning defaults. Suggested memories may
  influence a question or option but must not be presented as settled facts.
- A null weekly schedule or retrospective means no saved record exists. Ask for
  relevant constraints when needed; do not invent a schedule or prior outcome.
- Recipe archival and external purchases require explicit confirmation.
- `mark_item_purchased` records shopping progress; it does not buy anything.
- If a proposed recipe conflicts with a hard restriction, reject it and offer
  a safe alternative instead of weakening the restriction.

## Result quality

Return a concise plan organized by day and meal slot, with a separate weekend
prep section when relevant. Include names, servings, effort, and a short reason
when that reason helps the user trust the choice. Group shopping items by store
and make substitutions visible. Keep medical and food-safety claims out of the
workflow unless the user provides a verified source.
