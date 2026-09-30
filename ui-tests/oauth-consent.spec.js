const { test, expect } = require('@playwright/test');

test('OAuth consent handles a missing request and escapes displayed scopes', async ({ page }) => {
  await page.goto('/oauth/consent');
  await expect(page.locator('#message')).toHaveText('Missing authorization request.');

  await page.route('**/api/auth/config', (route) => route.fulfill({ json: {
    supabaseUrl: 'https://example.supabase.co', supabaseAnonKey: 'public-test-key', authRequired: true,
  } }));
  await page.route('**/static/vendor/supabase.js', (route) => route.fulfill({
    contentType: 'application/javascript',
    body: `window.supabase = { createClient: () => ({ auth: {
      getSession: async () => ({ data: { session: { access_token: 'fake-token' } } }),
      oauth: {
        getAuthorizationDetails: async () => ({ data: { client: { name: 'Test client' }, scope: 'openid <img>' }, error: null }),
        approveAuthorization: async () => ({ data: { redirect_url: window.unsafeCallback ? 'http://example.test/not-allowed' : 'http://127.0.0.1:18765/oauth-done?decision=approve' }, error: null }),
        denyAuthorization: async () => ({ data: { redirect_url: 'http://127.0.0.1:18765/oauth-done?decision=deny' }, error: null }),
      },
    } }) };`,
  }));
  await page.route('**/oauth-done*', (route) => route.fulfill({ contentType: 'text/html', body: '<h1>Returned to client</h1>' }));

  for (const [button, decision] of [['Allow access', 'approve'], ['Deny', 'deny']]) {
    await page.goto('/oauth/consent?authorization_id=test-request');
    await expect(page.locator('#summary')).toContainText('Test client');
    await expect(page.locator('#scopes')).toContainText('<img>');
    await expect(page.locator('#scopes img')).toHaveCount(0);
    if (decision === 'approve') {
      await page.evaluate(() => { window.unsafeCallback = true; });
      await page.getByRole('button', { name: button }).click();
      await expect(page.locator('#message')).toContainText('unsupported callback URL');
      await expect(page.getByRole('button', { name: button })).toBeVisible();
      await page.evaluate(() => { window.unsafeCallback = false; });
    }
    await page.getByRole('button', { name: button }).click();
    await expect(page).toHaveURL(new RegExp(`decision=${decision}`));
  }
});

test('OAuth consent sends unsigned users to sign-in', async ({ page }) => {
  await page.route('**/api/auth/config', (route) => route.fulfill({ json: {
    supabaseUrl: 'https://example.supabase.co', supabaseAnonKey: 'public-test-key', authRequired: true,
  } }));
  await page.route('**/static/vendor/supabase.js', (route) => route.fulfill({
    contentType: 'application/javascript',
    body: `window.supabase = { createClient: () => ({ auth: {
      getSession: async () => ({ data: { session: null } }),
      onAuthStateChange: () => ({ data: { subscription: { unsubscribe() {} } } }),
    } }) };`,
  }));
  await page.goto('/oauth/consent?authorization_id=needs-login');
  await expect(page).toHaveURL(/\/login\?next=/);
  await expect(page.locator('#login-form')).toBeVisible();
});
