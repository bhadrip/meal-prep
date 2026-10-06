const { test, expect } = require('@playwright/test');

test('editor dropdowns support keyboard selection, cancel, Tab, and saved values', async ({ page }) => {
  await page.goto('/app?view=pantry');
  await page.getByRole('button', { name: 'Add pantry item', exact: true }).click();
  const editor = page.locator('#editor-dialog');
  const control = (name) => editor.locator(`input[type="hidden"][name="${name}"]`).locator('..');
  const category = control('category');
  await category.locator('.choice-trigger').focus();
  await category.locator('.choice-trigger').press('ArrowDown');
  await expect(category.getByRole('option', { name: 'Categorize from name', exact: true })).toBeFocused();
  await category.getByRole('option', { name: 'Categorize from name', exact: true }).press('End');
  await expect(category.getByRole('option', { name: 'Uncategorized', exact: true })).toBeFocused();
  await category.getByRole('option', { name: 'Uncategorized', exact: true }).press('Escape');
  await expect(editor).toBeVisible();
  await expect(category.locator('input')).toHaveValue('auto');
  await expect(category.locator('.choice-trigger')).toBeFocused();
  await category.locator('.choice-trigger').press('ArrowDown');
  await page.keyboard.type('fro');
  await expect(category.getByRole('option', { name: 'Frozen', exact: true })).toBeFocused();
  await category.getByRole('option', { name: 'Frozen', exact: true }).press('Enter');
  await expect(category.locator('input')).toHaveValue('frozen');
  await category.locator('.choice-trigger').click();
  await page.keyboard.press('Tab');
  await expect(category.getByRole('listbox')).toBeHidden();
  await expect(editor.locator('[name="quantity"]')).toBeFocused();

  await control('storageLocation').locator('.choice-trigger').click();
  await control('storageLocation').getByRole('option', { name: 'Fridge', exact: true }).click();
  await control('quantityConfidence').locator('.choice-trigger').click();
  await control('quantityConfidence').getByRole('option', { name: 'Exact', exact: true }).click();
  const name = `Dropdown peas ${Date.now()}`;
  await editor.locator('[name="name"]').fill(name);
  await editor.locator('[name="quantity"]').fill('2');
  await editor.locator('#dialog-save').click();
  await expect(editor).toBeHidden();
  await expect(page.locator('#app-content')).toContainText(name);
  const saved = (await (await page.request.get('/api/pantry')).json()).items.find((item) => item.name === name);
  expect(saved).toMatchObject({ category: 'frozen', storageLocation: 'fridge', quantityConfidence: 'exact', quantity: 2 });
});

test('account menu opens settings household switcher, restores failure, and persists selection', async ({ page }) => {
  const first = '00000000-0000-0000-0000-000000000042';
  const second = '00000000-0000-0000-0000-000000000043';
  let active = first;
  let attempts = 0;
  await page.route('**/api/auth/config', (route) => route.fulfill({ json: { supabaseUrl: 'https://example.test', supabaseAnonKey: 'test', authRequired: true } }));
  await page.route('**/static/vendor/supabase.js', (route) => route.fulfill({ contentType: 'application/javascript', body: `window.supabase = {createClient: () => ({auth: {getSession: async () => ({data: {session: {access_token: 'test', user: {email: 'owner@example.test'}}}})}})};` }));
  await page.route('**/api/app/bootstrap?*', async (route) => {
    const data = await (await route.fetch()).json();
    data.memberships = { activeHouseholdId: active, households: [
      { id: first, name: 'My household', role: 'owner' },
      { id: second, name: 'Weekend kitchen with a longer household name', role: 'member' },
    ] };
    data.access = { role: active === first ? 'owner' : 'member' };
    await route.fulfill({ json: data });
  });
  await page.route(`**/api/households/${second}/activate`, (route) => {
    attempts += 1;
    if (attempts === 1) return route.fulfill({ status: 503, json: { detail: 'Please retry the household switch.' } });
    active = second;
    return route.fulfill({ json: { activeHouseholdId: second } });
  });
  await page.setViewportSize({ width: 1360, height: 950 });
  await page.goto('/app');
  await expect(page.locator('#account-label')).toHaveText('My household');
  await expect(page.locator('.topbar .choice-trigger')).toHaveCount(0);
  await page.locator('#account-button').click();
  await page.locator('#account-switch-household').click();
  await expect(page.locator('#view-title')).toHaveText('Settings');
  const picker = page.locator('#household-choice');
  await expect(picker.locator('.choice-trigger')).toBeFocused();
  await expect(picker.locator('.choice-trigger')).toContainText('My household · Owner');
  await picker.locator('.choice-trigger').click();
  await expect(picker.getByRole('option', { name: 'My household · Owner', exact: true })).toHaveAttribute('aria-selected', 'true');
  await page.screenshot({ path: 'test-results/dropdown-household.png' });
  await page.getByRole('heading', { name: 'Your households', exact: true }).click();
  await expect(picker.getByRole('listbox')).toBeHidden();

  await page.setViewportSize({ width: 390, height: 844 });
  const triggerBox = await picker.locator('.choice-trigger').boundingBox();
  expect(triggerBox.x).toBeGreaterThanOrEqual(0);
  expect(triggerBox.x + triggerBox.width).toBeLessThanOrEqual(390);
  expect(triggerBox.width).toBeGreaterThan(100);
  await picker.locator('.choice-trigger').click();
  const box = await picker.getByRole('listbox').boundingBox();
  expect(box.x).toBeGreaterThanOrEqual(0);
  expect(box.x + box.width).toBeLessThanOrEqual(390);
  expect(box.y + box.height).toBeLessThanOrEqual(844);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await picker.getByRole('option', { name: /Weekend kitchen/ }).click();
  await expect(page.locator('#toast')).toHaveText('Please retry the household switch.');
  await expect(page.locator('#household-select')).toHaveValue(first);
  await expect(picker.locator('.choice-trigger')).toContainText('My household · Owner');
  await expect(picker.locator('.choice-trigger')).toBeEnabled();
  await picker.locator('.choice-trigger').press('ArrowDown');
  await page.keyboard.press('End');
  await picker.getByRole('option', { name: /Weekend kitchen/ }).press('Enter');
  await expect(page.locator('#household-select')).toHaveValue(second);
  await expect(page.locator('#account-label')).toContainText('Weekend kitchen');
  await expect(picker.locator('.choice-trigger')).toContainText('Weekend kitchen');
  await page.reload();
  await expect(page.locator('#household-select')).toHaveValue(second);
  await picker.locator('.choice-trigger').click();
  await expect(picker.getByRole('option', { name: /Weekend kitchen/ })).toHaveAttribute('aria-selected', 'true');
  // Capture the real mobile viewport; full-page capture resizes it and can close the popover.
  await page.screenshot({ path: 'test-results/dropdown-mobile.png' });
  await page.keyboard.press('Escape');
  await expect(picker.locator('.choice-trigger')).toBeFocused();
  expect(attempts).toBe(2);
});
