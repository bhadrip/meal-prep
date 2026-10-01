const { test, expect } = require('@playwright/test');

test('the website inbox opens household activity and marks it read', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  let readAt = null;
  const opened = [];
  await page.route('**/api/notifications', (route) => route.fulfill({ json: {
    items: [{ id: '00000000-0000-0000-0000-000000000042', household_id: 'home-2', kind: 'shopping_lists',
      title: 'Shopping list updated', target_path: '/app?view=shopping',
      created_at: '2026-09-30T12:00:00Z', read_at: readAt }],
    unreadCount: readAt ? 0 : 1,
  } }));
  await page.route('**/api/notifications/00000000-0000-0000-0000-000000000042/read', (route) => {
    opened.push(route.request().method());
    readAt = '2026-09-30T12:01:00Z';
    return route.fulfill({ json: { id: '00000000-0000-0000-0000-000000000042', readAt } });
  });
  await page.route('**/api/households/home-2/activate', (route) => {
    opened.push('ACTIVATE');
    return route.fulfill({ json: { activeHouseholdId: 'home-2' } });
  });

  await page.goto('/app');
  await expect(page.locator('#notification-count')).toHaveText('1');
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.getByRole('button', { name: 'Notifications, 1 unread' }).click();
  await expect(page).toHaveURL(/view=notifications/);
  await expect(page.locator('.notification-item.unread')).toContainText('Shopping list updated');
  await page.getByRole('button', { name: 'Open', exact: true }).click();
  await expect(page).toHaveURL(/view=shopping/);
  await expect(page.locator('#notification-count')).toBeHidden();
  expect(opened).toEqual(['PATCH', 'ACTIVATE']);
});
