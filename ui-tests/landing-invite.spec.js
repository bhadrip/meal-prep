const { test, expect } = require('@playwright/test');

test('landing links open the app and copy the MCP URL', async ({ page }) => {
  await page.goto('/');
  await expect(page.getByRole('heading', { name: 'Your food week, all together.' })).toBeVisible();
  await page.getByRole('button', { name: 'Copy MCP server URL' }).click();
  await expect(page.locator('#copy-mcp')).toHaveText(/Copied|Select the URL to copy/);
  await page.getByRole('link', { name: 'Open the app' }).first().click();
  await expect(page).toHaveURL(/\/app$/);
  await expect(page.locator('#view-title')).toHaveText('Overview');
});

async function mockInviteSession(page, session) {
  await page.route('**/api/auth/config', (route) => route.fulfill({ json: {
    supabaseUrl: 'https://example.supabase.co', supabaseAnonKey: 'public-test-key', authRequired: true,
  } }));
  await page.route('**/static/vendor/supabase.js', (route) => route.fulfill({
    contentType: 'application/javascript',
    body: `if (sessionStorage.getItem('mock-invite-session') === null) sessionStorage.setItem('mock-invite-session', ${JSON.stringify(JSON.stringify(session))});
      window.supabase = { createClient: () => ({ auth: {
      getSession: async () => ({ data: { session: JSON.parse(sessionStorage.getItem('mock-invite-session')) }, error: null }),
      signOut: async () => { sessionStorage.setItem('mock-invite-session', 'null'); return { error: null }; },
    } }) };`,
  }));
}

test('invitation page directs signed-out visitors to sign in', async ({ page }) => {
  await mockInviteSession(page, null);
  await page.goto('/invite');
  await expect(page.getByRole('link', { name: 'sign in with the invited email address' })).toHaveAttribute('href', '/login?next=%2Finvite');
});

test('invitation page shows empty state and lets members switch account', async ({ page }) => {
  await mockInviteSession(page, { access_token: 'test-token', user: { email: 'member@example.com' } });
  await page.route('**/api/invitations/mine', (route) => route.fulfill({ json: { invitations: [], hasHousehold: true } }));
  await page.goto('/invite');
  await expect(page.locator('#message')).toContainText('No active invitation');
  await expect(page.locator('#account')).toContainText('member@example.com');
  await page.getByRole('button', { name: 'Switch account' }).click();
  await expect(page).toHaveURL(/\/login\?next=%2Finvite/);
});

test('invitation can be retried after an error and then accepted', async ({ page }) => {
  await mockInviteSession(page, { access_token: 'test-token', user: { email: 'member@example.com' } });
  await page.route('**/api/invitations/mine', (route) => route.fulfill({ json: { invitations: [
    { id: 'invite-1', householdName: '<Shared kitchen>', expiresAt: '2030-10-01T00:00:00Z' },
  ], hasHousehold: true } }));
  let attempts = 0;
  await page.route('**/api/invitations/invite-1/accept', (route) => {
    attempts += 1;
    return route.fulfill(attempts === 1
      ? { status: 409, json: { detail: 'Invitation is temporarily unavailable.' } }
      : { json: { accepted: true } });
  });
  await page.goto('/invite');
  await expect(page.locator('#invitations')).toContainText('<Shared kitchen>');
  await expect(page.locator('#invitations img')).toHaveCount(0);
  const join = page.getByRole('button', { name: 'Join household' });
  await join.click();
  await expect(page.locator('#message')).toHaveText('Invitation is temporarily unavailable.');
  await expect(join).toBeEnabled();
  await join.click();
  await expect(page).toHaveURL(/\/app$/);
  expect(attempts).toBe(2);
});

test('household settings create, revoke, remove, switch, and leave through the UI', async ({ page }) => {
  await mockInviteSession(page, { access_token: 'test-token', user: { email: 'owner@example.com' } });
  let activeId = 'home-1';
  const households = [{ id: 'home-1', name: 'Home', role: 'owner' }];
  const members = [
    { userId: 'owner-1', email: 'owner@example.com', role: 'owner' },
    { userId: 'member-1', email: 'member@example.com', role: 'member' },
  ];
  const invitations = [];
  const calls = [];
  await page.route('**/api/app/bootstrap', async (route) => {
    const response = await route.fetch();
    const data = await response.json();
    return route.fulfill({ json: {
      ...data,
      pendingInvites: [],
      access: {
        role: activeId === 'home-1' ? 'owner' : 'member',
        members: activeId === 'home-1' ? members : [], invitations,
      },
      memberships: { households, activeHouseholdId: activeId },
    } });
  });
  await page.route('**/api/households', async (route) => {
    if (route.request().method() === 'POST') {
      const payload = route.request().postDataJSON();
      calls.push(['create', payload.name]);
      households.push({ id: 'home-2', name: payload.name, role: 'member' });
      activeId = 'home-2';
    }
    return route.fulfill({ json: { households, activeHouseholdId: activeId } });
  });
  await page.route('**/api/household/invitations', (route) => {
    const email = route.request().postDataJSON().email;
    calls.push(['invite', email]);
    invitations.push({ id: 'invite-1', email, status: 'pending', expiresAt: '2030-10-01T00:00:00Z' });
    return route.fulfill({ json: { id: 'invite-1' } });
  });
  await page.route('**/api/household/invitations/invite-1', (route) => {
    calls.push(['revoke', 'invite-1']);
    invitations.length = 0;
    return route.fulfill({ json: {} });
  });
  await page.route('**/api/household/members/member-1', (route) => {
    calls.push(['remove', 'member-1']);
    members.pop();
    return route.fulfill({ json: {} });
  });
  await page.route('**/api/households/home-1/activate', (route) => {
    calls.push(['activate', 'home-1']);
    activeId = 'home-1';
    return route.fulfill({ json: {} });
  });
  await page.route('**/api/households/home-2/activate', (route) => {
    calls.push(['activate', 'home-2']);
    activeId = 'home-2';
    return route.fulfill({ json: {} });
  });
  await page.route('**/api/households/leave', (route) => {
    calls.push(['leave', 'home-2']);
    households.pop();
    activeId = 'home-1';
    return route.fulfill({ json: {} });
  });
  await page.goto('/app');
  await expect(page.locator('#household-select')).toHaveValue('home-1');
  await page.getByRole('button', { name: 'Account settings' }).click();
  await page.locator('#invite-email').fill('guest@example.com');
  await page.getByRole('button', { name: 'Create invitation' }).click();
  await expect(page.locator('#app-content')).toContainText('guest@example.com');
  page.once('dialog', (dialog) => dialog.accept());
  await page.getByRole('button', { name: 'Revoke' }).click();
  await expect(page.locator('#app-content')).not.toContainText('guest@example.com');
  page.once('dialog', (dialog) => dialog.accept());
  await page.getByRole('button', { name: 'Remove' }).click();
  await expect(page.locator('#app-content')).not.toContainText('member@example.com');
  await page.locator('#new-household-name').fill('Weekend kitchen');
  await page.getByRole('button', { name: 'Create household' }).click();
  await expect(page.locator('#household-select')).toHaveValue('home-2');
  await expect(page.locator('#app-content')).toContainText('Weekend kitchen');
  await page.locator('#household-select').selectOption('home-1');
  await expect(page.locator('#household-select')).toHaveValue('home-1');
  await page.locator('#household-select').selectOption('home-2');
  await expect(page.locator('#household-select')).toHaveValue('home-2');
  page.once('dialog', (dialog) => dialog.accept());
  await page.getByRole('button', { name: 'Leave this household' }).click();
  await expect(page.locator('#household-select')).toHaveValue('home-1');
  expect(calls).toEqual([
    ['invite', 'guest@example.com'], ['revoke', 'invite-1'], ['remove', 'member-1'],
    ['create', 'Weekend kitchen'], ['activate', 'home-1'], ['activate', 'home-2'], ['leave', 'home-2'],
  ]);
});
