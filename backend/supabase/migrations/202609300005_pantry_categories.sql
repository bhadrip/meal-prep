alter table public.pantry_items
  add column category text not null default 'uncategorized'
  check (category in ('fruits', 'vegetables', 'snacks', 'frozen', 'dry_goods', 'condiments', 'uncategorized'));

update public.pantry_items
set category = case
  when storage_location = 'freezer' or name ~* '\mfrozen\M' then 'frozen'
  when name ~* '\m(chili oil|chilli oil|garlic paste|ginger paste|hot sauce|soy sauce|fish sauce|sriracha|ketchup|mustard|mayonnaise|mayo|vinegar|pesto|salsa|relish|chutney|tahini|harissa|gochujang|dressing|sauce)\M' then 'condiments'
  when name ~* '\m(chips|crackers|pretzels|popcorn|granola bar|granola bars|protein bar|protein bars|cookies|candy|chocolate|trail mix)\M' then 'snacks'
  when name ~* '\m(apple|apples|banana|bananas|berries|blueberries|strawberries|raspberries|orange|oranges|lemon|lemons|lime|limes|grape|grapes|peach|peaches|pear|pears|mango|mangoes|avocado|avocados|pineapple|pineapples|melon|kiwi)\M' then 'fruits'
  when name ~* '\m(spinach|lettuce|kale|carrot|carrots|broccoli|cauliflower|onion|onions|potato|potatoes|tomato|tomatoes|cucumber|cucumbers|pepper|peppers|zucchini|celery|cabbage|mushroom|mushrooms|asparagus|peas|corn)\M' then 'vegetables'
  when name ~* '\m(rice|lentil|lentils|bean|beans|pasta|flour|oat|oats|quinoa|couscous|cereal|noodle|noodles|sugar|salt|spice|spices|chickpea|chickpeas|almond|almonds|nuts|seeds|bread crumbs)\M' then 'dry_goods'
  else 'uncategorized'
end;
