const { test, expect } = require('@playwright/test');
const { navigateToView } = require('./navigation');
test.use({ hasTouch: true });

async function bounds(page, scope = page.locator('body')) {
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), 'Page must not scroll sideways').toBe(true);
  const small = await scope.locator('button:visible, summary:visible, a:visible').evaluateAll(elements => elements.filter(element => {
    const box = element.getBoundingClientRect();
    return element.isConnected && box.width > 0 && box.height > 0 && (box.width < 43.9 || box.height < 43.9);
  }).map(element => ({ name: element.textContent.trim() || element.getAttribute('aria-label'), width: element.getBoundingClientRect().width, height: element.getBoundingClientRect().height })));
  expect(small, 'Every available action needs a 44px touch target').toEqual([]);
}

async function tapVisible(page, target) {
  // A sticky header or bottom navigation must not cover the action's center.
  await expect.poll(() => target.evaluate(element => {
    element.scrollIntoView({ block: 'center', inline: 'nearest' });
    const b = element.getBoundingClientRect();
    const hit = document.elementFromPoint(b.x + b.width / 2, b.y + b.height / 2);
    return element === hit || element.contains(hit);
  })).toBe(true);
  await target.tap();
}

test('touch navigation reaches every section, dismisses safely, and survives rotation', async ({ page }, info) => {
  await page.setViewportSize({ width: 320, height: 568 });
  await page.goto('/app');
  for (const [view, title] of Object.entries({ overview: 'Overview', plan: 'Weekly plan', recipes: 'Recipes', pantry: 'Pantry', shopping: 'Shopping', reviews: 'Reviews', circles: 'Circles', settings: 'Settings' })) {
    if (['reviews', 'circles', 'settings'].includes(view)) {
      await page.locator('#mobile-more').tap();
      await page.locator(`#mobile-menu-dialog [data-view="${view}"]`).tap();
      await expect(page.locator('#mobile-menu-dialog')).toBeHidden();
    } else await page.locator(`.mobile-nav [data-view="${view}"]`).tap();
    await expect(page.locator('#view-title')).toHaveText(title);
    await expect(page.locator('.section-loading')).toHaveCount(0);
    await bounds(page);
  }
  await page.locator('#mobile-more').tap();
  await page.screenshot({ path: info.outputPath('phone-navigation.png') });
  await page.getByRole('button', { name: 'Close navigation' }).tap();
  await expect(page.locator('#mobile-more')).toBeFocused();
  await expect(page.locator('#mobile-more')).toHaveAttribute('aria-expanded', 'false');
  await page.locator('#mobile-more').tap();
  await page.keyboard.press('Escape');
  await expect(page.locator('#mobile-menu-dialog')).toBeHidden();
  await page.locator('#mobile-more').tap();
  await page.touchscreen.tap(2, 2);
  await expect(page.locator('#mobile-menu-dialog')).toBeHidden();
  await page.locator('#mobile-more').tap();
  await page.setViewportSize({ width: 1024, height: 768 });
  await expect(page.locator('#mobile-menu-dialog')).toBeHidden();
  await expect(page.locator('.sidebar')).toBeVisible();
  await page.setViewportSize({ width: 390, height: 844 });
  await page.getByRole('button', { name: /^Notifications/ }).tap();
  await expect(page.locator('#view-title')).toHaveText('Notifications');
  await bounds(page);
});

test('every page and editor fits small phones, tablets and short landscapes', async ({ page }, info) => {
  test.setTimeout(90000);
  const editors = [
    ['recipes', 'Add recipe'], ['recipes', 'Create meal'], ['pantry', 'Add pantry item'],
    ['shopping', 'Add item'], ['reviews', 'Review this week'], ['reviews', 'Review a meal'], ['reviews', 'Add memory'],
    ['settings', 'Edit meal slots'], ['plan', 'Add meal'], ['plan', 'Edit notes'],
  ];
  for (const size of [{ width: 320, height: 568 }, { width: 390, height: 844 }, { width: 768, height: 1024 }, { width: 740, height: 360 }]) {
    await page.setViewportSize(size);
    for (const path of ['/', '/login', '/invite', '/oauth/consent']) {
      await page.goto(path);
      await bounds(page);
    }
    for (const view of ['overview', 'plan', 'recipes', 'pantry', 'shopping', 'reviews', 'settings', 'circles']) {
      await page.goto(`/app?view=${view}`);
      await expect(page.locator('.section-loading')).toHaveCount(0);
      await expect(page.locator('#app-content .loading')).toHaveCount(0);
      await bounds(page);
    }
    for (const [view, name] of editors) {
      await navigateToView(page, view);
      await tapVisible(page, page.locator('#app-content').getByRole('button', { name, exact: true }));
      const editor = page.locator('#editor-dialog');
      await expect(editor).toBeVisible();
      await bounds(page, editor);
      const box = await editor.boundingBox();
      expect(box.x).toBeGreaterThanOrEqual(0);
      expect(box.x + box.width).toBeLessThanOrEqual(size.width);
      expect(box.y + box.height).toBeLessThanOrEqual(size.height);
      const fonts = await editor.locator('input:not([type="hidden"]), textarea').evaluateAll(elements => elements.map(element => parseFloat(getComputedStyle(element).fontSize)));
      expect(fonts.every(size => size >= 16), 'Text fields must not trigger iPhone focus zoom').toBe(true);
      const choice = editor.locator('.choice-trigger:enabled').first();
      if (await choice.count()) {
        await tapVisible(page, choice);
        const menu = editor.getByRole('listbox');
        await expect(menu).toBeVisible();
        const menuBounds = await menu.boundingBox();
        const footer = await editor.locator('.dialog-actions').boundingBox();
        expect(menuBounds.y + menuBounds.height).toBeLessThanOrEqual(footer.y);
      }
      await tapVisible(page, editor.getByRole('button', { name: 'Cancel', exact: true }));
      await expect(editor).toBeHidden();
    }
    await page.screenshot({ path: info.outputPath(`layout-${size.width}-${size.height}.png`) });
  }
});

test('long recipe editor keeps its actions reachable after a rejected save and keyboard-sized resize', async ({ page }, info) => {
  await page.setViewportSize({ width: 320, height: 568 });
  await page.goto('/app?view=recipes');
  await page.getByRole('button', { name: 'Add recipe', exact: true }).tap();
  const editor = page.locator('#editor-dialog');
  const title = `Phone recipe ${info.project.name} ${Date.now()}`;
  await editor.locator('[name="title"]').fill(title);
  await editor.locator('[name="ingredients"]').fill('Lentils | 1 | cup');
  await editor.locator('[name="instructions"]').fill('Cook the lentils.\nServe warm.');
  await page.setViewportSize({ width: 320, height: 340 });
  await editor.locator('[name="sourceUrl"]').fill('https://example.test/recipe');
  await bounds(page, editor);
  await page.route('**/api/recipes', route => route.request().method() === 'PUT' ? route.fulfill({ status: 503, json: { detail: 'Please retry your recipe save.' } }) : route.continue());
  await tapVisible(page, editor.locator('#dialog-save'));
  await expect(editor.locator('#dialog-error')).toHaveText('Please retry your recipe save.');
  await expect(editor.locator('[name="title"]')).toHaveValue(title);
  await page.screenshot({ path: info.outputPath('short-editor-retry.png') });
  await page.unroute('**/api/recipes');
  await tapVisible(page, editor.locator('#dialog-save'));
  await expect(editor).toBeHidden();
  await page.setViewportSize({ width: 390, height: 844 });
  await page.reload();
  await page.getByRole('button', { name: '← All recipes', exact: true }).tap();
  await page.locator('#recipe-search').fill(title);
  await expect(page.locator('#recipe-results')).toContainText(title);
  await page.locator('.rb-open').filter({ hasText: title }).tap();
  await expect(page.locator('.hero h2')).toHaveText(title);
  await bounds(page);
});

test('touch pantry and shopping actions persist and retain rejected drafts', async ({ page }, info) => {
  await page.setViewportSize({ width: 320, height: 568 });
  const name = `Phone rice ${info.project.name} ${Date.now()}`;
  await page.goto('/app?view=pantry');
  await page.getByRole('button', { name: 'Add pantry item', exact: true }).tap();
  const editor = page.locator('#editor-dialog');
  await editor.locator('[name="name"]').fill(name);
  await editor.locator('[name="quantity"]').fill('4');
  await editor.locator('[name="unit"]').fill('cups');
  const storage = editor.locator('[name="storageLocation"]').locator('..');
  await storage.locator('.choice-trigger').tap();
  await storage.getByRole('option', { name: 'Pantry', exact: true }).tap();
  await tapVisible(page, editor.locator('#dialog-save'));
  await expect(editor).toBeHidden();
  const row = page.locator('.pantry-table .table-row').filter({ hasText: name });
  await tapVisible(page, row.getByRole('button', { name: 'Use', exact: true }));
  await editor.locator('[name="quantity"]').fill('5');
  // Remove the native max only to exercise the server's failure path.
  await editor.locator('[name="quantity"]').evaluate(element => element.removeAttribute('max'));
  await tapVisible(page, editor.locator('#dialog-save'));
  await expect(editor.locator('#dialog-error')).not.toBeEmpty();
  await expect(editor.locator('[name="quantity"]')).toHaveValue('5');
  await editor.locator('[name="quantity"]').fill('1');
  await tapVisible(page, editor.locator('#dialog-save'));
  await expect(editor).toBeHidden();
  await expect(row).toContainText('3 cups left');
  await page.reload();
  await expect(row).toContainText('3 cups left');
  await bounds(page);
  await page.locator('.mobile-nav [data-view="shopping"]').tap();
  await page.getByRole('button', { name: 'Add item', exact: true }).tap();
  await editor.locator('[name="name"]').fill(name);
  await editor.locator('[name="quantity"]').fill('2');
  await editor.locator('[name="unit"]').fill('bags');
  await tapVisible(page, editor.locator('#dialog-save'));
  await expect(editor).toBeHidden();
  const shopping = page.locator('.check-row').filter({ hasText: name });
  await tapVisible(page, shopping.getByRole('checkbox'));
  await expect(shopping.getByRole('checkbox')).toBeChecked();
  await expect(shopping).toHaveClass(/done/);
  await tapVisible(page, shopping.getByRole('button', { name: 'Edit', exact: true }));
  await editor.locator('[name="quantity"]').fill('3');
  await tapVisible(page, editor.locator('#dialog-save'));
  await expect(editor).toBeHidden();
  await page.reload();
  await expect(shopping).toContainText('3 bags');
  await expect(shopping.getByRole('checkbox')).toBeChecked();
  await bounds(page);
  page.once('dialog', dialog => dialog.accept());
  await tapVisible(page, shopping.getByRole('button', { name: 'Remove', exact: true }));
  await expect(shopping).toHaveCount(0);
});
