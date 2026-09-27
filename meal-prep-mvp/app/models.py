from typing import Any, Literal

from pydantic import BaseModel, Field


class InteractionEvent(BaseModel):
    action: str = Field(min_length=1, max_length=80)
    target_id: str | None = Field(default=None, max_length=120)
    parameters: dict[str, Any] = Field(default_factory=dict)
    view_id: str = "home"
    state_version: int = 1
    idempotency_key: str | None = Field(default=None, max_length=160)


class ActionSpec(BaseModel):
    label: str
    action: str
    target_id: str | None = None
    parameters: dict[str, Any] = Field(default_factory=dict)
    style: Literal["primary", "secondary", "quiet", "danger"] = "secondary"


class ComponentSpec(BaseModel):
    id: str
    type: Literal[
        "hero_meal",
        "status_row",
        "use_soon",
        "plan_strip",
        "prep_checklist",
        "shopping_progress",
        "choice_group",
        "meal_options",
        "confirmation",
        "scoped_prompt",
        "toast",
        "onboarding_form",
        "schedule_check",
        "retro_form",
    ]
    data: dict[str, Any]
    actions: list[ActionSpec] = Field(default_factory=list)


class ViewSpec(BaseModel):
    schema_version: Literal["1.0"] = "1.0"
    view_id: str
    purpose: str
    state_version: int
    source: Literal["model", "fallback", "policy"]
    model_label: str | None = None
    decision_id: str | None = None
    generated_at: str
    components: list[ComponentSpec]


class SwapRanking(BaseModel):
    ordered_ids: list[str] = Field(min_length=1, max_length=3)
    reasons: dict[str, str]
    headline: str = Field(max_length=90)


class ScopedResolution(BaseModel):
    title: str = Field(max_length=90)
    summary: str = Field(max_length=220)
    option_ids: list[str] = Field(min_length=1, max_length=3)
    reasons: dict[str, str]
