from copy import deepcopy
from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import uuid4


SEED_MEALS = [
    {
        "id": "paneer-bowl",
        "name": "Paneer rice bowls",
        "minutes": 28,
        "servings": 4,
        "reason": "Uses spinach while it is still at its best",
        "tags": ["Vegetarian", "One pan"],
        "image": "/static/assets/paneer-rice-bowl.png",
    },
    {
        "id": "lemon-chicken",
        "name": "Lemon chicken tray bake",
        "minutes": 35,
        "servings": 4,
        "reason": "Everything is already on the shopping list",
        "tags": ["Low prep", "Family favorite"],
        "image": None,
    },
    {
        "id": "sesame-noodles",
        "name": "Sesame vegetable noodles",
        "minutes": 18,
        "servings": 4,
        "reason": "Fastest option and uses the open carrots",
        "tags": ["Under 20 min", "Pantry-friendly"],
        "image": None,
    },
    {
        "id": "freezer-dal",
        "name": "Freezer dal with flatbread",
        "minutes": 12,
        "servings": 4,
        "reason": "No chopping and only one pan to wash",
        "tags": ["Freezer backup", "Under 15 min"],
        "image": None,
    },
]


@dataclass
class HouseholdState:
    version: int = 7
    household: str = "The Parkers"
    active_meal_id: str = "paneer-bowl"
    previous_meal_id: str | None = None
    shopping_done: int = 9
    shopping_total: int = 14
    prep_tasks: list[dict] = field(
        default_factory=lambda: [
            {"id": "wash-greens", "label": "Wash and dry the greens", "done": True, "minutes": 8},
            {"id": "cook-rice", "label": "Cook rice for two dinners", "done": False, "minutes": 25},
            {"id": "mix-sauce", "label": "Mix sesame-lime sauce", "done": False, "minutes": 10},
        ]
    )
    use_soon: list[dict] = field(
        default_factory=lambda: [
            {"name": "Baby spinach", "amount": "1 bag", "window": "Use today", "tone": "urgent"},
            {"name": "Cilantro", "amount": "½ bunch", "window": "1–2 days", "tone": "soon"},
            {"name": "Carrots", "amount": "4", "window": "3–4 days", "tone": "steady"},
        ]
    )
    week: list[dict] = field(
        default_factory=lambda: [
            {"day": "Mon", "meal": "Tomato pasta", "state": "done"},
            {"day": "Tue", "meal": "Paneer bowls", "state": "today"},
            {"day": "Wed", "meal": "Chicken tray bake", "state": "next"},
            {"day": "Thu", "meal": "Leftovers", "state": "later"},
            {"day": "Fri", "meal": "Taco night", "state": "later"},
        ]
    )
    seen_keys: set[str] = field(default_factory=set)
    decision_records: list[dict] = field(default_factory=list)
    onboarding_complete: bool = False
    household_size: int = 4
    dietary_restrictions: list[str] = field(default_factory=lambda: ["No shellfish"])
    planned_dinners: int = 5
    week_shape: str = "normal"
    pantry_status: str = "mostly_current"
    stressors: list[str] = field(default_factory=list)
    successful_strategies: list[str] = field(default_factory=list)
    previous_schedule: list[dict] = field(
        default_factory=lambda: [
            {"day": "Monday", "mode": "quick"},
            {"day": "Tuesday", "mode": "cook"},
            {"day": "Wednesday", "mode": "quick"},
            {"day": "Thursday", "mode": "leftovers"},
            {"day": "Friday", "mode": "flexible"},
            {"day": "Saturday", "mode": "cook"},
            {"day": "Sunday", "mode": "prep"},
        ]
    )
    current_schedule: list[dict] = field(default_factory=list)
    schedule_confirmed: bool = False
    schedule_is_normal: bool = True
    remember_schedule: bool = True
    retro_due: bool = True
    previous_week_meals: list[dict] = field(
        default_factory=lambda: [
            {"id": "retro-mon", "day": "Monday", "meal": "Tomato pasta", "outcome": "cooked"},
            {"id": "retro-tue", "day": "Tuesday", "meal": "Paneer rice bowls", "outcome": "cooked"},
            {"id": "retro-wed", "day": "Wednesday", "meal": "Lemon chicken tray bake", "outcome": "swapped"},
            {"id": "retro-thu", "day": "Thursday", "meal": "Leftovers", "outcome": "cooked"},
            {"id": "retro-fri", "day": "Friday", "meal": "Taco night", "outcome": "skipped"},
        ]
    )
    latest_retro: dict | None = None
    memories: list[dict] = field(default_factory=list)

    def reset(self) -> None:
        fresh = type(self)()
        self.__dict__.clear()
        self.__dict__.update(fresh.__dict__)

    def complete_onboarding(self, values: dict) -> None:
        self.household_size = min(max(int(values.get("householdSize", 1)), 1), 30)
        self.dietary_restrictions = [
            str(value).strip()[:120]
            for value in values.get("dietaryRestrictions", [])
            if str(value).strip()
        ][:12]
        self.planned_dinners = min(max(int(values.get("plannedDinners", 5)), 1), 7)
        self.week_shape = str(values.get("weekShape", "normal"))[:40]
        self.pantry_status = str(values.get("pantryStatus", "mostly_current"))[:40]
        self.stressors = [str(value)[:80] for value in values.get("stressors", [])][:8]
        self.successful_strategies = [
            str(value)[:80] for value in values.get("successfulStrategies", [])
        ][:8]
        self.onboarding_complete = True
        self.retro_due = False
        for restriction in self.dietary_restrictions:
            self.add_memory("constraint", f"Dietary restriction: {restriction}", "You told us", "confirmed")
        for stressor in self.stressors:
            self.add_memory("pressure", f"Planning stress: {stressor}", "You told us", "confirmed")
        for strategy in self.successful_strategies:
            self.add_memory("success", f"Works well: {strategy}", "You told us", "confirmed")
        self.version += 1

    def save_week_schedule(self, values: dict) -> None:
        allowed_modes = {"cook", "quick", "leftovers", "flexible", "out", "prep"}
        incoming = values.get("days", [])
        rows = []
        for item in incoming[:7]:
            day = str(item.get("day", ""))[:12]
            mode = str(item.get("mode", "flexible"))
            if day and mode in allowed_modes:
                rows.append({"day": day, "mode": mode})
        if len(rows) != 7:
            raise ValueError("a schedule requires seven valid days")
        self.current_schedule = rows
        self.schedule_is_normal = bool(values.get("isNormalWeek", True))
        self.remember_schedule = bool(values.get("rememberRhythm", True))
        if self.remember_schedule:
            self.previous_schedule = deepcopy(rows)
            self.add_memory("schedule", "Start each week from the saved household rhythm", "Schedule check", "confirmed")
        self.schedule_confirmed = True
        self.version += 1

    def save_retro(self, values: dict) -> None:
        allowed_outcomes = {"cooked", "swapped", "skipped"}
        outcomes = []
        for item in values.get("outcomes", [])[:14]:
            outcome = str(item.get("outcome", ""))
            if outcome not in allowed_outcomes:
                raise ValueError("invalid meal outcome")
            outcomes.append(
                {
                    "id": str(item.get("id", ""))[:80],
                    "meal": str(item.get("meal", ""))[:180],
                    "outcome": outcome,
                }
            )
        self.latest_retro = {
            "outcomes": outcomes,
            "workedWell": [str(value)[:80] for value in values.get("workedWell", [])][:8],
            "stressors": [str(value)[:80] for value in values.get("stressors", [])][:8],
            "note": str(values.get("note", "")).strip()[:600],
        }
        for value in self.latest_retro["workedWell"]:
            self.add_memory("success", f"Worked last week: {value}", "Weekly retro", "suggested")
        for value in self.latest_retro["stressors"]:
            self.add_memory("pressure", f"Made last week harder: {value}", "Weekly retro", "suggested")
        self.retro_due = False
        self.schedule_confirmed = False
        self.version += 1

    def add_memory(self, category: str, content: str, source: str, status: str, scope: str = "persistent") -> dict:
        existing = next(
            (item for item in self.memories if item["active"] and item["category"] == category and item["content"].casefold() == content.casefold()),
            None,
        )
        if existing:
            existing["evidenceCount"] += 1
            return existing
        item = {
            "id": str(uuid4()),
            "category": category[:40],
            "content": content.strip()[:240],
            "source": source[:80],
            "status": status if status in {"suggested", "confirmed"} else "suggested",
            "scope": scope if scope in {"persistent", "this_week"} else "persistent",
            "evidenceCount": 1,
            "active": True,
        }
        self.memories.append(item)
        return item

    def review_memory(self, memory_id: str, action: str, content: str | None = None) -> None:
        item = next(value for value in self.memories if value["id"] == memory_id and value["active"])
        if action == "confirm":
            item["status"] = "confirmed"
        elif action == "forget":
            item["active"] = False
        elif action == "update":
            normalized = str(content or "").strip()
            if not normalized:
                raise ValueError("memory text is required")
            item["content"] = normalized[:240]
            item["status"] = "confirmed"
            item["source"] = "You corrected this"
        else:
            raise ValueError("unsupported memory action")
        self.version += 1

    def meal(self, meal_id: str | None = None) -> dict:
        selected = meal_id or self.active_meal_id
        return deepcopy(next(meal for meal in SEED_MEALS if meal["id"] == selected))

    def swap(self, meal_id: str, idempotency_key: str | None) -> bool:
        if idempotency_key and idempotency_key in self.seen_keys:
            return False
        self.meal(meal_id)
        if idempotency_key:
            self.seen_keys.add(idempotency_key)
        self.previous_meal_id = self.active_meal_id
        self.active_meal_id = meal_id
        self.week[1]["meal"] = self.meal()["name"]
        self.version += 1
        return True

    def undo_swap(self) -> bool:
        if not self.previous_meal_id:
            return False
        current = self.active_meal_id
        self.active_meal_id = self.previous_meal_id
        self.previous_meal_id = current
        self.week[1]["meal"] = self.meal()["name"]
        self.version += 1
        return True

    def toggle_prep(self, task_id: str) -> None:
        task = next(item for item in self.prep_tasks if item["id"] == task_id)
        task["done"] = not task["done"]
        self.version += 1

    def record_decision(
        self,
        *,
        action: str,
        decision: str,
        source: str,
        target_id: str | None,
        view_id: str,
    ) -> str:
        decision_id = str(uuid4())
        self.decision_records.append(
            {
                "id": decision_id,
                "action": action,
                "decision": decision,
                "source": source,
                "target_id": target_id,
                "view_id": view_id,
                "state_version": self.version,
                "created_at": datetime.now(UTC).isoformat(),
            }
        )
        return decision_id


STATE = HouseholdState()
