const { test, expect } = require('@playwright/test');

const content = (page) => page.locator('#app-content');
const editor = (page) => page.locator('#editor-dialog');
const unique = (prefix) => `${prefix} ${Date.now()}`;

async function open(page, view) {
  await page.goto('/');
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
  await page.locator('.mobile-nav [data-view="shopping"]').click();
  await expect(page.locator('#view-title')).toHaveText('Shopping');
});

test('overview shortcuts and editor validation and cancel', async ({ page }) => {
  await open(page, 'overview');
  for (const [button, title] of [
    ['View plan', 'Weekly plan'], ['Open list', 'Shopping'], ['View pantry', 'Pantry'],
    ['Edit preferences', 'Settings'], ['Browse recipes', 'Recipes'], ['View reviews', 'Reviews'],
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
  await form.getByRole('button', { name: 'Save household setup' }).click();
  await expect(form.locator('[name="householdSize"]')).toHaveValue('3');
  await expect(form.locator('[name="stores"]')).toHaveValue('Safeway, Costco');
  await page.locator('.sidebar [data-view="overview"]').click();
  await expect(content(page)).toContainText('3 people');
  await expect(content(page)).toContainText('25 minutes maximum');
  await expect(content(page)).toContainText('No dietary restrictions recorded.');
  await page.locator('.sidebar [data-view="settings"]').click();
  await page.getByRole('button', { name: 'Move Food rules down' }).click();
  await expect(page.locator('#dashboard-form .card-order-row').first()).toContainText('Planning defaults');
  await page.locator('#dashboard-form [name="visibleCard"][value="pantry"]').uncheck();
  await page.getByRole('button', { name: 'Save visible cards' }).click();
  await expect(page.locator('#dashboard-form [name="visibleCard"][value="pantry"]')).not.toBeChecked();
  await page.reload();
  await page.locator('.sidebar [data-view="settings"]').click();
  await expect(page.locator('#dashboard-form .card-order-row').first()).toContainText('Planning defaults');
  await expect(page.locator('#dashboard-form [name="visibleCard"][value="pantry"]')).not.toBeChecked();
});

test('weekly rhythm and planned meal can be added, edited, and removed', async ({ page }) => {
  await open(page, 'plan');
  const week = await page.locator('#week-picker').inputValue();
  await content(page).getByRole('button', { name: 'Edit weekly rhythm' }).click();
  await choose(page, 'Monday', 'busy');
  await saveEditor(page);
  await expect(content(page).locator('.day-card').first()).toContainText('busy');
  const meal = unique('Playwright dinner');
  await content(page).getByRole('button', { name: 'Add meal or prep' }).click();
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
  page.once('dialog', (dialog) => dialog.accept());
  await updated.getByRole('button', { name: 'Remove' }).click();
  await expect(updated).toHaveCount(0);
  await page.locator('#week-picker').fill('2027-01-04');
  await expect(page.locator('#week-picker')).toHaveValue('2027-01-04');
  await expect(content(page).locator('.day-card')).toHaveCount(7);
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
  const shareUrl = await page.getByRole('textbox', { name: 'New recipe share link' }).inputValue();
  expect(shareUrl).toContain('/s/');
  await content(page).getByRole('button', { name: 'Copy link' }).click();
  await page.goto(shareUrl);
  await expect(page.getByRole('heading', { name: title })).toBeVisible();
  await page.locator('#save-recipe').click();
  await expect(page.locator('#message')).toHaveText('Saved to your household recipes.');
  await page.goto('/');
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
  await page.goto('/');
  await page.locator('.sidebar [data-view="recipes"]').click();
  await content(page).locator(`[data-action="open-recipe"][data-id="${originalId}"]`).click();
  page.once('dialog', (dialog) => dialog.accept());
  await content(page).getByRole('button', { name: 'Archive' }).click();
  await expect(content(page).locator(`[data-action="open-recipe"][data-id="${originalId}"]`)).toHaveCount(0);
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
  await saveEditor(page);
  row = content(page).locator('.check-row').filter({ hasText: name });
  await expect(row).toContainText('5 each');
  await row.getByRole('checkbox').uncheck();
  row = content(page).locator('.check-row').filter({ hasText: name });
  await expect(row.getByRole('checkbox')).not.toBeChecked();
  page.once('dialog', (dialog) => dialog.accept());
  await row.getByRole('button', { name: 'Remove' }).click();
  await expect(content(page).locator('.check-row').filter({ hasText: name })).toHaveCount(0);
});

test('feedback and household memory lifecycle', async ({ page }) => {
  await open(page, 'reviews');
  const note = unique('Playwright meal note');
  await content(page).getByRole('button', { name: 'Add meal feedback' }).click();
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
      signInWithOtp: async () => ({ error: null }),
      verifyOtp: async ({ email, token }) => {
        if (token !== '12345678') return { data: {}, error: { message: 'Invalid code' } };
        const session = { access_token: 'fake-token', user: { email } };
        sessionStorage.setItem('mock-session', JSON.stringify(session));
        return { data: { session }, error: null };
      },
      signOut: async () => { sessionStorage.removeItem('mock-session'); return { error: null }; },
    } }) };`,
  }));
  await page.goto('/login?next=%2F');
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
