"""Capture reported evidence without turning it into an inference or outcome."""
from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from .errors import ApplicationError


class FoodResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True)
    audience: Annotated[str, Field(min_length=1, max_length=80)]
    response: Literal["liked", "mixed", "disliked", "not_tried"]


class ReportedSignals(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True)
    goal: Literal["time", "stress", "kids_enjoyment", "waste", "cost", "shared_work", "variety", "other"] | None = None
    goalNote: Annotated[str, Field(min_length=1, max_length=200)] | None = None
    actualMinutes: Annotated[int, Field(ge=0, le=1440)] | None = None
    effort: Annotated[int, Field(ge=1, le=5)] | None = None
    stressBefore: Annotated[int, Field(ge=1, le=5)] | None = None
    stressAfter: Annotated[int, Field(ge=1, le=5)] | None = None
    planStatus: Literal["followed", "changed", "skipped", "not_planned"] | None = None
    actualMeal: Annotated[str, Field(min_length=1, max_length=180)] | None = None
    whoCooked: Annotated[str, Field(min_length=1, max_length=120)] | None = None
    changeReason: Annotated[str, Field(min_length=1, max_length=200)] | None = None
    context: Annotated[list[Literal["guests", "illness", "late_schedule", "travel", "school_break", "missing_ingredient", "equipment_problem", "other"]], Field(max_length=8)] | None = None
    responses: Annotated[list[FoodResponse], Field(max_length=20)] | None = None
    leftovers: Literal["none", "saved", "discarded"] | None = None
    wasteQuantity: Annotated[float, Field(ge=0, le=100000, allow_inf_nan=False)] | None = None
    wasteUnit: Literal["g", "kg", "ml", "l", "portion", "item"] | None = None
    actualCost: Annotated[float, Field(ge=0, le=100000, allow_inf_nan=False)] | None = None
    currency: Annotated[str, Field(pattern="^[A-Z]{3}$")] | None = None
    startedAt: Annotated[str, Field(max_length=50)] | None = None
    finishedAt: Annotated[str, Field(max_length=50)] | None = None

    @model_validator(mode="after")
    def consistent(self):
        if self.goal == "other" and not self.goalNote:
            raise ValueError("Describe the other household goal")
        if (self.wasteQuantity is None) != (self.wasteUnit is None):
            raise ValueError("Reported waste needs both quantity and unit")
        if (self.actualCost is None) != (self.currency is None):
            raise ValueError("Reported cost needs both amount and currency")
        if self.context is not None and len(set(self.context)) != len(self.context):
            raise ValueError("Context values must be unique")
        if self.responses is not None and len({r.audience.casefold() for r in self.responses}) != len(self.responses):
            raise ValueError("Each audience can have only one reported response")
        times = []
        for value in (self.startedAt, self.finishedAt):
            if value is not None:
                parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
                if parsed.tzinfo is None:
                    raise ValueError("Reported times need a timezone offset")
                times.append(parsed)
        if len(times) == 2 and times[1] < times[0]:
            raise ValueError("Finished time cannot precede started time")
        return self


def normalize_signals(value):
    if not isinstance(value, dict):
        raise ApplicationError("feedback.signals must be an object; omit anything unknown")
    try:
        return ReportedSignals.model_validate(value).model_dump(exclude_none=True)
    except ValidationError as exc:
        issue = exc.errors()[0]
        path = ".".join(str(key) for key in issue["loc"])
        raise ApplicationError(f"Invalid feedback.signals{'.' + path if path else ''}: {issue['msg']}") from exc


def occurred_on(value):
    if value is None:
        return None
    if not isinstance(value, str):
        raise ApplicationError("occurredOn must be an ISO date or unknown")
    try:
        parsed = date.fromisoformat(value)
        if parsed.isoformat() != value:
            raise ValueError()
        return value
    except ValueError as exc:
        raise ApplicationError("occurredOn must be an ISO date or unknown") from exc


def capture_contract():
    return {"schemaVersion": 1, "signals": ReportedSignals.model_json_schema(),
        "workflow": "Use save_feedback for an explicit reported result, or feedbackType=context_update for a household observation. Preserve the person's words in note. Link to a mealPlanEntryId when known; otherwise use weekStart. occurredOn is when it happened; created_at is when it was saved. Use a stable feedback id when retrying.",
        "unknowns": "Omit unknown values. Zero minutes/waste/cost is a reported zero. Completion, adherence, food enjoyment and goal success are separate signals. A context update, skipped plan or missing report is not a failed experiment.",
        "sources": "Input source is set by the server transport. Signals are user reports, not measured facts or LLM estimates. Do not infer illness, preferences, effort, food response, quantities, cost or timing from season, a plan, an image, or silence."}
