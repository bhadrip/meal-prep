"""Serving estimates and label values; never infer numbers from a meal title."""
import math
from .errors import ApplicationError
from .planning_model import text

MACROS = ("protein", "carbs", "fat", "fiber")
LEVELS = ("unknown", "low", "moderate", "high")
AMOUNTS = ("calories", *MACROS)


def amount(value):
    if value is None:
        return None
    if (isinstance(value, bool) or not isinstance(value, (int, float))
            or not 0 <= value <= 1_000_000 or not math.isfinite(value)
            or round(value, 3) != value):
        raise ApplicationError("Nutrient amount must be a finite nonnegative number with at most 3 decimals")
    return value


def normalize_nutrition(value):
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ApplicationError("Nutrition must be an object")
    basis = text(value.get("basis"), "Nutrition basis", 1000)
    profiles = value.get("profiles")
    if not isinstance(profiles, list) or not 1 <= len(profiles) <= 8:
        raise ApplicationError("Nutrition needs 1–8 serving variations")
    result, names = [], set()
    for profile in profiles:
        if not isinstance(profile, dict):
            raise ApplicationError("Nutrition variation must be an object")
        name = text(profile.get("name"), "Variation name", 80)
        if name.casefold() in names:
            raise ApplicationError("Nutrition variation names must be unique")
        names.add(name.casefold())
        macros = profile.get("macros", {})
        if not isinstance(macros, dict) or set(macros) - set(MACROS):
            raise ApplicationError("Nutrition macros must use protein, carbs, fat, fiber")
        if any(level not in LEVELS for level in macros.values()):
            raise ApplicationError("Nutrition levels must be unknown, low, moderate, high")
        micros = profile.get("micronutrients", [])
        if not isinstance(micros, list) or len(micros) > 12:
            raise ApplicationError("Use at most 12 micronutrient food sources")
        sources = []
        has_numbers = False
        for source in micros:
            if not isinstance(source, dict):
                raise ApplicationError("Micronutrient must identify a nutrient and food source")
            sources.append({"nutrient": text(source.get("nutrient"), "Micronutrient", 80),
                            "source": text(source.get("source"), "Nutrient food source", 180)})
            number = amount(source.get("amount"))
            if number is not None:
                if source.get("unit") not in ("g", "mg", "mcg"):
                    raise ApplicationError("Numeric micronutrients need a unit: g, mg, or mcg")
                sources[-1].update(amount=number, unit=source["unit"])
                has_numbers = True
            elif source.get("unit"):
                raise ApplicationError("Micronutrient unit needs an amount")
        result.append({"name": name, "serving": text(profile.get("serving"), "Serving variation", 1000),
                       "macros": {key: macros.get(key, "unknown") for key in MACROS},
                       "micronutrients": sources})
        amounts = profile.get("amounts", {})
        if not isinstance(amounts, dict) or set(amounts) - set(AMOUNTS):
            raise ApplicationError("Numeric nutrients must use calories, protein, carbs, fat, fiber")
        numbers = {key: amount(value) for key, value in amounts.items()}
        has_numbers = has_numbers or any(value is not None for value in numbers.values())
        if has_numbers:
            portion = text(profile.get("portion"), "Nutrition portion", 300)
            kind = profile.get("valueType", "estimated")
            if kind not in ("estimated", "label"):
                raise ApplicationError("Nutrition valueType must be estimated or label")
            result[-1].update(portion=portion, valueType=kind,
                              amounts={key: numbers.get(key) for key in AMOUNTS})
    return {"basis": basis, "profiles": result}


def weekly_nutrition(plan):
    """Sum one recorded plate per variation per meal; report partial coverage."""
    entries = (plan or {}).get('entries', [])
    profiles = {}
    for entry in entries:
        for plate in (entry.get('nutrition') or {}).get('profiles', []):
            key = plate['name'].casefold()
            row = profiles.setdefault(key, {'name': plate['name'], 'plannedPlates': 0,
                'amounts': {name: {'total': None, 'coveredMeals': 0} for name in AMOUNTS},
                'micronutrients': {}})
            row['plannedPlates'] += 1
            for name in AMOUNTS:
                value = (plate.get('amounts') or {}).get(name)
                if value is not None:
                    total = row['amounts'][name]
                    total['total'] = (total['total'] or 0) + value
                    total['coveredMeals'] += 1
            # Canonical mg allows mixing g, mg and mcg without losing unit meaning.
            seen = set()
            for micro in plate.get('micronutrients', []):
                if micro.get('amount') is None:
                    continue
                nutrient = micro['nutrient'].casefold()
                total = row['micronutrients'].setdefault(nutrient, {
                    'nutrient': micro['nutrient'], 'unit': 'mg', 'total': 0, 'coveredMeals': 0})
                total['total'] += micro['amount'] * {'g': 1000, 'mg': 1, 'mcg': .001}[micro['unit']]
                if nutrient not in seen:
                    total['coveredMeals'] += 1
                seen.add(nutrient)
    for profile in profiles.values():
        for number in profile['amounts'].values():
            if number['total'] is not None:
                number['total'] = round(number['total'], 3)
        profile['micronutrients'] = [{**item, 'total': round(item['total'], 6)}
                                    for item in profile['micronutrients'].values()]
    return {'mealCount': len(entries), 'profiles': list(profiles.values()),
            'basis': 'One stated plate per variation per planned meal. Known values only; not household consumption or daily targets.'}


def with_weekly_nutrition(plan):
    return {**plan, 'nutritionSummary': weekly_nutrition(plan)} if plan is not None else None


def select_variation(nutrition, variation):
    """Direct clients can choose the same view as the rendered variation toggle."""
    if variation is None:
        return nutrition
    name = text(variation, 'Nutrition variation', 80).casefold()
    matches = [profile for profile in (nutrition or {}).get('profiles', [])
               if profile['name'].casefold() == name]
    if not matches:
        raise ApplicationError('Nutrition variation was not found')
    return {**nutrition, 'profiles': matches}
