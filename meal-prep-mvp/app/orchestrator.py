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


def dashboard_view(state: HouseholdState, *, source: str = "fallback", model_label: str | None = None, toast: str | None = None) -> ViewSpec:
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
            actions=[action("Review full plan", "show_plan", style="quiet")],
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
                actions=[action("Undo", "undo_swap", style="quiet")],
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
