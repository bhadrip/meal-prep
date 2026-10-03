const {test, expect} = require('@playwright/test');
const dialog = page => page.locator('#editor-dialog');
let week, suffix, createdRecipes = [], createdMeals = [];
async function request(page, method, path, data) {
  const res = await page.request[method](path, {data});
  expect(res.ok(), await res.text()).toBeTruthy();
  const result = await res.json();
  if (method === 'put' && path === '/api/recipes') createdRecipes.push(result.id);
  if (method === 'put' && path === '/api/meals') createdMeals.push(result.id);
  return result;
}
async function choose(scope, suffix, value) {
  const input = scope.locator(`input[type="hidden"][name$="${suffix}"]`), parent = input.locator('..');
  await parent.locator('.choice-trigger').click(); await parent.locator(`[data-choice-value="${value}"]`).click();
  await expect(input).toHaveValue(value);
}
async function save(page) { await dialog(page).locator('#dialog-save').click(); await expect(dialog(page)).toBeHidden(); }
async function fillComponent(row, data) {
  await row.getByLabel('Food or dish', {exact: true}).fill(data.name);
  if (data.quantity) await row.getByLabel('Amount', {exact: true}).fill(String(data.quantity));
  if (data.unit) await row.getByLabel('Unit', {exact: true}).fill(data.unit);
  if (data.source) await choose(row, '-source', data.source);
  if (data.recipeId) await choose(row, '-recipeId', data.recipeId);
}
async function search(page, query) {
  await page.locator('#recipe-search').fill(query);
  await expect(page.locator('#recipe-search')).toHaveValue(query);
  await expect(page.locator('#recipe-results')).toHaveAttribute('aria-busy', 'false');
}
test.beforeEach(async ({page}) => {
  createdRecipes = []; createdMeals = [];
  suffix = `${test.info().line}-${test.info().retry}-${Date.now()}`;
  const date = new Date('2042-01-06T12:00:00Z'); date.setUTCDate(date.getUTCDate() + 7 * test.info().line);
  week = date.toISOString().slice(0,10);
  const household = await request(page, 'get', '/api/household');
  await request(page, 'put', '/api/meal-slots', {slots: household.mealSlots.map(slot => ({...slot, enabled: slot.id === 'dinner' || slot.enabled}))});
  await request(page, 'put', '/api/meal-plan', {weekStart: week, entries: [], tasks: []});
});

test.afterEach(async ({page}) => {
  for (const id of createdMeals) await request(page, 'delete', `/api/meals/${id}`);
  for (const id of createdRecipes) await request(page, 'delete', `/api/recipes/${id}`);
});

test('Add meal searches saved food, changes only servings and notes, and opens linked recipe', async ({page}) => {
  const recipe = await request(page, 'put', '/api/recipes', {title: `Teriyaki udon ${suffix}`, servings: 4,
    ingredients: [{name: 'Udon', quantity: 400, unit: 'g'}], instructions: ['Cook udon', 'Add tofu']});
  const saved = await request(page, 'put', '/api/meals', {name: `Udon dinner ${suffix}`, servings: 4,
    notes: 'Original library note', components: [{name: recipe.title, quantity: 4, unit: 'servings',
      source: 'cook', action: 'cook', recipeId: recipe.id}]});
  await page.goto(`/app?view=plan&week=${week}`);
  await page.getByRole('button', {name: 'Add meal', exact: true}).click();
  const picker = dialog(page);
  await expect(picker.locator('[name="meal"]')).toHaveCount(0);
  await expect(picker.locator('.component-row')).toHaveCount(0);
  await expect(picker.locator('#dialog-save')).toBeDisabled();
  await picker.locator('#plan-food-search').fill(`Teriyaki udon ${suffix}`);
  await picker.locator('.plan-food-result').filter({hasText: recipe.title}).click();
  await expect(picker.locator('#dialog-save')).toBeEnabled();
  await picker.locator('#plan-food-search').fill('No such dinner in this library');
  await expect(picker.locator('#dialog-save')).toBeDisabled();
  await picker.locator('#plan-food-search').fill(`Teriyaki udon ${suffix}`);
  await picker.locator('.plan-food-result').filter({hasText: recipe.title}).click();
  await picker.locator('[name="servings"]').fill('2');
  await picker.locator('[name="notes"]').fill('Extra chili crunch');
  await save(page);
  const entry = page.locator('.meal').filter({hasText: recipe.title});
  await entry.locator('strong .planned-recipe-link').click();
  await expect(page.locator('#view-title')).toHaveText('Recipes');
  await expect(page.locator('.hero-copy')).toContainText(recipe.title);
  await page.goto(`/app?view=plan&week=${week}`);
  await page.locator('.meal').filter({hasText: recipe.title}).getByRole('button', {name: 'Meal details'}).click();
  const detail = page.locator('#planned-meal-dialog');
  await expect(detail).toContainText('Extra chili crunch');
  await expect(detail).toContainText('2 servings');
  await detail.getByRole('button', {name: `Open recipe: ${recipe.title}`}).click();
  await expect(page.locator('#view-title')).toHaveText('Recipes');
  await expect(page.locator('.hero-copy')).toContainText(recipe.title);
  await expect(page.locator('.card-grid')).toContainText('Cook udon');
  const first = (await request(page, 'get', `/api/meal-plan?week_start=${week}`)).plan.entries[0];
  expect(first.components[0]).toMatchObject({recipeId: recipe.id, quantity: 2});
  expect(first.notes).toBe('Extra chili crunch');

  await page.goto(`/app?view=plan&week=${week}`);
  await page.getByRole('button', {name: 'Add meal', exact: true}).click();
  await picker.locator('#plan-food-search').fill(`Udon dinner ${suffix}`);
  await picker.locator('.plan-food-result').filter({hasText: saved.name}).click();
  await expect(picker.locator('[name="notes"]')).toHaveValue('Original library note');
  await picker.locator('[name="servings"]').fill('8');
  await picker.locator('[name="notes"]').fill('Feed friends tonight');
  await save(page);
  const plan = (await request(page, 'get', `/api/meal-plan?week_start=${week}`)).plan;
  const second = plan.entries.find(row => row.sourceMeal?.id === saved.id);
  expect(second.components[0].quantity).toBe(8);
  expect(second.notes).toBe('Feed friends tonight');
  const savedCard = page.locator(`.meal[data-meal-id="${second.id}"]`);
  await expect(savedCard.getByRole('button', {name: 'Meal details'})).toHaveCount(1);
  await savedCard.getByRole('button', {name: 'Meal details'}).click();
  await expect(page.locator('#planned-meal-dialog')).toContainText('Planned from saved meal');
  expect((await request(page, 'get', `/api/meals/${saved.id}`)).notes).toBe('Original library note');
});

test('Edit planned meal links a recipe through one dropdown and keeps an unselected meal unchanged', async ({page}) => {
  const dal = await request(page, 'put', '/api/recipes', {title: `Dal ${suffix}`, servings: 4});
  const rotis = await request(page, 'put', '/api/recipes', {title: `Ready rotis ${suffix}`, kind: 'ready_food', servings: 4});
  await request(page, 'put', '/api/meal-plan', {weekStart: week, entries: [
    {date: week, slot: 'dinner', meal: `Friends dinner ${suffix}`, servings: 2, notes: 'Original note'}], tasks: []});
  await page.goto(`/app?view=plan&week=${week}`);
  const openEdit = () => page.locator('.meal').getByRole('button', {name: 'Edit', exact: true}).click();
  await openEdit();
  await expect(dialog(page).locator('[name="plannedRecipeId"]').locator('..').locator('.choice-trigger')).toBeVisible();
  await expect(dialog(page).getByRole('status')).toContainText('saved by name only');
  await expect(dialog(page).locator('.component-row')).toHaveCount(0);
  await expect(dialog(page).getByLabel('Food or dish')).toHaveCount(0);
  await expect(dialog(page).getByRole('button', {name: 'Advanced meal details'})).toHaveCount(0);
  await dialog(page).locator('[name="notes"]').fill('Keep this dinner');
  await save(page);
  let entry = (await request(page, 'get', `/api/meal-plan?week_start=${week}`)).plan.entries[0];
  expect(entry.meal).toBe(`Friends dinner ${suffix}`);
  expect(entry.components).toEqual([]);
  await openEdit();
  await choose(dialog(page), 'plannedRecipeId', dal.id);
  await page.route('**/api/meal-plan/items', route => {
    const body = route.request().postDataJSON();
    body.item.sourceMeal = {id: require('crypto').randomUUID(), name: 'Forged origin', revision: 1};
    return route.continue({postData: JSON.stringify(body)});
  });
  await dialog(page).locator('#dialog-save').click();
  await expect(dialog(page).locator('#dialog-error')).toContainText('Saved meal origin cannot be replaced');
  await expect(dialog(page).locator('[name="plannedRecipeId"]')).toHaveValue(dal.id);
  expect((await request(page, 'get', `/api/meal-plan?week_start=${week}`)).plan.entries[0]).toEqual(entry);
  await page.unroute('**/api/meal-plan/items');
  await save(page);
  entry = (await request(page, 'get', `/api/meal-plan?week_start=${week}`)).plan.entries[0];
  expect(entry.meal).toBe(dal.title);
  expect(entry.components[0]).toMatchObject({recipeId: dal.id, source: 'cook', quantity: 2});
  expect(entry.notes).toBe('Keep this dinner');
  await expect(page.locator('.meal').getByRole('link', {name: dal.title})).toBeVisible();
  await openEdit();
  await expect(dialog(page).locator('[name="plannedRecipeId"]')).toHaveValue(dal.id);
  await choose(dialog(page), 'plannedRecipeId', rotis.id);
  await save(page);
  entry = (await request(page, 'get', `/api/meal-plan?week_start=${week}`)).plan.entries[0];
  expect(entry.meal).toBe(rotis.title);
  expect(entry.components).toHaveLength(1);
  expect(entry.components[0]).toMatchObject({recipeId: rotis.id, source: 'ready', action: 'serve'});
  expect(entry.components[0].recipeSnapshot.title).toBe(rotis.title);
  await openEdit();
  await dialog(page).locator('[name="servings"]').fill('3');
  await save(page);
  entry = (await request(page, 'get', `/api/meal-plan?week_start=${week}`)).plan.entries[0];
  expect(entry.servings).toBe(3);
  expect(entry.components[0]).toMatchObject({recipeId: rotis.id, quantity: 3});
});

test('recipe dropdown preserves other planned foods and rejects a duplicate link', async ({page}) => {
  const dal = await request(page, 'put', '/api/recipes', {title: `Dal ${suffix}`, servings: 4});
  const rice = await request(page, 'put', '/api/recipes', {title: `Rice ${suffix}`, servings: 4});
  const salad = await request(page, 'put', '/api/recipes', {title: `Salad ${suffix}`, servings: 4});
  await request(page, 'put', '/api/meal-plan', {weekStart: week, entries: [{date: week, slot: 'dinner',
    meal: `Dinner ${suffix}`, servings: 2, components: [
      {name: dal.title, quantity: 2, unit: 'servings', source: 'cook', action: 'cook', recipeId: dal.id},
      {name: rice.title, quantity: 2, unit: 'servings', source: 'cook', action: 'cook', recipeId: rice.id},
      {name: 'Takeout bread', quantity: 1, unit: 'loaf', source: 'external', action: 'serve'}]}], tasks: []});
  await page.goto(`/app?view=plan&week=${week}`);
  await page.locator('.meal').getByRole('button', {name: 'Edit', exact: true}).click();
  await expect(dialog(page).locator('[data-planned-recipe]')).toHaveCount(2);
  await expect(dialog(page).locator('.component-row')).toHaveCount(0);
  await expect(dialog(page).getByRole('button', {name: 'Advanced meal details'})).toHaveCount(0);
  await choose(dialog(page), 'plannedRecipeId-1', dal.id);
  await dialog(page).locator('#dialog-save').click();
  await expect(dialog(page).locator('#dialog-error')).toContainText('only once');
  let entry = (await request(page, 'get', `/api/meal-plan?week_start=${week}`)).plan.entries[0];
  expect(entry.components.map(part => part.recipeId)).toEqual([dal.id, rice.id, null]);
  await choose(dialog(page), 'plannedRecipeId-1', salad.id);
  await save(page);
  entry = (await request(page, 'get', `/api/meal-plan?week_start=${week}`)).plan.entries[0];
  expect(entry.meal).toBe(`${dal.title} + ${salad.title} + Takeout bread`);
  expect(entry.components.map(part => part.recipeId)).toEqual([dal.id, salad.id, null]);
  expect(entry.components[2]).toMatchObject({name: 'Takeout bread', quantity: 1, unit: 'loaf'});
});

test('edit a planned combination by adding, replacing, and removing recipes', async ({page}) => {
  const tofu = await request(page, 'put', '/api/recipes', {title: `Tofu ${suffix}`});
  const rice = await request(page, 'put', '/api/recipes', {title: `Rice ${suffix}`});
  const greens = await request(page, 'put', '/api/recipes', {title: `Greens ${suffix}`});
  const pita = await request(page, 'put', '/api/recipes', {title: `Pita ${suffix}`, kind: 'ready_food'});
  const planned = await request(page, 'put', '/api/meal-plan', {weekStart: week, entries: [{date: week, slot: 'dinner',
    meal: 'Original dinner', servings: 2, components: [tofu, rice, greens].map(recipe => ({
      name: recipe.title, quantity: 2, unit: 'servings', source: 'cook', action: 'cook', recipeId: recipe.id}))}], tasks: []});
  const id = planned.entries[0].id;
  await page.goto(`/app?view=plan&week=${week}`);
  const card = page.locator(`.meal[data-meal-id="${id}"]`);
  await card.getByRole('button', {name: 'Edit', exact: true}).click();
  const editor = dialog(page);
  await expect(editor.locator('[data-planned-recipe]')).toHaveCount(3);
  const recipeTabPromise = page.waitForEvent('popup');
  await editor.locator('[data-planned-recipe]').first().getByRole('link', {name: 'Open in library to edit'}).click();
  const recipeTab = await recipeTabPromise;
  await expect(recipeTab.getByRole('heading', {name: tofu.title, exact: true})).toBeVisible();
  await expect(recipeTab.getByRole('button', {name: 'Edit recipe'})).toBeVisible();
  await recipeTab.close();
  await editor.getByRole('button', {name: `Remove ${rice.title} from planned meal`}).click();
  await editor.getByRole('button', {name: '+ Add food'}).click();
  const added = editor.locator('[data-planned-recipe]').last();
  const fieldName = await added.locator('input[type="hidden"]').getAttribute('name');
  await choose(added, fieldName, tofu.id);
  await editor.locator('#dialog-save').click();
  await expect(editor.locator('#dialog-error')).toContainText('only once');
  let entry = (await request(page, 'get', `/api/meal-plan?week_start=${week}`)).plan.entries[0];
  expect(entry.components.map(part => part.recipeId)).toEqual([tofu.id, rice.id, greens.id]);
  await choose(added, fieldName, pita.id);
  await save(page);
  entry = (await request(page, 'get', `/api/meal-plan?week_start=${week}`)).plan.entries[0];
  expect(entry.components.map(part => part.recipeId)).toEqual([tofu.id, greens.id, pita.id]);
  expect(entry.components[2]).toMatchObject({source: 'ready', action: 'serve'});
  await expect(card).toContainText(pita.title);
  await card.getByRole('button', {name: 'Edit', exact: true}).click();
  await editor.getByRole('button', {name: `Remove ${tofu.title} from planned meal`}).click();
  await save(page);
  entry = (await request(page, 'get', `/api/meal-plan?week_start=${week}`)).plan.entries[0];
  expect(entry.components.map(part => part.recipeId)).toEqual([greens.id, pita.id]);
  await card.getByRole('button', {name: 'Edit', exact: true}).click();
  await editor.getByRole('button', {name: `Remove ${greens.title} from planned meal`}).click();
  await editor.getByRole('button', {name: `Remove ${pita.title} from planned meal`}).click();
  await editor.locator('#dialog-save').click();
  await expect(editor.locator('#dialog-error')).toContainText('Choose another food');
  expect((await request(page, 'get', `/api/meal-plan?week_start=${week}`)).plan.entries[0].components).toHaveLength(2);
  page.once('dialog', prompt => prompt.accept());
  await editor.getByRole('button', {name: 'Remove this planned meal'}).click();
  await expect(card).toHaveCount(0);
  expect((await request(page, 'get', `/api/meal-plan?week_start=${week}`)).plan.entries).toHaveLength(0);
});

test('a dated food selection displays as one unit without asking for a planned-meal name', async ({page}) => {
  const curry = await request(page, 'put', '/api/recipes', {title: `Vegetable curry ${suffix}`});
  const rice = await request(page, 'put', '/api/recipes', {title: `Ready rice ${suffix}`, kind: 'ready_food'});
  const plan = await request(page, 'patch', '/api/meal-plan/items', {weekStart: week, kind: 'meal', item: {
    date: week, slot: 'dinner', servings: 2, components: [
      {name: curry.title, source: 'cook', action: 'cook', recipeId: curry.id},
      {name: rice.title, source: 'ready', action: 'serve', recipeId: rice.id}]}});
  expect(plan.entries[0].meal).toBe(`${curry.title} + ${rice.title}`);
  await page.goto(`/app?view=plan&week=${week}`);
  const card = page.locator(`.meal[data-meal-id="${plan.entries[0].id}"]`);
  await expect(card.locator('strong')).toHaveText('2 foods together');
  await expect(card.getByRole('link', {name: curry.title})).toBeVisible();
  await expect(card.getByRole('link', {name: rice.title})).toBeVisible();
  await expect(card.getByRole('button', {name: 'Meal details'})).toHaveCount(1);
  await expect(card.getByRole('button', {name: '2 foods together'})).toHaveCount(0);
  await card.getByRole('button', {name: 'Edit', exact: true}).click();
  await expect(dialog(page).locator('[name="meal"]')).toHaveCount(0);
  await expect(dialog(page).locator('[data-planned-recipe]')).toHaveCount(2);
  await dialog(page).getByRole('button', {name: 'Cancel'}).click();
  await card.getByRole('button', {name: 'Meal details'}).click();
  await expect(page.locator('#planned-meal-dialog')).toContainText(curry.title);
  await expect(page.locator('#planned-meal-dialog')).toContainText(rice.title);
});

test('Add meal combines a recipe and ready food into one planned dinner with separate links', async ({page}) => {
  const udon = await request(page, 'put', '/api/recipes', {title: `Udon ${suffix}`, servings: 4,
    ingredients: [{name: 'Udon noodles', quantity: 400, unit: 'g'}]});
  const salad = await request(page, 'put', '/api/recipes', {title: `Ready salad ${suffix}`,
    kind: 'ready_food', servings: 4});
  await page.goto(`/app?view=plan&week=${week}`);
  await page.getByRole('button', {name: 'Add meal', exact: true}).click();
  const picker = dialog(page);
  await picker.locator('#plan-food-search').fill(udon.title);
  await picker.locator('.plan-food-result').filter({hasText: udon.title}).click();
  await picker.getByRole('button', {name: 'Add another recipe or ready food'}).click();
  await expect(picker.locator('#plan-food-selected')).toContainText(udon.title);
  await expect(picker.locator('.plan-food-result').filter({hasText: udon.title})).toHaveCount(0);
  await picker.locator('#plan-food-search').fill(salad.title);
  await picker.locator('.plan-food-result').filter({hasText: salad.title}).click();
  await expect(picker.locator('#plan-food-selected')).toContainText(salad.title);
  await picker.getByRole('button', {name: `Remove ${salad.title}`}).click();
  await expect(picker.locator('#plan-food-selected')).not.toContainText(salad.title);
  await picker.locator('#plan-food-search').fill(salad.title);
  await picker.locator('.plan-food-result').filter({hasText: salad.title}).click();
  await picker.locator('[name="servings"]').fill('2');
  await picker.locator('[name="notes"]').fill('Serve together');
  await save(page);
  const plan = (await request(page, 'get', `/api/meal-plan?week_start=${week}`)).plan;
  expect(plan.entries).toHaveLength(1);
  expect(plan.entries[0].notes).toBe('Serve together');
  expect(plan.entries[0].components.map((row) => [row.recipeId, row.quantity, row.source])).toEqual([
    [udon.id, 2, 'cook'], [salad.id, 2, 'ready']]);
  const entry = page.locator('.meal').filter({hasText: udon.title});
  await expect(entry).toContainText(salad.title);
  await entry.getByRole('link', {name: salad.title}).click();
  await expect(page.locator('.hero-copy')).toContainText(salad.title);
});

test('Create meal saves a reusable combination from library recipes and ready food', async ({page}) => {
  const soup = await request(page, 'put', '/api/recipes', {title: `Soup ${suffix}`, servings: 4});
  const bread = await request(page, 'put', '/api/recipes', {title: `Ready bread ${suffix}`,
    kind: 'ready_food', servings: 4});
  await page.goto('/app?view=recipes&type=meals');
  await page.getByRole('button', {name: 'Create meal'}).click();
  const picker = dialog(page);
  await expect(picker.locator('.component-row')).toHaveCount(0);
  await picker.locator('#plan-food-search').fill(soup.title);
  await picker.locator('.plan-food-result').filter({hasText: soup.title}).click();
  await expect(picker.locator('#dialog-save')).toBeDisabled();
  await picker.locator('#plan-food-search').fill(bread.title);
  await picker.locator('.plan-food-result').filter({hasText: bread.title}).click();
  await expect(picker.locator('#dialog-save')).toBeEnabled();
  await picker.locator('[name="servings"]').fill('3');
  await picker.locator('[name="notes"]').fill('Simple weeknight dinner');
  await save(page);
  const meals = (await request(page, 'get', `/api/meals?query=${encodeURIComponent(suffix)}`)).items;
  const combined = meals.find((meal) => meal.name === `${soup.title} + ${bread.title}`);
  expect(combined).toBeTruthy(); createdMeals.push(combined.id);
  expect(combined.notes).toBe('Simple weeknight dinner');
  expect(combined.components.map((food) => [food.recipeId, food.quantity, food.source])).toEqual([
    [soup.id, 3, 'cook'], [bread.id, 3, 'ready']]);
  const card = page.locator(`[data-saved-meal="${combined.id}"]`);
  await expect(card).toContainText(soup.title);
  await expect(card).toContainText(bread.title);
  await card.getByRole('button', {name: bread.title}).click();
  await expect(page.locator('.hero-copy')).toContainText(bread.title);
  const planned = await request(page, 'post', `/api/meals/${combined.id}/plan`, {weekStart: week, date: week, slot: 'dinner', servings: 3});
  await page.goto(`/app?view=plan&week=${week}`);
  await page.locator(`.meal[data-meal-id="${planned.entries[0].id}"]`).getByRole('button', {name: 'Meal details'}).click();
  await expect(page.locator('#planned-meal-dialog')).toContainText('already saved in your meal library');
  await expect(page.locator('#planned-meal-dialog').getByRole('button', {name: 'Save as reusable meal'})).toHaveCount(0);
  await expect(page.locator('#planned-meal-dialog').getByRole('tooltip')).toHaveCount(0);
});

test('a named planned meal opens details without inventing a recipe or saving a copy', async ({page}) => {
  await request(page, 'put', '/api/recipes', {title: `Friends dinner ${suffix}`, servings: 2});
  await request(page, 'put', '/api/meal-plan', {weekStart: week, entries: [{date: week, slot: 'dinner',
    meal: `Friends dinner ${suffix}`, notes: 'Bring salad'}], tasks: []});
  await page.goto(`/app?view=plan&week=${week}`);
  await page.locator('.meal').getByRole('button', {name: 'Meal details'}).click();
  const detail = page.locator('#planned-meal-dialog');
  await expect(detail).toContainText('Bring salad');
  await expect(detail).toContainText('No recipe or ready food is linked');
  await expect(detail.getByRole('button', {name: /Open recipe/})).toHaveCount(0);
  await detail.getByRole('button', {name: 'Search recipes for this meal'}).click();
  await expect(page.locator('#view-title')).toHaveText('Recipes');
  await expect(page.locator('#recipe-search')).toHaveValue(`Friends dinner ${suffix}`);
  await expect(page.locator('#recipe-results')).toContainText(`Friends dinner ${suffix}`);
  expect((await request(page, 'get', `/api/meals?query=${encodeURIComponent(suffix)}`)).items).toHaveLength(0);
});

test('Meals category creates recipes plus ready food, scales a dated copy, and calculates pantry-aware shopping', async ({page}) => {
  const dal = await request(page, 'put', '/api/recipes', {title: `Dal ${suffix}`, servings: 4, ingredients: [{name: `Lentils ${suffix}`, quantity: 200, unit: 'g'}]});
  const salad = await request(page, 'put', '/api/recipes', {title: `Salad ${suffix}`, servings: 2, ingredients: [{name: `Carrots ${suffix}`, quantity: 100, unit: 'g'}]});
  const stock = await request(page, 'put', '/api/pantry', {name: `Rotis ${suffix}`, quantity: 10, unit: 'pieces', quantityConfidence: 'exact'});
  await page.goto(`/app?view=plan&week=${week}`);
  await page.getByRole('button', {name: 'Use saved meal', exact: true}).click();
  await expect(page.locator('#view-title')).toHaveText('Recipes');
  await expect(page.getByRole('combobox', {name:'Library type'})).toHaveValue('meals');
  await page.getByRole('button', {name: 'Create meal', exact: true}).click();
  await dialog(page).getByRole('button', {name: 'Advanced meal details'}).click();
  await dialog(page).getByLabel('Meal name', {exact: true}).fill(`Dinner ${suffix}`);
  await dialog(page).getByLabel('Default servings').fill('4');
  await dialog(page).getByLabel('Notes', {exact: true}).fill(`Quick family dinner ${suffix}`);
  const values = [{name: stock.name, quantity: 8, unit: 'pieces'}, {name: dal.title, quantity: 4, unit: 'servings', source: 'cook', recipeId: dal.id}, {name: salad.title, quantity: 4, unit: 'servings', source: 'cook', recipeId: salad.id}];
  for (let i=0; i<values.length; i++) {
    if (i) await dialog(page).getByRole('button', {name: 'Add food', exact: true}).click();
    await fillComponent(dialog(page).locator('.component-row').nth(i), values[i]);
  }
  await save(page);
  await search(page, suffix);
  const card = page.locator('[data-saved-meal]').filter({hasText: `Dinner ${suffix}`});
  await expect(card).toContainText(dal.title); await expect(card).toContainText(salad.title);
  const id = await card.getAttribute('data-saved-meal');
  await card.getByRole('button', {name: 'Plan this meal'}).click();
  await expect(dialog(page).getByLabel('Date', {exact: true})).toHaveValue(week);
  await dialog(page).getByLabel('Servings to plan').fill('8'); await save(page);
  await expect(page.locator('.meal').filter({hasText: `Dinner ${suffix}`})).toContainText(`16 pieces`);
  const plan = (await request(page, 'get', `/api/meal-plan?week_start=${week}`)).plan;
  expect(plan.entries[0].sourceMeal.id).toBe(id);
  expect(plan.entries[0].components.map(row => row.quantity)).toEqual([16,8,8]);
  await page.getByRole('button', {name: 'Shopping needs', exact: true}).click();
  await expect(dialog(page)).toContainText(`Lentils ${suffix}`);
  await dialog(page).getByRole('button', {name: 'Update shopping list'}).click(); await expect(dialog(page)).toBeHidden();
  const list = (await request(page, 'get', '/api/shopping-list')).shoppingList.items;
  expect(list.find(row => row.name === stock.name).quantity).toBe(6);
  expect(list.find(row => row.name === `Lentils ${suffix}`).quantity).toBe(400);
  expect(list.find(row => row.name === `Carrots ${suffix}`).quantity).toBe(400);
  expect((await request(page, 'get', '/api/pantry')).items.find(row => row.id === stock.id).quantity).toBe(10);
  await page.goto(`/app?view=recipes&type=meals&query=${suffix}`);
  await card.getByRole('button', {name: 'Edit', exact: true}).click();
  await dialog(page).getByLabel('Meal name', {exact: true}).fill(`Changed dinner ${suffix}`); await save(page);
  const revised = await request(page, 'get', `/api/meals/${id}`); expect(revised.revision).toBe(2);
  expect((await request(page, 'get', `/api/meal-plan?week_start=${week}`)).plan).toEqual(plan);
  await card.getByRole('button', {name: 'Archive', exact: true}).click(); await expect(card).toHaveCount(0);
  await page.goto(`/app?view=plan&week=${week}`);
  await expect(page.locator('.meal')).toContainText(`Dinner ${suffix}`);
  expect((await request(page, 'get', `/api/meal-plan?week_start=${week}`)).plan).toEqual(plan);
  await page.locator('.meal').getByRole('button', {name: 'Edit', exact: true}).click();
  await dialog(page).getByRole('textbox', {name: 'Notes', exact: true}).fill('Serve after school'); await save(page);
  const edited = (await request(page, 'get', `/api/meal-plan?week_start=${week}`)).plan.entries[0];
  expect(edited.sourceMeal).toEqual(plan.entries[0].sourceMeal);
  expect(edited.components).toEqual(plan.entries[0].components);
  expect(edited.notes).toBe('Serve after school');
});

test('mobile library retains a failed recipe draft, saves corrected food, and searches notes and components', async ({page}) => {
  await page.setViewportSize({width:390,height:844}); await page.goto('/app?view=recipes&type=meals');
  await page.locator('.mobile-nav [data-view="recipes"]').click();
  await expect(page.getByRole('combobox', {name:'Library type'})).toHaveValue('meals');
  await page.getByRole('button', {name:'Create meal'}).click();
  await dialog(page).getByRole('button', {name: 'Advanced meal details'}).click();
  await dialog(page).getByLabel('Meal name', {exact:true}).fill(`Snack ${suffix}`);
  const row=dialog(page).locator('.component-row');
  await fillComponent(row,{name:`Popcorn ${suffix}`,quantity:2,unit:'portions',source:'cook'});
  await dialog(page).locator('#dialog-save').click();
  await expect(dialog(page).locator('#dialog-error')).toContainText('recipeId');
  await expect(row.getByLabel('Food or dish')).toHaveValue(`Popcorn ${suffix}`);
  expect((await request(page,'get',`/api/meals?query=${suffix}`)).total).toBe(0);
  await choose(row,'-source','ready');
  await dialog(page).getByLabel('Notes',{exact:true}).fill(`School pickup ${suffix}`); await save(page);
  await search(page,`popcorn ${suffix}`); await expect(page.locator('[data-saved-meal]')).toHaveCount(1);
  await search(page,`pickup ${suffix}`); await expect(page.locator('[data-saved-meal]')).toHaveCount(1);
  await page.reload(); await expect(page.locator('[data-saved-meal]')).toHaveCount(1);
  expect(await page.evaluate(()=>document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});

test('search and pagination find older meals beyond the first page', async ({page}) => {
  const older = await request(page,'put','/api/meals',{name:`Old ${suffix}`,servings:1,components:[{name:`Rare popcorn ${suffix}`}]});
  for(let i=0;i<52;i++) await request(page,'put','/api/meals',{name:`Page meal ${suffix} ${i}`,servings:1,components:[{name:'Roti'}]});
  await page.goto(`/app?view=recipes&type=meals&query=${suffix}`);
  await expect(page.locator('[data-saved-meal]')).toHaveCount(50);
  await page.getByRole('button',{name:'Show more meals'}).click(); await expect(page.locator('[data-saved-meal]')).toHaveCount(53);
  await expect(page.locator(`[data-saved-meal="${older.id}"]`)).toBeVisible();
  await search(page,`Rare popcorn ${suffix}`); await expect(page.locator('[data-saved-meal]')).toHaveCount(1);
  await expect(page.locator('[data-saved-meal]')).toHaveAttribute('data-saved-meal',older.id);
});

test('Save combination copies a mixed dinner while single recipes need no duplicate meal', async ({page}) => {
  const recipe = await request(page,'put','/api/recipes',{title:`Batch dal ${suffix}`,servings:4,ingredients:[{name:'Lentils',quantity:200,unit:'g'}]});
  const taskId=require('crypto').randomUUID(), stock=await request(page,'put','/api/pantry',{name:`Roti ${suffix}`,quantity:8,unit:'pieces'});
  const plan=await request(page,'put','/api/meal-plan',{weekStart:week,tasks:[{id:taskId,title:'Cook once',recipeId:recipe.id,servings:8}],entries:[{date:week,slot:'dinner',meal:`Batch dinner ${suffix}`,servings:4,components:[{name:recipe.title,quantity:4,unit:'servings',source:'task',taskId},{name:stock.name,quantity:8,unit:'pieces',pantryItemId:stock.id}]}]});
  await page.goto(`/app?view=plan&week=${week}`); await page.locator('.meal').getByRole('button',{name:'Meal details'}).click();
  await expect(page.locator('#planned-meal-dialog').getByRole('tooltip')).toHaveCount(0);
  await expect(page.locator('#planned-meal-dialog').getByRole('button',{name:'About saving this meal'})).toHaveCount(0);
  await expect(page.locator('#planned-meal-dialog')).not.toContainText('These foods are already combined for this date');
  await page.locator('#planned-meal-dialog').getByRole('button',{name:'Save as reusable meal'}).click();
  await expect(dialog(page).locator('[data-source="task"]')).toHaveCount(0); await save(page);
  const saved=(await request(page,'get',`/api/meals?query=${suffix}`)).items.find(row=>row.name===`Batch dinner ${suffix}`);
  createdMeals.push(saved.id);
  expect(saved.components[0]).toMatchObject({source:'cook',recipeId:recipe.id,taskId:null,pantryItemId:null});
  expect(saved.components[1].pantryItemId).toBeNull();
  expect((await request(page,'get',`/api/meal-plan?week_start=${week}`)).plan).toEqual(plan);
  await page.goto(`/app?view=recipes&recipe=${recipe.id}`);
  await expect(page.getByRole('button',{name:'Save as meal'})).toHaveCount(0);
  const ready=await request(page,'put','/api/recipes',{title:`Ready rotis ${suffix}`,kind:'ready_food'});
  const readyTask=require('crypto').randomUUID();
  await request(page,'put','/api/meal-plan',{weekStart:week,tasks:[{id:readyTask,title:'Heat rotis',recipeId:ready.id,servings:4}],entries:[{date:week,slot:'dinner',meal:`Heated rotis ${suffix}`,servings:4,components:[{name:ready.title,source:'task',taskId:readyTask,action:'heat',quantity:8,unit:'pieces'}]}]});
  await page.goto(`/app?view=plan&week=${week}`); await page.locator('.meal').getByRole('button',{name:'Meal details'}).click();
  await expect(page.locator('#planned-meal-dialog').getByRole('button',{name:'Save as reusable meal'})).toHaveCount(0);
  expect((await request(page,'get',`/api/meals?query=Heated%20rotis%20${suffix}`)).items).toHaveLength(0);
});

async function mountMcp(page, data) {
  await page.route('**/meal-library-host', route=>route.fulfill({contentType:'text/html',body:`<!doctype html><iframe src="/static/mcp-app.html" style="width:100%;height:1000px"></iframe><script>
  window.ready=false;window.calls=[];addEventListener('message',async event=>{const m=event.data;if(m?.jsonrpc!=='2.0'||!m.method)return;
  if(m.method==='ui/notifications/initialized'){window.ready=true;return;}
  if(m.method==='ui/initialize'){event.source.postMessage({jsonrpc:'2.0',id:m.id,result:{}},'*');return;}
  if(m.method==='tools/call'){window.calls.push(m.params);const res=await fetch('/mcp',{method:'POST',headers:{'Content-Type':'application/json',Accept:'application/json, text/event-stream'},body:JSON.stringify(m)});event.source.postMessage(await res.json(),'*');}});</script>`}));
  await page.goto('/meal-library-host');await expect.poll(()=>page.evaluate(()=>window.ready)).toBe(true);
  await page.evaluate(data=>document.querySelector('iframe').contentWindow.postMessage({jsonrpc:'2.0',method:'ui/notifications/tool-result',params:{structuredContent:data}},'*'),data);
}
test('MCP App Meals category searches via real tools, preserves failed planning, and plans scaled food', async ({page})=>{
  const meal=await request(page,'put','/api/meals',{name:`Chat dinner ${suffix}`,servings:2,components:[{name:`Ready rotis ${suffix}`,quantity:4,unit:'pieces'}]});
  const household=await request(page,'get','/api/household');
  await mountMcp(page,{kind:'meal_library',library:await request(page,'get','/api/meals'),household});
  const frame=page.frameLocator('iframe');
  await frame.getByLabel('Search recipes', {exact:true}).fill(`Ready rotis ${suffix}`);
  await expect(frame.locator('[data-saved-meal]')).toHaveCount(1);
  await frame.getByRole('button',{name:'Plan this meal'}).click();
  const form=frame.locator('#plan-saved-meal-form');
  await form.getByLabel('Date',{exact:true}).fill(week);await form.getByLabel('Servings to plan').fill('6');
  await request(page,'delete',`/api/meals/${meal.id}`);
  await form.getByRole('button',{name:'Add to weekly plan'}).click(); await expect(form.locator('.form-error')).toContainText('Archived');
  await expect(form.getByLabel('Servings to plan')).toHaveValue('6');
  expect((await request(page,'get',`/api/meal-plan?week_start=${week}`)).plan.entries).toHaveLength(0);
  const replacement=await request(page,'put','/api/meals',{...meal,id:undefined});
  await frame.getByLabel('Search recipes', {exact:true}).fill(suffix);
  await frame.locator(`[data-saved-meal="${replacement.id}"]`).getByRole('button',{name:'Plan this meal'}).click();
  await expect(form).toHaveAttribute('data-id',replacement.id);
  await form.getByLabel('Date',{exact:true}).fill(week);await form.getByLabel('Servings to plan').fill('6'); await form.getByRole('button',{name:'Add to weekly plan'}).click();
  await expect(frame.locator('[data-plan-meal]')).toContainText('12 pieces');
  const plan=(await request(page,'get',`/api/meal-plan?week_start=${week}`)).plan;
  expect(plan.entries[0].sourceMeal.id).toBe(replacement.id);expect(plan.entries[0].components[0].quantity).toBe(12);
  expect(await page.evaluate(()=>window.calls.map(row=>row.name))).toEqual(expect.arrayContaining(['browse_recipe_library','get_meal','plan_saved_meal']));
});

test('new meal recipe picker includes recipes beyond the first page and fills the dish name and serving unit', async ({page}) => {
  const older = await request(page, 'put', '/api/recipes', {title: `Old recipe ${suffix}`, servings: 4});
  for (let i=0; i<51; i++) await request(page, 'put', '/api/recipes', {title: `Picker recipe ${suffix} ${i}`});
  await page.goto('/app?view=recipes&type=meals'); await page.getByRole('button', {name:'Create meal'}).click();
  await dialog(page).getByRole('button', {name: 'Advanced meal details'}).click();
  await dialog(page).getByLabel('Meal name', {exact:true}).fill(`Recipe meal ${suffix}`);
  const row=dialog(page).locator('.component-row');
  await choose(row, '-source', 'cook'); await choose(row, '-recipeId', older.id);
  await expect(row.getByLabel('Food or dish')).toHaveValue(older.title);
  await expect(row.getByLabel('Unit', {exact:true})).toHaveValue('servings');
  await row.getByLabel('Amount', {exact:true}).fill('4'); await save(page);
  const meal=(await request(page, 'get', `/api/meals?query=${suffix}`)).items[0];
  expect(meal.components[0]).toMatchObject({name:older.title, recipeId:older.id, unit:'servings', quantity:4});
});

test('one library mixes recipes, ready food and meals, filters them, and opens component details without losing the meal filter', async ({page}) => {
  const recipe=await request(page,'put','/api/recipes',{title:`Dal ${suffix}`,servings:4,ingredients:[{name:'Lentils',quantity:200,unit:'g'}]});
  await page.goto('/app?view=recipes');
  await page.getByRole('button',{name:'Add recipe',exact:true}).click();
  await choose(dialog(page),'kind','ready_food');
  await dialog(page).getByLabel('Recipe name',{exact:true}).fill(`Pre-cooked rotis ${suffix}`);
  await dialog(page).getByLabel('Tags, separated by commas',{exact:true}).fill('quick');
  await dialog(page).getByLabel('Ingredients — one per line: name | quantity | unit').fill('Flour | 100 | g');
  await dialog(page).locator('#dialog-save').click();
  await expect(dialog(page).locator('#dialog-error')).toContainText('Ready food has no ingredient demand');
  await dialog(page).getByLabel('Ingredients — one per line: name | quantity | unit').fill('');
  await save(page);
  const ready=(await request(page,'get',`/api/recipes?query=${suffix}&limit=25`)).items.find(row=>row.kind==='ready_food');
  expect(ready).toBeTruthy(); createdRecipes.push(ready.id);
  await page.getByRole('button',{name:'← All recipes',exact:true}).click();
  await page.getByRole('button',{name:'Create meal',exact:true}).click();
  await dialog(page).getByRole('button', {name: 'Advanced meal details'}).click();
  await dialog(page).getByLabel('Meal name',{exact:true}).fill(`Dinner ${suffix}`);
  const first=dialog(page).locator('.component-row').first();
  await choose(first,'-recipeId',recipe.id); await expect(first.locator('input[name$="-source"]')).toHaveValue('cook');
  await expect(first.locator('input[name$="-action"]')).toHaveValue('cook');
  await first.getByLabel('Amount',{exact:true}).fill('4');
  await dialog(page).getByRole('button',{name:'Add food',exact:true}).click();
  const second=dialog(page).locator('.component-row').nth(1);
  await choose(second,'-recipeId',ready.id); await expect(second.locator('input[name$="-source"]')).toHaveValue('ready');
  await second.getByLabel('Amount',{exact:true}).fill('8'); await second.getByLabel('Unit',{exact:true}).fill('pieces');
  await save(page);
  const meal=(await request(page,'get',`/api/meals?query=${suffix}`)).items[0]; createdMeals.push(meal.id);
  expect(meal.components[1]).toMatchObject({recipeId:ready.id,source:'ready',name:ready.title});
  await page.goto(`/app?view=recipes&query=${suffix}`);
  await expect(page.locator('.recipe-card')).toHaveCount(2); await expect(page.locator('[data-saved-meal]')).toHaveCount(1);
  const type=page.getByRole('combobox',{name:'Library type'});
  await type.selectOption('ready_food'); await expect(page.locator('.recipe-card')).toHaveCount(1);
  await expect(page.locator('.recipe-card')).toContainText(ready.title); await expect(page.locator('[data-saved-meal]')).toHaveCount(0);
  await type.selectOption('meals'); await expect(page.locator('[data-saved-meal]')).toHaveAttribute('data-saved-meal',meal.id);
  await page.locator('#recipe-search').fill(`Dinner ${suffix}`);
  await page.getByRole('group',{name:'Browse recipes by'}).getByRole('button',{name:'Tags',exact:true}).click();
  await page.locator('.rb-options').getByRole('button',{name:/^quick /}).click();
  await expect(page.locator('[data-saved-meal]')).toHaveAttribute('data-saved-meal',meal.id);
  await page.getByRole('button',{name:'Clear tag',exact:true}).click();
  await page.locator('#recipe-search').fill(suffix);
  await page.locator('[data-saved-meal]').getByRole('button',{name:recipe.title,exact:true}).click();
  await expect(page.locator('.hero h2')).toHaveText(recipe.title); await expect(page.locator('#app-content')).toContainText('Lentils');
  await page.getByRole('button',{name:'← All recipes',exact:true}).click();
  await expect(type).toHaveValue('meals'); await expect(page.locator('#recipe-search')).toHaveValue(suffix);
  await page.locator('[data-saved-meal]').getByRole('button',{name:ready.title,exact:true}).click();
  await expect(page.locator('.hero h2')).toHaveText(ready.title); await expect(page.locator('.hero .eyebrow')).toHaveText('Ready food');
  await page.goBack(); await expect(page.locator('[data-saved-meal]')).toHaveAttribute('data-saved-meal',meal.id);
  await page.reload(); await expect(type).toHaveValue('meals'); await expect(page.locator('#recipe-search')).toHaveValue(suffix);
  expect(new URL(page.url()).searchParams.get('view')).toBe('recipes');
  await page.locator('[data-saved-meal]').getByRole('button',{name:ready.title,exact:true}).click();
  await page.getByRole('button',{name:'Create share link',exact:true}).click();
  await page.getByRole('button',{name:'Confirm public link'}).click();
  const shareUrl=await page.getByRole('textbox',{name:'New recipe share link'}).inputValue();
  await page.goto(shareUrl);await page.locator('#save-recipe').click();
  await expect(page.locator('#message')).toHaveText('Saved to your household recipes.');
  const copies=(await request(page,'get',`/api/recipe-library?item_type=ready_food&query=${suffix}`)).items;
  expect(copies).toHaveLength(2);expect(copies.every(row=>row.kind==='ready_food')).toBe(true);
  createdRecipes.push(copies.find(row=>row.id!==ready.id).id);
});

test('MCP App shares type filters and opens recipes and ready food from a meal, retaining the filtered library', async ({page}) => {
  const recipe=await request(page,'put','/api/recipes',{title:`Dal ${suffix}`,servings:4,ingredients:[{name:'Lentils',quantity:200,unit:'g'}]});
  const ready=await request(page,'put','/api/recipes',{title:`Rotis ${suffix}`,kind:'ready_food',instructions:['Heat for a minute']});
  const meal=await request(page,'put','/api/meals',{name:`Dinner ${suffix}`,servings:4,components:[{name:recipe.title,recipeId:recipe.id,source:'cook',quantity:4,unit:'servings'},{name:ready.title,recipeId:ready.id,source:'ready',quantity:8,unit:'pieces'}]});
  const data=await request(page,'get',`/api/recipe-library?item_type=all&query=${suffix}`),household=await request(page,'get','/api/household');
  await mountMcp(page,{kind:'recipe_library',...data,household});
  const frame=page.frameLocator('iframe'),type=frame.getByRole('combobox',{name:'Library type'});
  await expect(frame.locator('.recipe-card')).toHaveCount(2); await expect(frame.locator('[data-saved-meal]')).toHaveCount(1);
  await type.selectOption('ready_food');await expect(frame.locator('.recipe-card')).toHaveCount(1);await expect(frame.locator('[data-saved-meal]')).toHaveCount(0);
  await type.selectOption('meals');await expect(frame.locator('[data-saved-meal]')).toHaveAttribute('data-saved-meal',meal.id);
  await frame.locator('[data-saved-meal]').getByRole('button',{name:ready.title,exact:true}).click();
  await expect(frame.locator('.recipe-detail')).toContainText('Heat for a minute');
  await frame.getByRole('button',{name:'← All recipes',exact:true}).click();
  await expect(type).toHaveValue('meals');await expect(frame.getByLabel('Search recipes',{exact:true})).toHaveValue(suffix);
  await frame.locator('[data-saved-meal]').getByRole('button',{name:recipe.title,exact:true}).click();
  await expect(frame.locator('.recipe-detail')).toContainText('Lentils');
  expect(await page.evaluate(()=>window.calls.filter(row=>row.name==='get_recipe').map(row=>row.arguments.recipe_id))).toEqual([ready.id,recipe.id]);
});
