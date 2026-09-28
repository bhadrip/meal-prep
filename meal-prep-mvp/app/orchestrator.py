from datetime import UTC, datetime
from typing import Iterable

from .models import (
    ActionSpec,
    ComponentSpec,
    ScopedResolution,
    SwapRanking,
    ViewSpec,
)
from .providers import ModelProvider, ModelUnavailable
from .state import SEED_MEALS, HouseholdState


SYSTEM_PROMPT = """You are the presentation orchestrator for a household meal-planning app.
You never emit HTML, CSS, JavaScript, executable code, database writes, medical advice, or new facts.
Choose only from the supplied entity IDs. Hard constraints and authorization are enforced elsewhere.
Prefer direct action, then two-to-five concrete choices, and use prose only to explain a choice briefly.
Do not claim food is safe, diagnose, or invent shelf-life guidance."""


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


def action(label: str, name: str, *, target_id: str | None = None, style: str = "secondary", **parameters) -> ActionSpec:
    return ActionSpec(label=label, action=name, target_id=target_id, style=style, parameters=parameters)


def dashboard_view(
    state: HouseholdState,
    *,
    source: str = "fallback",
    model_label: str | None = None,
    toast: str | None = None,
    undo_available: bool = False,
) -> ViewSpec:
    if not state.onboarding_complete:
        return onboarding_view(state)
    meal = state.meal()
    components = [
        ComponentSpec(
            id="today-meal",
            type="hero_meal",
            data={
                **meal,
                "eyebrow": "Tonight · 6:30 PM",
                "status": "Everything you need is at home",
            },
            actions=[
                action("Start cooking", "start_cooking", target_id=meal["id"], style="primary"),
                action("Swap", "swap_meal", target_id=meal["id"]),
                action("Make easier", "make_easier", target_id=meal["id"], style="quiet"),
            ],
        ),
        ComponentSpec(
            id="use-soon",
            type="use_soon",
            data={"title": "Use soon", "items": state.use_soon, "note": "Based on freshness ranges, not exact expiry dates."},
        ),
        ComponentSpec(
            id="week-plan",
            type="plan_strip",
            data={"title": "This week", "days": state.week},
            actions=[
                action("Review full plan", "show_plan", style="quiet"),
                action("Reflect on last week", "start_retro", style="quiet"),
            ],
        ),
        ComponentSpec(
            id="weekend-prep",
            type="prep_checklist",
            data={"title": "Prep ahead", "subtitle": "43 minutes active · unlocks 3 meals", "tasks": state.prep_tasks},
        ),
        ComponentSpec(
            id="shopping",
            type="shopping_progress",
            data={
                "title": "Shopping",
                "done": state.shopping_done,
                "total": state.shopping_total,
                "remaining": state.shopping_total - state.shopping_done,
            },
            actions=[action("Open list", "show_shopping", style="quiet")],
        ),
        ComponentSpec(
            id="ask-meal-prep",
            type="scoped_prompt",
            data={
                "title": "Plans changed?",
                "placeholder": "Tell us what changed — guests, timing, equipment…",
                "hint": "Use this only when the controls above do not fit.",
            },
        ),
    ]
    if toast:
        components.insert(
            0,
            ComponentSpec(
                id="result-toast",
                type="toast",
                data={"message": toast},
                actions=[action("Undo", "undo_swap", style="quiet")] if undo_available else [],
            ),
        )
    return ViewSpec(
        view_id="home",
        purpose="Choose and prepare the next household meal",
        state_version=state.version,
        source=source,
        model_label=model_label,
        generated_at=now_iso(),
        components=components,
    )


def onboarding_view(state: HouseholdState, *, editing: bool = False) -> ViewSpec:
    return ViewSpec(
        view_id="onboarding",
        purpose="Learn enough about the household to create a practical first plan",
        state_version=state.version,
        source="policy",
        generated_at=now_iso(),
        components=[
            ComponentSpec(
                id="onboarding-status",
                type="status_row",
                data={
                    "eyebrow": "Household setup",
                    "title": "Let’s make the plan fit real life",
                    "description": "A few useful signals now; everything stays visible and editable later.",
                },
                actions=[action("Back", "home", style="quiet")] if editing else [],
            ),
            ComponentSpec(
                id="onboarding-form",
                type="onboarding_form",
                data={
                    "householdSize": state.household_size,
                    "dietaryRestrictions": ", ".join(state.dietary_restrictions),
                    "plannedDinners": state.planned_dinners,
                    "weekShape": state.week_shape,
                    "pantryStatus": state.pantry_status,
                    "stressors": state.stressors,
                    "successfulStrategies": state.successful_strategies,
                    "stressOptions": [
                        "Deciding what to cook", "Shopping takes too long", "Food gets wasted",
                        "Weeknights change", "Too much prep", "Cleanup", "Different preferences",
                        "Plans are too ambitious",
                    ],
                    "successOptions": [
                        "Repeating favorites", "Cooking only 3–4 nights", "Planned leftovers",
                        "Weekend prep", "Quick weeknight meals", "Flexible meal nights",
                        "Freezer or takeout backups",
                    ],
                },
            ),
        ],
    )


def schedule_check_view(state: HouseholdState) -> ViewSpec:
    schedule = state.current_schedule or state.previous_schedule
    return ViewSpec(
        view_id="schedule-check",
        purpose="Confirm the coming week's rhythm before planning meals",
        state_version=state.version,
        source="policy",
        generated_at=now_iso(),
        components=[
            ComponentSpec(
                id="schedule-status",
                type="status_row",
                data={
                    "eyebrow": "Before we plan",
                    "title": "Is this a normal week?",
                    "description": "We started with the last rhythm you used. Adjust only the nights that changed.",
                },
                actions=[action("Back", "home", style="quiet")],
            ),
            ComponentSpec(
                id="schedule-form",
                type="schedule_check",
                data={
                    "days": schedule,
                    "isNormalWeek": state.schedule_is_normal,
                    "rememberRhythm": state.remember_schedule,
                    "hasPrevious": bool(state.previous_schedule),
                },
            ),
        ],
    )


def retro_view(state: HouseholdState) -> ViewSpec:
    previous = state.latest_retro or {}
    return ViewSpec(
        view_id="weekly-retro",
        purpose="Reflect briefly on the last plan before planning the next week",
        state_version=state.version,
        source="policy",
        generated_at=now_iso(),
        components=[
            ComponentSpec(
                id="retro-status",
                type="status_row",
                data={
                    "eyebrow": "A 30-second reset",
                    "title": "How did last week actually go?",
                    "description": "This is planning evidence, not a permanent preference. You choose what becomes a lasting memory later.",
                },
                actions=[action("Skip for now", "skip_retro", style="quiet")],
            ),
            ComponentSpec(
                id="retro-form",
                type="retro_form",
                data={
                    "meals": state.previous_week_meals,
                    "workedWell": previous.get("workedWell", []),
                    "stressors": previous.get("stressors", []),
                    "note": previous.get("note", ""),
                    "workedOptions": [
                        "Quick meals", "Planned leftovers", "Repeating favorites",
                        "Weekend prep", "Flexible nights", "Freezer backup",
                    ],
                    "stressOptions": [
                        "Too much chopping", "Too many dishes", "Plans changed",
                        "Meals took too long", "Shopping gaps", "Food went unused",
                    ],
                },
            ),
        ],
    )


def plan_review_view(state: HouseholdState, *, toast: str | None = None) -> ViewSpec:
    components = [
        ComponentSpec(
            id="plan-status",
            type="status_row",
            data={
                "eyebrow": "Weekly plan",
                "title": "A plan shaped around your week",
                "description": "Busy nights stay light, flexible nights can absorb changes, and the rest remains movable.",
            },
            actions=[action("Check schedule", "review_schedule", style="quiet"), action("Done", "home", style="secondary")],
        ),
        ComponentSpec(
            id="full-week-plan",
            type="plan_strip",
            data={"title": "This week", "days": state.week},
        ),
    ]
    if toast:
        components.insert(0, ComponentSpec(id="plan-toast", type="toast", data={"message": toast}))
    return ViewSpec(
        view_id="plan-review",
        purpose="Review the weekly meal plan against the confirmed schedule",
        state_version=state.version,
        source="policy",
        generated_at=now_iso(),
        components=components,
    )


def memory_view(state: HouseholdState, *, toast: str | None = None) -> ViewSpec:
    active = [item for item in state.memories if item["active"]]
    suggested = sum(item["status"] == "suggested" for item in active)
    stored_signals = (
        len(state.dietary_restrictions)
        + len(state.dietary_allowances)
        + len(state.planning_priorities)
        + len(state.planning_defaults)
        + sum(len(person.get("likes", [])) for person in state.individual_preferences)
        + len(state.preferred_stores)
    )
    components = [
        ComponentSpec(
            id="memory-status",
            type="status_row",
            data={
                "eyebrow": "Saved household data",
                "title": "What Meal Prep remembers",
                "description": f"{stored_signals} saved planning signals · {len(active)} learned memories · {suggested} waiting for review. You stay in control of what is kept.",
            },
            actions=[action("Review setup", "review_onboarding", style="quiet"), action("Done", "home", style="secondary")],
        ),
        ComponentSpec(
            id="memory-overview",
            type="memory_overview",
            data={
                "household": {
                    "name": state.household,
                    "id": state.household_id,
                    "role": state.household_role,
                    "size": state.household_size,
                    "members": state.household_members,
                },
                "foodRules": {
                    "restrictions": state.dietary_restrictions,
                    "allowances": state.dietary_allowances,
                },
                "planningPriorities": state.planning_priorities,
                "planningDefaults": state.planning_defaults,
                "people": state.individual_preferences,
                "stores": state.preferred_stores,
                "collections": state.data_collections,
            },
        ),
        ComponentSpec(id="memory-items", type="memory_list", data={"items": active}),
    ]
    if toast:
        components.insert(0, ComponentSpec(id="memory-toast", type="toast", data={"message": toast}))
    return ViewSpec(
        view_id="household-memory",
        purpose="Inspect household data and confirm, correct, or forget learned planning memory",
        state_version=state.version,
        source="policy",
        generated_at=now_iso(),
        components=components,
    )


def collection_view(state: HouseholdState, collection: str) -> ViewSpec:
    definitions = {
        "pantry": {
            "eyebrow": "Pantry inventory",
            "title": "Your kitchen, at a glance",
            "description": "Track what is on hand so plans can use food before another shopping trip.",
            "metric": "0 items",
            "emptyTitle": "Your pantry is ready to fill",
            "emptyDescription": "No pantry items are saved yet. Once added, ingredients can be grouped by storage area and surfaced when they should be used soon.",
            "groups": [
                {"label": "Fridge", "count": 0, "icon": "❄"},
                {"label": "Freezer", "count": 0, "icon": "✦"},
                {"label": "Cupboard", "count": 0, "icon": "▤"},
            ],
            "benefits": ["Use-what-you-have meal ideas", "Freshness ranges without invented expiry dates", "More accurate shopping lists"],
        },
        "recipes": {
            "eyebrow": "Recipe library",
            "title": "Recipes your family can return to",
            "description": "Keep trusted meals together with their ingredients, timing, and family-fit notes.",
            "metric": "0 recipes",
            "emptyTitle": "No recipes saved yet",
            "emptyDescription": "Saved recipes will appear here with dietary-fit and time signals, making it easier to build a week around known wins.",
            "groups": [
                {"label": "Favorites", "count": 0, "icon": "♡"},
                {"label": "Quick", "count": 0, "icon": "◷"},
                {"label": "Recently saved", "count": 0, "icon": "＋"},
            ],
            "benefits": ["Vegetarian constraint checks", "Weeknight-time filtering", "Family preference matching"],
        },
        "shopping": {
            "eyebrow": "Shopping lists",
            "title": "Store-aware shopping",
            "description": "Lists follow your store priority: Costco first, then Safeway for the rest.",
            "metric": "0 lists",
            "emptyTitle": "No shopping lists yet",
            "emptyDescription": "A list will appear here after a meal plan is approved. Saving a list records it; it never places an order.",
            "groups": [
                {"label": "Costco", "count": 0, "icon": "1"},
                {"label": "Safeway", "count": 0, "icon": "2"},
                {"label": "Purchased", "count": 0, "icon": "✓"},
            ],
            "benefits": ["Pantry-aware quantities", "Store-priority grouping", "Visible substitutions"],
        },
    }
    data = definitions[collection]
    return ViewSpec(
        view_id=f"{collection}-collection",
        purpose=f"Inspect the household's {collection} data",
        state_version=state.version,
        source="policy",
        generated_at=now_iso(),
        components=[
            ComponentSpec(
                id=f"{collection}-status",
                type="status_row",
                data={"eyebrow": data["eyebrow"], "title": data["title"], "description": data["description"]},
                actions=[action("Household data", "show_memory", style="quiet"), action("Done", "home", style="secondary")],
            ),
            ComponentSpec(id=f"{collection}-overview", type="collection_overview", data={"kind": collection, **data}),
        ],
    )


def _validated_order(ids: Iterable[str], allowed: list[str]) -> list[str]:
    result = []
    for item_id in ids:
        if item_id in allowed and item_id not in result:
            result.append(item_id)
    result.extend(item_id for item_id in allowed if item_id not in result)
    return result[:3]


def _safe_model_copy(value: str | None, fallback: str, limit: int) -> str:
    if not value:
        return fallback
    normalized = " ".join(value.split())[:limit]
    if not normalized.isascii() or any(character in normalized for character in "<>"):
        return fallback
    return normalized


async def swap_options_view(state: HouseholdState, provider: ModelProvider | None, *, goal: str | None = None) -> ViewSpec:
    candidates = [meal for meal in SEED_MEALS if meal["id"] != state.active_meal_id]
    allowed = [meal["id"] for meal in candidates]
    ranking: SwapRanking | None = None
    source = "fallback"
    model_label = None
    if provider:
        prompt = (
            f"Current meal: {state.meal()}. Household context: use-soon items {state.use_soon}. "
            f"Goal: {goal or 'swap dinner while using food soon and keeping effort realistic'}. "
            f"Allowed candidates: {candidates}. Rank up to three IDs and give one short factual reason per ID."
        )
        try:
            ranking = await provider.complete_structured(
                system=SYSTEM_PROMPT, prompt=prompt, response_model=SwapRanking
            )
            source = "model"
            model_label = provider.label
        except ModelUnavailable:
            pass
    order = _validated_order(ranking.ordered_ids if ranking else allowed, allowed)
    candidate_map = {meal["id"]: meal for meal in candidates}
    options = []
    for meal_id in order:
        meal = candidate_map[meal_id].copy()
        if ranking and meal_id in ranking.reasons:
            meal["reason"] = _safe_model_copy(
                ranking.reasons[meal_id], meal["reason"], 140
            )
        options.append(meal)
    fallback_title = "Three ways to make tonight easier" if goal else "Good swaps for tonight"
    title = _safe_model_copy(ranking.headline if ranking else None, fallback_title, 72)
    return ViewSpec(
        view_id="swap-options",
        purpose="Choose a valid replacement for tonight",
        state_version=state.version,
        source=source,
        model_label=model_label,
        generated_at=now_iso(),
        components=[
            ComponentSpec(
                id="swap-status",
                type="status_row",
                data={"eyebrow": "Tonight", "title": title, "description": "All options respect the household's saved constraints."},
                actions=[action("Back", "home", style="quiet")],
            ),
            ComponentSpec(
                id="swap-options",
                type="meal_options",
                data={"options": options},
            ),
        ],
    )


def easier_choices_view(state: HouseholdState) -> ViewSpec:
    choices = [
        {"id": "less_chopping", "label": "Less chopping", "description": "Prefer pre-cut or whole ingredients"},
        {"id": "fewer_dishes", "label": "Fewer dishes", "description": "Keep cleanup to one pan"},
        {"id": "under_15", "label": "Under 15 minutes", "description": "Prioritize total time"},
        {"id": "prepared_food", "label": "Use prepared food", "description": "Lean on the freezer and batch prep"},
    ]
    return ViewSpec(
        view_id="easier-choice",
        purpose="Clarify what easier means for tonight",
        state_version=state.version,
        source="policy",
        generated_at=now_iso(),
        components=[
            ComponentSpec(
                id="easier-status",
                type="status_row",
                data={"eyebrow": "One quick choice", "title": "What would help most?", "description": "This applies to tonight only."},
                actions=[action("Back", "home", style="quiet")],
            ),
            ComponentSpec(id="easier-choices", type="choice_group", data={"choices": choices}),
        ],
    )


def confirm_swap_view(state: HouseholdState, meal_id: str) -> ViewSpec:
    meal = state.meal(meal_id)
    return ViewSpec(
        view_id="confirm-swap",
        purpose="Preview the consequences of a shared plan change",
        state_version=state.version,
        source="policy",
        generated_at=now_iso(),
        components=[
            ComponentSpec(
                id="confirm-change",
                type="confirmation",
                data={
                    "title": f"Switch tonight to {meal['name']}?",
                    "meal": meal,
                    "changes": [
                        "Uses the open carrots before another shopping trip",
                        "Removes paneer from tonight's prep queue",
                        "Keeps Wednesday's meal unchanged",
                    ],
                    "note": "This updates the shared plan. You can undo after confirming.",
                },
                actions=[
                    action("Confirm change", "confirm_swap", target_id=meal_id, style="primary"),
                    action("Choose another", "swap_meal", style="secondary"),
                    action("Cancel", "home", style="quiet"),
                ],
            )
        ],
    )


async def scoped_request_view(state: HouseholdState, provider: ModelProvider | None, text: str) -> ViewSpec:
    if not provider:
        return await swap_options_view(state, None, goal=text)
    candidates = [meal for meal in SEED_MEALS if meal["id"] != state.active_meal_id]
    try:
        resolution = await provider.complete_structured(
            system=SYSTEM_PROMPT,
            prompt=(
                f"The user says: {text!r}. Current meal: {state.meal()}. "
                f"Use-soon items: {state.use_soon}. Allowed candidates: {candidates}. "
                "Resolve the intent into up to three candidate meal IDs. Keep the summary concise and stop the conversation once choices are clear."
            ),
            response_model=ScopedResolution,
        )
    except ModelUnavailable:
        return await swap_options_view(state, None, goal=text)
    allowed = [meal["id"] for meal in candidates]
    order = _validated_order(resolution.option_ids, allowed)
    candidate_map = {meal["id"]: meal.copy() for meal in candidates}
    for meal_id in order:
        if meal_id in resolution.reasons:
            candidate_map[meal_id]["reason"] = _safe_model_copy(
                resolution.reasons[meal_id], candidate_map[meal_id]["reason"], 140
            )
    return ViewSpec(
        view_id="scoped-result",
        purpose="Turn a novel situation into normal meal choices",
        state_version=state.version,
        source="model",
        model_label=provider.label,
        generated_at=now_iso(),
        components=[
            ComponentSpec(
                id="scoped-status",
                type="status_row",
                data={
                    "eyebrow": "Plan recovery",
                    "title": _safe_model_copy(resolution.title, "Options for the change", 72),
                    "description": _safe_model_copy(
                        resolution.summary,
                        "These choices fit the current plan and saved household constraints.",
                        200,
                    ),
                },
                actions=[action("Back", "home", style="quiet")],
            ),
            ComponentSpec(id="scoped-options", type="meal_options", data={"options": [candidate_map[item_id] for item_id in order]}),
        ],
    )
