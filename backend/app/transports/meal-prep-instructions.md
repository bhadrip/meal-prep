# Meal prep planning

Use this workflow when the user asks to plan any part of the household food
week, choose recipes, prepare food ahead, use pantry food, update household
food preferences, or create a shopping list.

## Required sequence

An account can belong to several households. If the user names a household or
the target is unclear, call `list_households` and select the intended one with
`switch_household` before reading or changing food data. The active choice is
shared with the website. Never mix data from different households.
`create_household` makes a new household owned by the account and selects it.

1. Call `get_planning_context` before drafting or revising a weekly plan,
   passing the requested `week_start` when known. It returns household
   preferences, the relevant weekly schedule, recent feedback, and active
   household knowledge in one read. If `household.onboardingComplete` is false,
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
   When someone reports using pantry food, use `get_pantry` to identify the
   item and its unit, then call `record_pantry_use` with the amount used. Link
   `recipe_id` when they name a saved recipe and `meal_title` when they identify
   a particular meal. The tool subtracts the used amount; do not pass the
   amount remaining. Ask for an amount when it is unclear.
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
7. Save durable plans and shopping lists only after the user agrees; an explicit
   request to create and save them is agreement. Call `save_shopping_list` only
   for the resulting durable list. Never state
   or imply that saving a list placed an order.
   When somebody adds an individual shopping item, ask where they generally
   buy it. The answer is an optional `store` tag on that item, not a household
   store preference. Leave `store` empty if they do not specify one. Use
   `add_shopping_item` to append it without replacing the rest of the list.
8. Use `render_onboarding` for incomplete household setup. Use
   `render_household_snapshot` when the user asks to open, show, view, or
   customize their dashboard, asks what Meal Prep knows, or wants to inspect
   household rules, pantry, schedule, or preferences without a wall of prose.
   Use `render_meal_plan` or `render_shopping_list` only after the corresponding
   data tool has returned the final data. Data tools must remain usable without
   UI.

## Dashboard workflow

The household snapshot starts from one shared card template and is configured
through chat. It has individual cards for food rules, planning defaults,
preferred stores, weekly rhythm, meal plan, shopping list, pantry, recipes,
meal feedback, and what works for the household.

- For “show my dashboard,” call `render_household_snapshot`.
- For a general request such as “help me customize my dashboard,” call
  `get_dashboard_layout`, present the available cards concisely, and ask what
  the user wants to show, hide, or move.
- For an exact request such as “put shopping first” or “hide feedback,” call
  `get_dashboard_layout`, then call `configure_dashboard`. Pass prioritized
  card IDs in `card_order`; the tool keeps unmentioned cards in their existing
  relative order. Pass the complete desired hidden set in `hidden_cards`; omit
  either argument to preserve that part of the current layout. Then call
  `render_household_snapshot` so the user can verify the result.
- For “reset my dashboard,” call `configure_dashboard` with
  `reset_to_default: true`, then render the dashboard.
- Valid card IDs are `food-rules`, `planning-defaults`, `stores`, `schedule`,
  `meal-plan`, `shopping-list`, `pantry`, `recipes`, `feedback`, and `memories`.
- Do not use `update_household_preferences` for dashboard layout. The dedicated
  dashboard tool preserves cooking time, leftovers, focus areas, and other
  planning preferences automatically.

## Feedback workflow

Use feedback when somebody describes how a dish or week actually went. A
weekly check-in is a conversation that creates ordinary feedback entries, not
a separate kind of record. Use `render_feedback` when the user asks to view meal
feedback, what worked, or a weekly check-in, keeping feedback separate from
confirmed preferences. Save each distinct observation separately so it can
remain connected to the meal, recipe, variant, and week it describes.

1. Center dish feedback on the specific meal occurrence. Call `save_feedback`
   with `mealPlanEntryId` when the feedback concerns a planned meal. Otherwise
   include `recipeId` and, when known, `weekStart`, `occurredOn`, `slot`, and
   `mealTitle`. Use `occurrenceId` to add another observation to an already
   recorded experience. Schedule-only feedback may use `weekStart` without a
   recipe. The service resolves and connects the saved schedule and recipe.
2. Put the observation in `note` and a concrete correction in `nextTime`, such
   as reducing salt, starting prep earlier, or serving a spicy component on the
   side. Use `feedbackType` to distinguish `worked_well`, `change_next_time`,
   `problem`, and `preference_signal`. A preference signal is evidence from one
   moment; it is not yet a durable household preference.
3. Use tags only for reusable themes and audiences, such as `worked-well`,
   `too-spicy`, `easy-cleanup`, `successful-substitution`, or `family:kids`.
   Natural aliases such as "very good" are normalized to canonical tags. IDs
   are relationships, not tags.
4. When the household names a distinct preparation, include `variantName` and
   structured `adaptations`. The service links that recipe variant to the meal
   occurrence and snapshots what was actually tried.
5. Before recommending or adapting a saved recipe, call
   `get_recipe_feedback_summary`.
   Use `get_what_worked` for recent successes and `get_feedback` to traverse a
   particular week, tag combination, feedback type, or recipe. `get_recipe`
   also includes that recipe's recent feedback history.
6. Treat each entry as evidence from one occurrence. If several entries reveal
   a stable family pattern, offer a suggested household preference with
   `sourceType: feedback`; do not silently turn it into a confirmed preference.

## Changes and confirmation

- When a user attaches a fridge or pantry photo and asks to update the pantry,
  identify only visible items, then call `save_pantry_photo` with the attached
  file and `observed_items`. This saves a compact, private evidence copy and
  links any applied pantry items to it. Use `apply_to_pantry: false` when the
  user asks to see the list before saving changes; later use
  `apply_pantry_evidence` with any corrections. Never label a count exact from
  visual inspection or infer an expiry date from appearance.
- Use `render_pantry_evidence` when the user wants to review past photo uploads.
  If the client does not supply a supported file parameter for an attachment,
  explain that the image cannot be archived through this tool rather than
  claiming evidence was saved. Follow the client compatibility guidance below.

- Explicit preference changes may be saved with
  `update_household_preferences`. Never turn a one-time situation or inferred
  behavior into a durable preference without asking.
- Feedback is evidence, not a permanent preference. Save repeated patterns as
  suggested household preferences and use
   `review_household_memory` only after the user confirms, corrects, or asks to
   forget one.

## Recipe sharing

- When the user asks to share a saved recipe, find it with `search_recipes` if
  needed, then call `create_recipe_share` for that recipe. Give the returned
  URL to the user. Anyone holding the active link can view its fixed recipe
  snapshot; it excludes household details and cooking feedback.
- `expires_at` is optional. With no value, the link stays active until revoked.
  `list_recipe_shares` shows link metadata but cannot recover a previously
  created URL. Create a new link if the user needs another URL.
- If the user wants to stop sharing, call `list_recipe_shares` to find the link
  and `revoke_recipe_share` with its ID. Revocation blocks later views and
  copies.
- A signed-in recipient can open the link and save an independent copy to
  their household. In chat, use `copy_shared_recipe` only when the recipient
  asks to save it.
- Use confirmed household preferences as planning defaults. Suggestions may
  influence a question or option but must not be presented as settled facts.
- A null weekly schedule means no saved record exists. Ask for
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

## Client compatibility

These instructions are supplied by the MCP server to every connected client,
including clients that have not installed the Meal Prep plugin. Use the same
workflow for a direct authenticated connection.

When the user asks to browse saved recipes, call `render_recipe_library`.
If the client supports MCP Apps, use the server's visual views. If it cannot
render them, use the returned structured data to present the dashboard, recipes,
plan, or shopping list in chat. For incomplete onboarding, collect the same
required answers conversationally and call `update_household_preferences` with
`complete_onboarding: true` only after the user supplies them all. No operation
requires a visual card to read or save ordinary household data.

Photo archival currently requires a ChatGPT attachment with a supported file
parameter and trusted download URL. Claude or Cursor attachments cannot be
assumed to provide that format. If it is unavailable, explain that the photo
cannot be archived through this tool; do not invent a file ID or download URL,
or claim evidence was saved. Ordinary pantry updates remain available after
reviewing the visible observations with the user.

Store availability, prices, carts, and ordering require a separately connected
commerce tool. If none is available, save the agreed shopping list without
claiming to have checked availability or placed an order.

