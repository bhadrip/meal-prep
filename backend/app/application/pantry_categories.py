"""Shared pantry categories for website, photo, and MCP writes."""

import re

PANTRY_CATEGORIES = (
    "fruits", "vegetables", "snacks", "frozen", "dry_goods", "condiments", "uncategorized",
)

_WORDS = {
    "condiments": r"chili oil|chilli oil|garlic paste|ginger paste|hot sauce|soy sauce|fish sauce|sriracha|ketchup|mustard|mayonnaise|mayo|vinegar|pesto|salsa|relish|chutney|tahini|harissa|gochujang|dressing|sauce",
    "snacks": r"chips|crackers|pretzels|popcorn|granola bars?|protein bars?|cookies|candy|chocolate|trail mix",
    "fruits": r"apples?|bananas?|berries|blueberries|strawberries|raspberries|oranges?|lemons?|limes?|grapes?|peaches?|pears?|mango(?:es|s)?|avocados?|pineapples?|melon|kiwi",
    "vegetables": r"spinach|lettuce|kale|carrots?|broccoli|cauliflower|onions?|potatoes?|tomatoes?|cucumbers?|peppers?|zucchini|celery|cabbage|mushrooms?|asparagus|peas|corn",
    "dry_goods": r"rice|lentils?|beans?|pasta|flour|oats?|quinoa|couscous|cereal|noodles?|sugar|salt|spices?|chickpeas?|almonds?|nuts|seeds|bread crumbs",
}


def infer_pantry_category(name: str, storage_location: str = "") -> str:
    if storage_location == "freezer" or re.search(r"\bfrozen\b", name, re.I):
        return "frozen"
    for category, pattern in _WORDS.items():
        if re.search(rf"\b(?:{pattern})\b", name, re.I):
            return category
    return "uncategorized"
