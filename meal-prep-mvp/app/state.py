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
