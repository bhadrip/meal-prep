const { test, expect } = require('@playwright/test');

const content = (page) => page.locator('#app-content');
const editor = (page) => page.locator('#editor-dialog');
const unique = (prefix) => `${prefix} ${Date.now()}`;

async function open(page, view) {
  await page.goto('/app');
  await expect(page.locator('#mode-badge')).toHaveText('Demo data');
  await page.locator(`.sidebar [data-view="${view}"]`).click();
  await expect(page.locator('#view-title')).toHaveText({ overview: 'Overview', plan: 'Weekly plan', recipes: 'Recipes', pantry: 'Pantry', shopping: 'Shopping', reviews: 'Reviews', settings: 'Settings' }[view]);
}

async function choose(page, name, value) {
  const control = editor(page).locator(`input[type="hidden"][name="${name}"]`).locator('..');
  await control.locator('.choice-trigger').click();
  await control.locator(`[data-choice-value="${value}"]`).click();
  await expect(control.locator('input')).toHaveValue(value);
}

async function saveEditor(page) {
  await editor(page).locator('#dialog-save').click();
  await expect(editor(page)).toBeHidden();
  await expect(page.locator('#toast')).toContainText('Saved to your household.');
}

test('home loads only its three sections and defers the household dashboard', async ({ page }) => {
  const apiPaths = [];
  page.on('request', (request) => {
    const path = new URL(request.url()).pathname;
    if (path.startsWith('/api/')) apiPaths.push(path);
  });
  await page.goto('/app');
  await expect(content(page).locator('[data-home-section]')).toHaveCount(3);
  await expect(content(page).locator('.section-loading')).toHaveCount(0);
  expect(apiPaths.filter((path) => path === '/api/app/bootstrap')).toHaveLength(1);
  expect(apiPaths.filter((path) => path === '/api/app/snapshot')).toHaveLength(3);
  expect(apiPaths).not.toContain('/api/household/access');
  expect(apiPaths).not.toContain('/api/households');
  await page.locator('#household-dashboard summary').click();
  await expect(content(page).locator('[data-dashboard-card]')).toHaveCount(10);
  await expect(content(page).locator('[data-dashboard-card="recipes"]')).toContainText('Paneer');
});

test('navigation, sidebar, refresh, account, and mobile navigation', async ({ page }) => {
  await open(page, 'overview');
  for (const [view, title] of Object.entries({ plan: 'Weekly plan', recipes: 'Recipes', pantry: 'Pantry', shopping: 'Shopping', reviews: 'Reviews', settings: 'Settings', overview: 'Overview' })) {
    await page.locator(`.sidebar [data-view="${view}"]`).click();
    await expect(page.locator('#view-title')).toHaveText(title);
  }
  await page.getByRole('button', { name: 'Collapse sidebar' }).click();
  await expect(page.locator('.shell')).toHaveClass(/sidebar-collapsed/);
  await page.reload();
  await expect(page.locator('.shell')).toHaveClass(/sidebar-collapsed/);
  await page.getByRole('button', { name: 'Expand sidebar' }).click();
  await page.getByRole('button', { name: 'Refresh data' }).click();
  await expect(page.locator('#toast')).toContainText('Up to date.');
  await page.getByRole('button', { name: 'Account settings' }).click();
  await expect(page.locator('#view-title')).toHaveText('Settings');
  await page.setViewportSize({ width: 390, height: 844 });
  for (const [view, title] of Object.entries({ overview: 'Overview', plan: 'Weekly plan', recipes: 'Recipes', pantry: 'Pantry', shopping: 'Shopping' })) {
    await page.locator(`.mobile-nav [data-view="${view}"]`).click();
    await expect(page.locator('#view-title')).toHaveText(title);
  }
});

test('overview shortcuts and editor validation and cancel', async ({ page }) => {
  await open(page, 'overview');
  for (const [button, title] of [
    ['Open weekly plan', 'Weekly plan'], ['Open list', 'Shopping'], ['View pantry', 'Pantry'],
    ['Customize dashboard', 'Settings'], ['Browse recipes', 'Recipes'], ['View reviews', 'Reviews'],
  ]) {
    await page.locator('.sidebar [data-view="overview"]').click();
    await content(page).getByRole('button', { name: button }).click();
    await expect(page.locator('#view-title')).toHaveText(title);
  }
  await page.locator('.sidebar [data-view="pantry"]').click();
  const name = unique('Cancelled pantry item');
  await content(page).getByRole('button', { name: 'Add pantry item' }).click();
  await editor(page).locator('[name="name"]').fill(name);
  await editor(page).getByRole('button', { name: 'Cancel' }).click();
  await expect(editor(page)).toBeHidden();
  await expect(content(page)).not.toContainText(name);
  await page.locator('.sidebar [data-view="recipes"]').click();
  await content(page).getByRole('button', { name: 'Add recipe' }).click();
  await editor(page).locator('#dialog-save').click();
  await expect(editor(page)).toBeVisible();
  await expect(editor(page).locator('[name="title"]')).toBeFocused();
  await editor(page).getByRole('button', { name: 'Close' }).click();
  await expect(editor(page)).toBeHidden();
});

test('household setup, dashboard visibility, and card order persist', async ({ page }) => {
  await open(page, 'settings');
  const form = page.locator('#settings-form');
  await form.locator('[name="householdSize"]').fill('3');
  await form.locator('[name="weeknightMaxMinutes"]').fill('25');
  await form.locator('[name="dietaryRestrictions"]').fill('none');
  await form.locator('[name="stores"]').fill('Safeway, Costco');
  await form.locator('[name="leftoversForLunch"]').uncheck();
  await form.locator('[name="focusAreas"][value="dinners"]').check();
  await form.getByRole('button', { name: 'Save preferences' }).click();
  await expect(form.locator('[name="householdSize"]')).toHaveValue('3');
  await expect(form.locator('[name="stores"]')).toHaveValue('Safeway, Costco');
  await page.locator('.sidebar [data-view="overview"]').click();
  await page.locator('#household-dashboard summary').click();
  await expect(content(page)).toContainText('3 people');
  await expect(content(page)).toContainText('25 minutes maximum');
  await expect(content(page)).toContainText('No dietary restrictions recorded.');
  await page.locator('.sidebar [data-view="settings"]').click();
  await page.getByRole('button', { name: 'Move Food rules down' }).click();
  await expect(page.locator('#dashboard-form .card-order-row').first()).toContainText('Planning defaults');
  await page.getByRole('button', { name: 'Move Food rules up' }).click();
  await expect(page.locator('#dashboard-form .card-order-row').first()).toContainText('Food rules');
  await page.getByRole('button', { name: 'Move Food rules down' }).click();
  await page.locator('#dashboard-form [name="visibleCard"][value="pantry"]').uncheck();
  await page.getByRole('button', { name: 'Save dashboard' }).click();
  await expect(page.locator('#dashboard-form [name="visibleCard"][value="pantry"]')).not.toBeChecked();
  await page.locator('.sidebar [data-view="overview"]').click();
  await expect(content(page).locator('[data-dashboard-card]').first()).toHaveAttribute('data-dashboard-card', 'planning-defaults');
  await expect(content(page).locator('[data-dashboard-card="pantry"]')).toHaveCount(0);
  await page.reload();
  await page.locator('#household-dashboard summary').click();
  await expect(content(page).locator('[data-dashboard-card]').first()).toHaveAttribute('data-dashboard-card', 'planning-defaults');
  await expect(content(page).locator('[data-dashboard-card="pantry"]')).toHaveCount(0);
  await page.locator('.sidebar [data-view="settings"]').click();
  await expect(page.locator('#dashboard-form .card-order-row').first()).toContainText('Planning defaults');
  await expect(page.locator('#dashboard-form [name="visibleCard"][value="pantry"]')).not.toBeChecked();
});

test('planned meals can be added and edited with compact actions', async ({ page }) => {
  await open(page, 'plan');
  const week = await page.locator('#week-picker').inputValue();
  const originalMondayMeals = await content(page).locator('.day-card').first().locator('.meal strong').allTextContents();
  await expect(content(page).getByRole('button', { name: 'Edit weekly rhythm' })).toHaveCount(0);
  const meal = unique('Playwright dinner');
  await content(page).getByRole('button', { name: 'Add meal', exact: true }).click();
  await editor(page).getByRole('button', { name: 'Advanced meal details' }).click();
  await editor(page).locator('[name="date"]').fill(week);
  await editor(page).locator('[name="meal"]').fill(meal);
  await choose(page, 'slot', 'dinner');
  await editor(page).locator('[name="notes"]').fill('Test note');
  await saveEditor(page);
  const mealRow = content(page).locator('.meal').filter({ hasText: meal });
  await expect(mealRow).toBeVisible();
  await mealRow.getByRole('button', { name: 'Edit' }).click();
  await editor(page).locator('[name="meal"]').fill(`${meal} edited`);
  await saveEditor(page);
  const updated = content(page).locator('.meal').filter({ hasText: `${meal} edited` });
  await expect(updated).toBeVisible();
  await expect(updated.getByRole('button', { name: 'Remove', exact:true })).toHaveCount(0);
  await expect(updated.getByRole('button', { name: 'Record eaten', exact:true })).toHaveCount(0);
  await expect(updated).not.toContainText('Test note');
  for (const originalMeal of originalMondayMeals) {
    await expect(content(page).locator('.day-card').first()).toContainText(originalMeal);
  }
  await page.locator('#week-picker').fill('2027-01-04');
  await expect(page.locator('#week-picker')).toHaveValue('2027-01-04');
  await expect(content(page).locator('.day-card')).toHaveCount(7);
});

test('an empty week can be planned from its day card without losing the previous week', async ({ page }) => {
  await open(page, 'plan');
  const firstWeek = await page.locator('#week-picker').inputValue();
  const firstWeekMeal = await content(page).locator('.meal strong').first().textContent();
  const nextMonday = new Date(`${firstWeek}T12:00:00`);
  nextMonday.setDate(nextMonday.getDate() + 7);
  const nextWeek = `${nextMonday.getFullYear()}-${String(nextMonday.getMonth() + 1).padStart(2, '0')}-${String(nextMonday.getDate()).padStart(2, '0')}`;
  await page.setViewportSize({ width: 390, height: 844 });
  await page.locator('#week-picker').fill(nextWeek);
  await expect(content(page)).toContainText('This week is open');
  const mondayCard = content(page).locator('.day-card').filter({ has: page.locator('b', { hasText: 'Monday' }) });
  await expect(mondayCard.getByRole('button', { name: 'Add meal to Monday' })).toBeVisible({ timeout: 1500 });
  await mondayCard.getByRole('button', { name: 'Add meal to Monday' }).click();
  await editor(page).getByRole('button', { name: 'Advanced meal details' }).click();
  await expect(editor(page).locator('[name="date"]')).toHaveValue(nextWeek);
  const meal = unique('Next week dinner');
  await editor(page).locator('[name="meal"]').fill(meal);
  await saveEditor(page);
  await expect(content(page).locator('.day-card').first()).toContainText(meal);
  await page.locator('#week-picker').fill(firstWeek);
  await expect(content(page)).toContainText(firstWeekMeal);
  await page.locator('#week-picker').fill(nextWeek);
  await expect(content(page)).toContainText(meal);
});

test('day form supports recipe components and guards the selected week', async ({ page }) => {
  await open(page, 'plan');
  const week = await page.locator('#week-picker').inputValue();
  const thursday = new Date(`${week}T12:00:00`);
  thursday.setDate(thursday.getDate() + 3);
  const selectedDate = `${thursday.getFullYear()}-${String(thursday.getMonth() + 1).padStart(2, '0')}-${String(thursday.getDate()).padStart(2, '0')}`;
  await page.setViewportSize({ width: 320, height: 720 });
  await content(page).getByRole('button', { name: 'Add meal to Thursday' }).click();
  await editor(page).getByRole('button', { name: 'Advanced meal details' }).click();
  await expect(editor(page).locator('[name="date"]')).toHaveValue(selectedDate);
  await choose(page, 'slot', 'dinner');
  const component = editor(page).locator('.component-row');
  await component.getByLabel('Food or dish').fill('Paneer rice bowls');
  const source = component.locator('input[name$="-source"]').locator('..');
  await source.locator('.choice-trigger').click();
  await source.locator('[data-choice-value="cook"]').click();
  const recipe = component.locator('input[name$="-recipeId"]').locator('..');
  await recipe.locator('.choice-trigger').click();
  await recipe.locator('[data-choice-value="11111111-1111-1111-1111-111111111111"]').click();
  const meal = unique('Prep rice');
  await editor(page).locator('[name="meal"]').fill(meal);
  await saveEditor(page);
  const row = content(page).locator('.meal').filter({ hasText: meal });
  await expect(row).toContainText('Dinner');
  await expect(row).toContainText('Paneer rice bowls');
  await row.getByRole('button', { name: 'Edit' }).click();
  const outside = new Date(`${week}T12:00:00`);
  outside.setDate(outside.getDate() + 7);
  await editor(page).locator('[name="date"]').fill(`${outside.getFullYear()}-${String(outside.getMonth() + 1).padStart(2, '0')}-${String(outside.getDate()).padStart(2, '0')}`);
  await editor(page).locator('#dialog-save').click();
  await expect(editor(page).locator('#dialog-error')).toContainText('selected week');
  await editor(page).getByRole('button', { name: 'Cancel' }).click();
  await expect(row).toBeVisible();
});

test('recipe create, search, edit, share, copy, public save, revoke, and archive', async ({ page }) => {
  await open(page, 'recipes');
  const title = unique('Playwright soup');
  await content(page).getByRole('button', { name: 'Add recipe' }).click();
  await editor(page).locator('[name="title"]').fill(title);
  await editor(page).locator('[name="description"]').fill('A browser tested recipe');
  await editor(page).locator('[name="ingredients"]').fill('Lentils | 2 | cups');
  await editor(page).locator('[name="instructions"]').fill('Rinse lentils\nSimmer until tender');
  await saveEditor(page);
  const originalId = await content(page).locator('[data-action="edit-recipe"]').getAttribute('data-id');
  await expect(content(page)).toContainText('Lentils');
  await expect(content(page)).toContainText('Simmer until tender');
  await content(page).getByRole('button', { name: 'Edit recipe' }).click();
  await editor(page).locator('[name="description"]').fill('Updated browser tested recipe');
  await saveEditor(page);
  await expect(content(page)).toContainText('Updated browser tested recipe');
  await content(page).getByRole('button', { name: 'Create share link' }).click();
  await expect(page.getByLabel('Review public recipe')).toContainText('Updated browser tested recipe');
  await expect(page.getByRole('textbox', { name: 'New recipe share link' })).toHaveCount(0);
  await page.getByLabel('Review public recipe').getByRole('button', {name: 'Cancel'}).click();
  await expect(page.getByLabel('Review public recipe')).toHaveCount(0);
  await content(page).getByRole('button', { name: 'Create share link' }).click();
  await page.getByRole('button', {name: 'Confirm public link'}).click();
  const shareUrl = await page.getByRole('textbox', { name: 'New recipe share link' }).inputValue();
  expect(shareUrl).toContain('/s/');
  await content(page).getByRole('button', { name: 'Copy link' }).click();
  await page.goto(shareUrl);
  await expect(page.getByRole('heading', { name: title })).toBeVisible();
  await page.locator('#save-recipe').click();
  await expect(page.locator('#message')).toHaveText('Saved to your household recipes.');
  await page.goto('/app');
  await page.locator('.sidebar [data-view="recipes"]').click();
  await page.locator('#recipe-search').fill(title);
  await expect(content(page).locator('.recipe-card')).toHaveCount(2);
  await page.locator('#recipe-search').fill('No such recipe in this household');
  await expect(content(page)).toContainText('No matches');
  await page.locator('#recipe-search').fill('');
  await content(page).locator(`[data-action="open-recipe"][data-id="${originalId}"]`).click();
  await content(page).getByRole('button', { name: 'Revoke' }).click();
  await expect(page.getByRole('textbox', { name: 'New recipe share link' })).toHaveCount(0);
  await page.goto(shareUrl);
  await expect(page.getByText('Not Found')).toBeVisible();
  await page.goto('/app');
  await page.locator('.sidebar [data-view="recipes"]').click();
  await content(page).locator(`[data-action="open-recipe"][data-id="${originalId}"]`).click();
  await expect(content(page).locator('.hero h2')).toHaveText(title);
  page.once('dialog', (dialog) => dialog.accept());
  await content(page).getByRole('button', { name: 'Archive' }).click();
  await expect(content(page).locator(`[data-action="open-recipe"][data-id="${originalId}"]`)).toHaveCount(0);
});

test('recipe tags can be saved, searched, and opened as exact filters', async ({ page }) => {
  for (let index = 0; index < 26; index += 1) {
    const response = await page.request.put('/api/recipes', { data: { title: unique(`Filler recipe ${index}`) } });
    expect(response.ok()).toBe(true);
  }
  await open(page, 'recipes');
  const tag = `sickness-friendly-${Date.now()}`;
  const soup = unique('Recovery soup');
  const dinner = unique('Guest dinner');
  for (const [title, tags] of [[soup, `${tag}, comfort`], [dinner, 'guest-friendly']]) {
    await content(page).getByRole('button', { name: 'Add recipe' }).click();
    await editor(page).locator('[name="title"]').fill(title);
    await editor(page).locator('[name="tags"]').fill(tags);
    await saveEditor(page);
    await content(page).getByRole('button', { name: '← All recipes' }).click();
  }
  const partialTag = tag.slice(0, -1);
  const searchResponse = page.waitForResponse((response) => response.url().includes('/api/recipe-library?') && new URL(response.url()).searchParams.get('query') === partialTag);
  await page.locator('#recipe-search').fill(partialTag);
  await expect(content(page).getByRole('group', { name: 'Suggested recipe tags' }).getByRole('button', { name: new RegExp(tag) })).toBeVisible();
  await searchResponse;
  await expect(content(page).locator('.recipe-card')).toHaveCount(1);
  await expect(content(page).locator('.recipe-card')).toContainText(soup);
  await content(page).getByRole('group', { name: 'Suggested recipe tags' }).getByRole('button', { name: new RegExp(tag) }).click();
  await expect(content(page).locator('.recipe-card')).toHaveCount(1);
  await expect(content(page).locator('.recipe-card')).toContainText(soup);
  await expect(content(page).locator('.recipe-card')).not.toContainText(dinner);
  await content(page).getByRole('button', { name: 'Clear tag' }).click();
  await page.locator('#recipe-search').fill('');
  await expect(content(page).locator('#recipe-results')).toHaveAttribute('aria-busy', 'false');
  await content(page).getByRole('button', {name: 'Tags', exact: true}).click();
  await page.getByRole('searchbox', { name: 'Find a recipe tag' }).fill('guest');
  await content(page).getByRole('group', { name: 'Recipe tag filters' }).getByRole('button', { name: /guest-friendly/ }).click();
  await expect(content(page).locator('.recipe-card').filter({ hasText: dinner })).toHaveCount(1);
  await content(page).getByRole('button', { name: 'Clear tag' }).click();
  await expect(content(page).locator('#recipe-results')).toHaveAttribute('aria-busy', 'false');
  await page.getByRole('searchbox', { name: 'Find a recipe tag' }).fill(`imagined-${Date.now()}`);
  await expect(content(page)).toContainText('No matching saved tags.');
  await expect(content(page).getByRole('group', { name: 'Recipe tag filters' }).getByRole('button', { name: /imagined/ })).toHaveCount(0);
});

test('recipe feedback appears in the open detail without leaving the page', async ({ page }) => {
  await open(page, 'recipes');
  await page.locator('#recipe-search').fill('Paneer');
  await content(page).locator('[data-action="open-recipe"][data-id="11111111-1111-1111-1111-111111111111"]').click();
  const note = unique('Fresh recipe feedback');
  await content(page).getByRole('button', { name: 'Add feedback' }).click();
  await editor(page).locator('[name="note"]').fill(note);
  await saveEditor(page);
  await expect(content(page)).toContainText(note);
  await content(page).getByRole('button', { name: '← All recipes' }).click();
  await expect(page.locator('#recipe-search')).toBeVisible();
});

test('pantry item can be added and edited', async ({ page }) => {
  await open(page, 'pantry');
  const name = unique('Playwright oats');
  await content(page).getByRole('button', { name: 'Add pantry item' }).click();
  await editor(page).locator('[name="name"]').fill(name);
  await editor(page).locator('[name="quantity"]').fill('2');
  await editor(page).locator('[name="unit"]').fill('bags');
  await choose(page, 'storageLocation', 'freezer');
  await choose(page, 'quantityConfidence', 'exact');
  await editor(page).locator('[name="useByDate"]').fill('2027-12-31');
  await saveEditor(page);
  const row = content(page).locator('.table-row').filter({ hasText: name });
  await expect(row).toContainText('Freezer');
  await expect(row).toContainText('2027-12-31');
  await row.getByRole('button', { name: 'Edit' }).click();
  await editor(page).locator('[name="quantity"]').fill('3');
  await saveEditor(page);
  await expect(content(page).locator('.table-row').filter({ hasText: name })).toContainText('3 bags');
});

test('pantry categories and search narrow items and save corrections', async ({ page }) => {
  await open(page, 'pantry');
  const chili = unique('Chili oil');
  const mystery = unique('Mystery tin');
  for (const name of [chili, mystery]) {
    await content(page).getByRole('button', { name: 'Add pantry item' }).click();
    await editor(page).locator('[name="name"]').fill(name);
    await saveEditor(page);
  }
  await content(page).locator('[data-pantry-category="condiments"]').click();
  await expect(content(page).locator('.table-row').filter({ hasText: chili })).toBeVisible();
  await expect(content(page).locator('.table-row').filter({ hasText: mystery })).toHaveCount(0);
  await content(page).locator('[data-pantry-category="uncategorized"]').click();
  await expect(content(page).locator('.table-row').filter({ hasText: mystery })).toBeVisible();
  await content(page).locator('.table-row').filter({ hasText: mystery }).getByRole('button', { name: 'Edit' }).click();
  await choose(page, 'category', 'snacks');
  await saveEditor(page);
  await expect(content(page).locator('.table-row').filter({ hasText: mystery })).toHaveCount(0);
  await content(page).locator('[data-pantry-category="snacks"]').click();
  await expect(content(page).locator('.table-row').filter({ hasText: mystery })).toBeVisible();
  await content(page).locator('#pantry-search').fill('no match');
  await expect(content(page).locator('.table-row').filter({ hasText: mystery })).toHaveCount(0);
  await content(page).locator('#pantry-search').fill('Mystery tin');
  await expect(content(page).locator('.table-row').filter({ hasText: mystery })).toBeVisible();
  await content(page).locator('[data-pantry-category="all"]').click();
  await expect(content(page).locator('.table-row').filter({ hasText: chili })).toHaveCount(0);
  await content(page).locator('#pantry-search').fill('');
  await expect(content(page).locator('.table-row').filter({ hasText: chili })).toBeVisible();
  await page.reload();
  await page.locator('.sidebar [data-view="pantry"]').click();
  await content(page).locator('[data-pantry-category="snacks"]').click();
  await expect(content(page).locator('.table-row').filter({ hasText: mystery })).toBeVisible();
});

test('pantry photo history opens inline, retries, and pages saved uploads', async ({ page }) => {
  const requests = [];
  let firstAttempt = true;
  await page.route('**/api/pantry/evidence?*', async (route) => {
    const offset = Number(new URL(route.request().url()).searchParams.get('offset'));
    requests.push(offset);
    if (firstAttempt) {
      firstAttempt = false;
      await route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ detail: 'Photos are temporarily unavailable.' }) });
      return;
    }
    const photo = offset === 0
      ? { id: 'photo-1', created_at: '2026-09-30T12:00:00Z', image_url: 'https://example.test/pantry-photo.webp', image_bytes: 4096, status: 'applied', note: 'Fridge shelf', observations: [{ name: 'Milk', quantity: 1, unit: 'carton' }] }
      : { id: 'photo-2', created_at: '2026-09-29T12:00:00Z', image_url: null, image_bytes: 2048, status: 'captured', note: 'Pantry shelf', observations: [{ name: 'Rice', quantity: 2, unit: 'bags' }] };
    await route.fulfill({ contentType: 'application/json', body: JSON.stringify({ items: [photo], count: 1, hasMore: offset === 0, nextOffset: offset + 1 }) });
  });
  await page.route('https://example.test/pantry-photo.webp', (route) => route.fulfill({
    contentType: 'image/png',
    body: Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVQIHWP4z8DwHwAFgAI/ScLxSQAAAABJRU5ErkJggg==', 'base64'),
  }));
  await open(page, 'pantry');
  await expect(content(page).locator('.pantry-sections')).toHaveCount(0);
  await expect(content(page).getByRole('button', { name: 'Photo history' })).toBeVisible();
  await expect(content(page).locator('#pantry-photo-panel')).toHaveCount(0);
  await content(page).getByRole('button', { name: 'Photo history' }).click();
  await expect(content(page).getByRole('button', { name: 'Add pantry item' })).toBeVisible();
  await expect(content(page).getByRole('group', { name: 'Pantry categories' })).toBeVisible();
  await expect(content(page).getByRole('alert')).toContainText('Photos are temporarily unavailable.');
  await content(page).getByRole('button', { name: 'Try again' }).click();
  await expect(content(page).locator('.pantry-photo-card')).toHaveCount(1);
  await expect(content(page).locator('.pantry-photo-card').first()).toContainText('Milk — 1 carton');
  await expect(content(page).locator('.pantry-photo-card').first()).toContainText('Added to pantry');
  await expect(content(page).locator('.pantry-photo-card img')).toHaveJSProperty('naturalWidth', 1);
  await expect(content(page).getByRole('button', { name: 'Add pantry item' })).toBeVisible();
  await content(page).getByRole('button', { name: 'Load older photos' }).click();
  await expect(content(page).locator('.pantry-photo-card')).toHaveCount(2);
  await expect(content(page).locator('.pantry-photo-card').last()).toContainText('Rice — 2 bags');
  await expect(content(page).locator('.pantry-photo-card').last()).toContainText('Saved for review');
  expect(requests).toEqual([0, 0, 1]);
  await page.reload();
  await expect(content(page).locator('.pantry-photo-card')).toHaveCount(1);
  await expect(content(page).locator('.pantry-photo-card').first()).toContainText('Milk — 1 carton');
  await content(page).getByRole('button', { name: 'Hide photo history' }).click();
  await expect(content(page).locator('#pantry-photo-panel')).toHaveCount(0);
  await expect(content(page).getByRole('button', { name: 'Add pantry item' })).toBeVisible();
});

test('empty photo history stays a small disclosure within Pantry', async ({ page }) => {
  await page.route('**/api/pantry/evidence?*', (route) => route.fulfill({
    contentType: 'application/json',
    body: JSON.stringify({ items: [], count: 0, hasMore: false, nextOffset: 0 }),
  }));
  await open(page, 'pantry');
  await expect(content(page).getByText('No photos have been saved yet.')).toHaveCount(0);
  await content(page).getByRole('button', { name: 'Photo history' }).click();
  await expect(content(page).getByText(/No photos have been saved yet/)).toBeVisible();
  await expect(content(page).locator('.table-card .table-row').first()).toBeVisible();
  await content(page).getByRole('button', { name: 'Hide photo history' }).click();
  await expect(content(page).getByText(/No photos have been saved yet/)).toHaveCount(0);
  await expect(content(page).locator('.table-card .table-row').first()).toBeVisible();
});

test('pantry use records a meal and shows the remaining quantity', async ({ page }) => {
  await open(page, 'pantry');
  const name = unique('Playwright rice');
  await content(page).getByRole('button', { name: 'Add pantry item' }).click();
  await editor(page).locator('[name="name"]').fill(name);
  await editor(page).locator('[name="quantity"]').fill('4');
  await editor(page).locator('[name="unit"]').fill('cups');
  await saveEditor(page);
  await content(page).locator('.table-row').filter({ hasText: name }).getByRole('button', { name: 'Use', exact: true }).click();
  await expect(editor(page).locator('#dialog-save')).toHaveText('Record use');
  await editor(page).locator('[name="quantity"]').fill('1');
  await choose(page, 'recipeId', '11111111-1111-1111-1111-111111111111');
  await editor(page).locator('[name="mealTitle"]').fill('Tuesday dinner');
  const useRequest = page.waitForRequest((request) => request.url().endsWith('/api/pantry/use') && request.method() === 'POST');
  await editor(page).locator('#dialog-save').click();
  const request = await useRequest;
  expect(request.postDataJSON()).toMatchObject({ quantity: 1, recipeId: '11111111-1111-1111-1111-111111111111', mealTitle: 'Tuesday dinner' });
  await expect(editor(page)).toBeHidden();
  const remaining = content(page).locator('.table-row').filter({ hasText: name });
  await expect(remaining).toContainText('3 cups left');
  await expect(remaining.getByRole('meter')).toHaveAttribute('aria-valuenow', '75');
});

test('shopping item can be added, purchased, edited, and removed', async ({ page }) => {
  await open(page, 'shopping');
  const name = unique('Playwright apples');
  await content(page).getByRole('button', { name: 'Add item' }).click();
  await editor(page).locator('[name="name"]').fill(name);
  await editor(page).locator('[name="quantity"]').fill('4');
  await editor(page).locator('[name="unit"]').fill('each');
  await editor(page).locator('[name="store"]').fill('Safeway');
  await saveEditor(page);
  let row = content(page).locator('.check-row').filter({ hasText: name });
  await expect(row).toContainText('4 each');
  await row.getByRole('checkbox').check();
  row = content(page).locator('.check-row').filter({ hasText: name });
  await expect(row.getByRole('checkbox')).toBeChecked();
  await row.getByRole('button', { name: 'Edit' }).click();
  await editor(page).locator('[name="quantity"]').fill('5');
  await editor(page).locator('[name="listName"]').fill('Browser groceries');
  await saveEditor(page);
  await expect(content(page)).toContainText('Browser groceries');
  row = content(page).locator('.check-row').filter({ hasText: name });
  await expect(row).toContainText('5 each');
  await row.getByRole('checkbox').uncheck();
  row = content(page).locator('.check-row').filter({ hasText: name });
  await expect(row.getByRole('checkbox')).not.toBeChecked();
  page.once('dialog', (dialog) => dialog.accept());
  await row.getByRole('button', { name: 'Remove' }).click();
  await expect(content(page).locator('.check-row').filter({ hasText: name })).toHaveCount(0);
});

test('weekly and meal reviews plus household memory lifecycle', async ({ page }) => {
  await open(page, 'reviews');
  const weekNote = unique('Playwright week review');
  await content(page).getByRole('button', { name: 'Review this week' }).click();
  await choose(page, 'feedbackType', 'worked_well');
  await editor(page).locator('[name="note"]').fill(weekNote);
  await editor(page).locator('[name="nextTime"]').fill('Keep the prep time');
  await saveEditor(page);
  await expect(content(page)).toContainText(weekNote);
  await expect(content(page)).toContainText('Keep the prep time');
  const note = unique('Playwright meal note');
  await content(page).getByRole('button', { name: 'Review a meal' }).click();
  await choose(page, 'feedbackType', 'change_next_time');
  await editor(page).locator('[name="note"]').fill(note);
  await editor(page).locator('[name="nextTime"]').fill('Use less salt');
  await editor(page).locator('[name="rating"]').fill('4');
  await saveEditor(page);
  await expect(content(page)).toContainText(note);
  await expect(content(page)).toContainText('Use less salt');
  const memory = unique('Playwright memory');
  await content(page).getByRole('button', { name: 'Add memory' }).click();
  await editor(page).locator('[name="content"]').fill(memory);
  await choose(page, 'scope', 'this_week');
  await saveEditor(page);
  let row = content(page).locator('.row').filter({ hasText: memory });
  await expect(row).toContainText('Suggested');
  await row.getByRole('button', { name: 'Confirm' }).click();
  row = content(page).locator('.row').filter({ hasText: memory });
  await expect(row).toContainText('Confirmed');
  await row.getByRole('button', { name: 'Edit' }).click();
  await editor(page).locator('[name="content"]').fill(`${memory} updated`);
  await saveEditor(page);
  row = content(page).locator('.row').filter({ hasText: `${memory} updated` });
  await row.getByRole('button', { name: 'Edit' }).click();
  await choose(page, 'action', 'forget');
  await saveEditor(page);
  await expect(content(page).locator('.row').filter({ hasText: `${memory} updated` })).toHaveCount(0);
});

test('login page explains local demo mode', async ({ page }) => {
  await page.goto('/login');
  await expect(page.locator('#message')).toContainText('demo mode');
  await expect(page.locator('#login-form')).toBeHidden();
  await page.getByRole('link', { name: 'Meal Prep' }).click();
  await expect(page.getByRole('heading', { name: 'Your food week, all together.' })).toBeVisible();
  await page.getByRole('link', { name: 'Open the app' }).first().click();
  await expect(page.locator('#view-title')).toHaveText('Overview');
});

test('sign-in code, email change, error, and sign-out UI with a mocked auth provider', async ({ page }) => {
  await page.route('**/api/auth/config', (route) => route.fulfill({ json: {
    supabaseUrl: 'https://example.supabase.co', supabaseAnonKey: 'public-test-key', authRequired: true,
  } }));
  await page.route('**/static/vendor/supabase.js', (route) => route.fulfill({
    contentType: 'application/javascript',
    body: `window.supabase = { createClient: () => ({ auth: {
      getSession: async () => ({ data: { session: JSON.parse(sessionStorage.getItem('mock-session') || 'null') }, error: null }),
      onAuthStateChange: () => ({ data: { subscription: { unsubscribe() {} } } }),
      signInWithOtp: async ({ email }) => email.startsWith('bad') ? { error: { message: 'Email is not approved' } } : { error: null },
      verifyOtp: async ({ email, token }) => {
        if (token !== '12345678') return { data: {}, error: { message: 'Invalid code' } };
        const session = { access_token: 'fake-token', user: { email } };
        sessionStorage.setItem('mock-session', JSON.stringify(session));
        return { data: { session }, error: null };
      },
      signOut: async () => { sessionStorage.removeItem('mock-session'); return { error: null }; },
    } }) };`,
  }));
  await page.goto('/login?next=%2Fapp');
  await page.locator('#email').fill('bad@example.com');
  await page.getByRole('button', { name: 'Send code' }).click();
  await expect(page.locator('#message')).toHaveText('Email is not approved');
  await page.locator('#email').fill('first@example.com');
  await page.getByRole('button', { name: 'Send code' }).click();
  await expect(page.locator('#code-email')).toHaveText('first@example.com');
  await page.getByRole('button', { name: 'Use another email' }).click();
  await page.locator('#email').fill('second@example.com');
  await page.getByRole('button', { name: 'Send code' }).click();
  await page.locator('#code').fill('00000000');
  await page.getByRole('button', { name: 'Verify code' }).click();
  await expect(page.locator('#message')).toHaveText('Invalid code');
  await page.locator('#code').fill('12345678');
  await page.getByRole('button', { name: 'Verify code' }).click();
  await expect(page.locator('#account-label')).toHaveText('second@example.com');
  await page.getByRole('button', { name: 'Account settings' }).click();
  await page.getByRole('button', { name: 'Sign out' }).click();
  await expect(page).toHaveURL(/\/login\?next=/);
  await expect(page.locator('#login-form')).toBeVisible();
});

test.describe('pantry dates in a UTC browser', () => {
  test.use({ timezoneId: 'UTC' });

  test('pantry freshness review, aligned columns, and inline remaining work on desktop and mobile', async ({ page }) => {
    await open(page, 'pantry');
    const name = unique('Mushrooms');
    const today = new Intl.DateTimeFormat('en-CA', { timeZone: 'America/Los_Angeles', year: 'numeric', month: '2-digit', day: '2-digit' }).format(new Date());
    const purchased = new Date(`${today}T12:00:00Z`);
    purchased.setUTCDate(purchased.getUTCDate() - 7);
    const purchaseDate = purchased.toISOString().slice(0, 10);
    await content(page).getByRole('button', { name: 'Add pantry item' }).click();
    await editor(page).locator('[name="name"]').fill(name);
    await editor(page).locator('[name="quantity"]').fill('2');
    await editor(page).locator('[name="unit"]').fill('boxes');
    await editor(page).locator('[name="acquiredAt"]').fill(purchaseDate);
    await choose(page, 'storageLocation', 'fridge');
    await saveEditor(page);
    const row = content(page).locator('.table-row').filter({ hasText: name });
    await expect(row).toContainText('Purchased 7 days ago');
    await expect(row).toContainText('Review first');
    await page.locator('.sidebar [data-view=overview]').click();
    const attention = content(page).locator('[data-home-section=pantry]');
    await expect(attention).toContainText(name);
    await attention.locator('.row').filter({ hasText: name }).getByRole('button', { name: 'Review' }).click();
    await expect(editor(page).locator('[name=acquiredAt]')).toHaveValue(purchaseDate);
    await editor(page).getByRole('button', { name: 'Cancel', exact: true }).click();
    await page.locator('.sidebar [data-view=pantry]').click();
    await content(page).getByRole('button', { name: /Review produce & dates/ }).click();
    await expect(row).toBeVisible();
    await content(page).getByRole('button', { name: /Review produce & dates/ }).click();
    const positions = await row.evaluate((element) => [...element.children].map((cell) => cell.getBoundingClientRect().x));
    const headers = await content(page).locator('.pantry-table .header').evaluate((element) => [...element.children].map((cell) => cell.getBoundingClientRect().x));
    positions.forEach((x, index) => expect(Math.abs(x - headers[index])).toBeLessThan(1));
    const allPositions = await content(page).locator('.pantry-table .table-row:not(.header)').evaluateAll((elements) => elements.map((element) => [...element.children].map((cell) => cell.getBoundingClientRect().x)));
    allPositions.forEach((cells) => cells.forEach((x, index) => expect(Math.abs(x - headers[index])).toBeLessThan(1)));
    await page.setViewportSize({ width: 820, height: 1000 });
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy();
    await page.setViewportSize({ width: 1280, height: 720 });
    await row.getByRole('button', { name: 'Used half', exact: true }).click();
    await expect(row).toContainText('1 boxes left');
    await expect(row.getByRole('meter')).toHaveAttribute('aria-valuenow', '50');
    await row.getByRole('button', { name: `Update remaining ${name}` }).click();
    await row.getByRole('spinbutton', { name: `Remaining ${name}` }).fill('0.25');
    await row.getByRole('button', { name: 'Save amount' }).click();
    await expect(row).toContainText('0.25 boxes left');
    await expect(row).toContainText('Purchased 7 days ago');
    await row.getByRole('button', { name: `Update remaining ${name}` }).click();
    await row.getByRole('spinbutton', { name: `Remaining ${name}` }).fill('-1');
    await row.getByRole('button', { name: 'Save amount' }).click();
    await expect(row.locator('.pantry-inline-form')).toBeVisible();
    await row.getByRole('button', { name: 'Cancel', exact: true }).click();
    await page.reload();
    await expect(row).toContainText('0.25 boxes left');
    await page.setViewportSize({ width: 390, height: 844 });
    await expect(row.locator('.pantry-freshness')).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy();
    await page.screenshot({ path: 'test-results/pantry-mobile.png', fullPage: true });
    await row.getByRole('button', { name: 'Finished', exact: true }).click();
    await expect(row).toHaveCount(0);
    await content(page).getByRole('button', { name: /^Finished \d/ }).click();
    await expect(row).toContainText('0 boxes left');
    await content(page).getByRole('button', { name: /Review produce & dates/ }).click();
    await expect(row).toHaveCount(0);
    await content(page).getByRole('button', { name: /Review produce & dates/ }).click();
    await row.getByRole('button', { name: 'Restock', exact: true }).click();
    await expect(editor(page).locator('[name=acquiredAt]')).toHaveValue(today);
    await editor(page).locator('[name=quantity]').fill('3');
    await saveEditor(page);
    await expect(row).toHaveCount(0);
    await content(page).getByRole('button', { name: /^On hand/ }).click();
    await expect(row).toContainText('3 boxes left');
    await expect(row).toContainText('Purchased today');
    await expect(row.getByRole('meter')).toHaveAttribute('aria-valuenow', '100');
    await page.reload();
    await expect(row).toContainText('3 boxes left');
    await page.setViewportSize({ width: 1440, height: 1000 });
    await page.screenshot({ path: 'test-results/pantry-desktop.png', fullPage: true });
  });
});

test('unknown pantry quantity can be set inline and failed saves retain input', async ({ page }) => {
  await open(page, 'pantry');
  const name = unique('Spinach');
  await content(page).getByRole('button', { name: 'Add pantry item' }).click();
  await editor(page).locator('[name="name"]').fill(name);
  await saveEditor(page);
  const row = content(page).locator('.table-row').filter({ hasText: name });
  await row.getByRole('button', { name: 'Add purchase date' }).click();
  await editor(page).locator('[name="acquiredAt"]').fill('2020-01-01');
  await saveEditor(page);
  await expect(row).toContainText('Review first');
  await row.getByRole('button', { name: `Update remaining ${name}` }).click();
  await row.getByRole('spinbutton').fill('1.5');
  await row.getByRole('textbox').fill('bags');
  await page.route('**/api/pantry', (route) => route.request().method() === 'PUT' ? route.fulfill({ status: 503, json: { detail: 'Try again later' } }) : route.continue());
  await row.getByRole('button', { name: 'Save amount' }).click();
  await expect(page.locator('#toast')).toContainText('Try again later');
  await expect(row.getByRole('spinbutton')).toHaveValue('1.5');
  await page.unroute('**/api/pantry');
  await row.getByRole('button', { name: 'Save amount' }).click();
  await expect(row).toContainText('1.5 bags left');
  await page.reload();
  await expect(row).toContainText('1.5 bags left');
});
