const { test, expect } = require('@playwright/test');

test.use({ timezoneId: 'America/Los_Angeles' });
const home = (page, name) => page.locator(`[data-home-section="${name}"]`);
const snapshotRoute = '**/api/app/snapshot?*';
const freezeToday = (page) => page.clock.setFixedTime(new Date('2026-10-01T12:00:00-07:00'));

test('meals render while pantry and notifications wait, and recipes load on navigation', async ({ page }) => {
  await freezeToday(page);
  let release;
  const delayed = new Promise((resolve) => { release = resolve; });
  const names = [];
  await page.route('**/api/notifications', async (route) => {
    await delayed;
    await route.fulfill({ json: { items: [] } });
  });
  await page.route(snapshotRoute, async (route) => {
    const name = new URL(route.request().url()).searchParams.get('sections');
    names.push(name);
    const response = await route.fetch();
    const data = await response.json();
    if (name === 'pantry') await delayed;
    if (name === 'mealPlan') data.sections.mealPlan = { status: 'ready', value: {
      weekStart: '2026-09-28', entries: [
        { id: 'today', date: '2026-10-01', slot: 'dinner', meal: 'Thursday lentil soup' },
        { id: 'old', date: '2026-09-28', slot: 'dinner', meal: 'Old Monday dinner' },
      ],
    } };
    await route.fulfill({ json: data });
  });
  try {
    await page.goto('/app');
    await expect(home(page, 'mealPlan')).toContainText('Thursday lentil soup');
    await expect(home(page, 'mealPlan')).not.toContainText('Old Monday dinner');
    await expect(home(page, 'pantry')).toContainText('Loading pantry');
    await expect(home(page, 'shoppingList').locator('.section-loading')).toHaveCount(0);
    expect(names.sort()).toEqual(['mealPlan', 'pantry', 'shoppingList']);
    await page.getByRole('button', { name: 'Browse recipes', exact: true }).click();
    await expect(page.locator('.recipe-card')).not.toHaveCount(0);
    await page.locator('.recipe-card').first().getByRole('button', { name: /^Open / }).click();
    await expect(page.getByRole('heading', { name: 'Recipe details' })).toBeVisible();
    expect(names).toContain('recipes');
    expect(names).not.toContain('feedback');
    expect(names).not.toContain('memories');
  } finally { release(); }
});

test('the actionable homepage fits desktop and mobile and opens today’s weekly plan', async ({ page }) => {
  await freezeToday(page);
  await page.setViewportSize({ width: 1360, height: 950 });
  await page.route(snapshotRoute, async (route) => {
    const name = new URL(route.request().url()).searchParams.get('sections');
    const data = await (await route.fetch()).json();
    const fixtures = {
      mealPlan: { weekStart: '2026-09-28', entries: [
        { id: 'soup', date: '2026-10-01', slot: 'dinner', meal: 'Lentil soup & roasted vegetables', notes: 'Use the spinach from the fridge.' },
      ], tasks: [{ id: 'prep', date: '2026-10-01', title: 'Prep tomorrow’s lunch', notes: 'Pack two leftover portions after dinner.' }] },
      shoppingList: { items: [
        { id: 'milk', name: 'Milk', quantity: 1, unit: 'gallon', store: 'Costco', purchased: false },
        { id: 'rice', name: 'Rice', quantity: 1, unit: 'bag', store: 'Safeway', purchased: false },
      ] },
      pantry: [{ id: 'spinach', name: 'Spinach', quantity: 1, unit: 'bag', use_by_date: '2026-10-01' }, { id: 'avocado', name: 'Avocados', quantity: 2, unit: 'each', use_by_date: '2026-10-03' }],
    };
    if (fixtures[name]) data.sections[name] = { status: 'ready', value: fixtures[name] };
    await route.fulfill({ json: data });
  });
  await page.goto('/app');
  await expect(home(page, 'mealPlan')).not.toContainText('Prep tomorrow’s lunch');
  await home(page, 'mealPlan').getByRole('button', {name:'Tasks',exact:true}).click();
  await expect(home(page, 'mealPlan')).toContainText('Prep tomorrow’s lunch');
  await expect(home(page, 'mealPlan')).not.toContainText('Lentil soup & roasted vegetables');
  await home(page, 'mealPlan').getByRole('button', {name:'Meals',exact:true}).click();
  await expect(home(page, 'pantry')).toContainText('Avocados');
  await expect(home(page, 'shoppingList')).toContainText('Milk');
  await page.screenshot({ path: 'test-results/homepage-desktop.png', fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: 'test-results/homepage-mobile.png', fullPage: true });
  await page.getByRole('button', { name: 'Open weekly plan', exact: true }).click();
  await expect(page.locator('.day-card').nth(3)).toContainText('Lentil soup & roasted vegetables');
  await expect(page.locator('#week-picker')).toHaveValue('2026-09-28');
});

test('a failed home section retries without blocking meals or shopping', async ({ page }) => {
  await freezeToday(page);
  let pantryAttempts = 0;
  await page.route(snapshotRoute, async (route) => {
    const name = new URL(route.request().url()).searchParams.get('sections');
    if (name !== 'pantry') return route.continue();
    pantryAttempts += 1;
    if (pantryAttempts === 1) return route.fulfill({ status: 503, json: { detail: 'Unavailable' } });
    const response = await route.fetch();
    const data = await response.json();
    data.sections.pantry = { status: 'ready', value: [
      { id: 'retry-spinach', name: 'Retry spinach', quantity: 1, unit: 'bag', use_by_date: '2026-10-01' },
      { id: 'old-milk', name: 'Check old milk', quantity: 1, use_by_date: '2026-09-30' },
      { name: 'Future yogurt', quantity: 1, use_by_date: '2026-10-05' },
      { name: 'Used-up carrots', quantity: 0, use_by_date: '2026-10-01' },
      { name: 'Undated rice', quantity: 1 },
    ] };
    return route.fulfill({ json: data });
  });
  await page.goto('/app');
  await expect(home(page, 'pantry')).toContainText('Could not load pantry');
  await expect(home(page, 'pantry')).not.toContainText('No pantry items');
  await expect(home(page, 'shoppingList').locator('.section-loading')).toHaveCount(0);
  await home(page, 'pantry').getByRole('button', { name: 'Try again' }).click();
  await expect(home(page, 'pantry')).toContainText('Retry spinach');
  await expect(home(page, 'pantry')).toContainText('Use-by today');
  await expect(home(page, 'pantry')).toContainText('Past recorded date');
  for (const name of ['Future yogurt', 'Used-up carrots', 'Undated rice']) await expect(home(page, 'pantry')).not.toContainText(name);
  expect(pantryAttempts).toBe(2);
  await home(page, 'pantry').locator('.row').filter({ hasText: 'Retry spinach' }).getByRole('button', { name: 'Review' }).click();
  await expect(page.locator('#editor-dialog [name="name"]')).toHaveValue('Retry spinach');
});

test('home actions save today’s prep and shopping progress to the backend', async ({ page }) => {
  await freezeToday(page);
  const grocery = `Homepage apples ${Date.now()}`;
  const shopping = (await (await page.request.post('/api/shopping-list/items', { data: { item: { name: grocery, quantity: 3, unit: 'each' } } })).json());
  const item = shopping.items.find((entry) => entry.name === grocery);
  await page.route(snapshotRoute, async (route) => {
    if (new URL(route.request().url()).searchParams.get('sections') !== 'shoppingList') return route.continue();
    const data = await (await route.fetch()).json();
    data.sections.shoppingList.value.items.sort((a, b) => Number(b.id === item.id) - Number(a.id === item.id));
    return route.fulfill({ json: data });
  });
  const prep = `Homepage prep ${Date.now()}`;
  await page.goto('/app');
  await home(page, 'mealPlan').getByRole('button', {name:'Tasks',exact:true}).click();
  await home(page, 'mealPlan').getByRole('button', { name: 'Add a task for today' }).click();
  const editor = page.locator('#editor-dialog');
  await expect(editor.locator('[name="date"]')).toHaveValue('2026-10-01');
  await editor.locator('[name="title"]').fill(prep);
  await editor.locator('#dialog-save').click();
  await expect(editor).toBeHidden();
  await expect(home(page, 'mealPlan')).toContainText(prep);
  const savedPlan = (await (await page.request.get('/api/meal-plan?week_start=2026-09-28')).json()).plan;
  expect(savedPlan.tasks).toContainEqual(expect.objectContaining({ title: prep, date: '2026-10-01', mealIds: [] }));
  await home(page, 'shoppingList').getByRole('checkbox', { name: `Mark ${grocery} purchased`, exact: true }).check();
  await expect(page.locator('#toast')).toHaveText('Shopping progress saved.');
  await expect(home(page, 'shoppingList')).not.toContainText(grocery);
  const savedShopping = (await (await page.request.get('/api/shopping-list')).json()).shoppingList;
  expect(savedShopping.items.find((entry) => entry.id === item.id).purchased).toBe(true);
});

test('a response from before refresh cannot replace the new household’s pantry', async ({ page }) => {
  await freezeToday(page);
  let householdVersion = 0;
  let release;
  const delayed = new Promise((resolve) => { release = resolve; });
  await page.route('**/api/app/bootstrap?*', async (route) => {
    const response = await route.fetch();
    const data = await response.json();
    householdVersion += 1;
    data.snapshot.household.householdId = `home-${householdVersion}`;
    await route.fulfill({ json: data });
  });
  await page.route(snapshotRoute, async (route) => {
    const version = householdVersion;
    const name = new URL(route.request().url()).searchParams.get('sections');
    const response = await route.fetch();
    const data = await response.json();
    data.household.householdId = `home-${version}`;
    if (name === 'pantry') {
      if (version === 1) await delayed;
      data.sections.pantry = { status: 'ready', value: [{ name: `Household ${version} spinach`, quantity: 1, use_by_date: '2026-10-01' }] };
    }
    await route.fulfill({ json: data });
  });
  try {
    await page.goto('/app');
    await expect(home(page, 'pantry')).toContainText('Loading pantry');
    await page.getByRole('button', { name: 'Refresh data' }).click();
    await expect(home(page, 'pantry')).toContainText('Household 2 spinach');
    const oldResponse = page.waitForResponse(async (response) => response.url().includes('sections=pantry') && (await response.json()).household.householdId === 'home-1');
    release();
    await (await oldResponse).finished();
    await expect(home(page, 'pantry')).toContainText('Household 2 spinach');
    await expect(home(page, 'pantry')).not.toContainText('Household 1 spinach');
  } finally { release(); }
});

test('returning to a slow week does not display the current week’s meals', async ({ page }) => {
  await freezeToday(page);
  let release;
  const delayed = new Promise((resolve) => { release = resolve; });
  await page.route(snapshotRoute, async (route) => {
    const params = new URL(route.request().url()).searchParams;
    const data = await (await route.fetch()).json();
    if (params.get('sections') === 'mealPlan') {
      const future = params.get('week_start') === '2030-02-04';
      if (future) await delayed;
      data.sections.mealPlan = { status: 'ready', value: {
        weekStart: future ? '2030-02-04' : '2026-09-28',
        entries: [{ date: future ? '2030-02-04' : '2026-10-01', meal: future ? 'Future-week soup' : 'Current-week dinner' }],
      } };
    }
    await route.fulfill({ json: data });
  });
  try {
    await page.goto('/app?view=plan&week=2030-02-04');
    await expect(page.locator('#app-content .section-loading')).toBeVisible();
    await page.locator('.sidebar [data-view="overview"]').click();
    await expect(home(page, 'mealPlan')).toContainText('Current-week dinner');
    await page.goBack();
    await expect(page.locator('#view-title')).toHaveText('Weekly plan');
    await expect(page.locator('#app-content .section-loading')).toBeVisible();
    await expect(page.locator('#app-content')).not.toContainText('Current-week dinner');
    release();
    await expect(page.locator('#week-picker')).toHaveValue('2030-02-04');
    await expect(page.locator('.day-card').first()).toContainText('Future-week soup');
  } finally { release(); }
});
