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

test('notifications can be read, cleared into the archive and restored across reloads', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  const item = { id: '00000000-0000-0000-0000-000000000042', title: 'Pantry updated',
    target_path: '/app?view=pantry', created_at: '2026-10-02T12:00:00Z', read_at: null, archived_at: null };
  let failArchive = false;
  await page.route('**/api/notifications**', async route => {
    const url = new URL(route.request().url());
    if (url.pathname.endsWith('/read')) {
      item.read_at = url.searchParams.get('read') === 'false' ? null : '2026-10-02T12:01:00Z';
      return route.fulfill({ json: { id: item.id, readAt: item.read_at } });
    }
    if (url.pathname.endsWith('/archive')) {
      if (failArchive) return route.fulfill({ status: 404, json: { detail: 'Notification not found' } });
      item.archived_at = url.searchParams.get('archived') === 'false' ? null : '2026-10-02T12:02:00Z';
      return route.fulfill({ json: { id: item.id, archivedAt: item.archived_at } });
    }
    const archived = url.searchParams.get('archived') === 'true';
    return route.fulfill({ json: { items: Boolean(item.archived_at) === archived ? [item] : [], unreadCount: !item.read_at && !item.archived_at ? 1 : 0 } });
  });
  await page.goto('/app?view=notifications');
  await expect(page.locator('.notification-item.unread')).toHaveCount(1);
  await page.getByRole('button', { name: 'Mark read', exact: true }).click();
  await expect(page.locator('.notification-item.unread')).toHaveCount(0);
  await expect(page.locator('#notification-count')).toBeHidden();
  await page.reload();
  await page.getByRole('button', { name: 'Mark unread', exact: true }).click();
  await expect(page.locator('#notification-count')).toHaveText('1');
  failArchive = true;
  await page.getByRole('button', { name: 'Archive', exact: true }).click();
  await expect(page.locator('.notification-item.unread')).toHaveCount(1);
  await expect(page.locator('#notification-count')).toHaveText('1');
  failArchive = false;
  await page.getByRole('button', { name: 'Archive', exact: true }).click();
  await expect(page.locator('.notification-item')).toHaveCount(0);
  await expect(page.locator('#notification-count')).toBeHidden();
  await page.reload();
  await expect(page.locator('.notification-item')).toHaveCount(0);
  await page.getByRole('button', { name: 'View archive', exact: true }).click();
  await expect(page.locator('.notification-item')).toContainText('Pantry updated');
  await page.getByRole('button', { name: 'Restore to inbox', exact: true }).click();
  await expect(page.locator('.notification-item')).toHaveCount(0);
  await page.getByRole('button', { name: 'Back to inbox', exact: true }).click();
  await expect(page.locator('.notification-item.unread')).toHaveCount(1);
  await expect(page.locator('#notification-count')).toHaveText('1');
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});
