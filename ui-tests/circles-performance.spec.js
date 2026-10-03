const {test, expect} = require('@playwright/test');

async function circle(page, name) {
  const response = await page.request.post('/api/circles', {data: {name}});
  expect(response.ok()).toBe(true);
  return response.json();
}

for (const viewport of [{width: 1280, height: 900}, {width: 390, height: 844}]) {
  test(`member panel preserves conversation geometry and draft at ${viewport.width}px`, async ({page}) => {
    await page.setViewportSize(viewport);
    const room = await circle(page, `Panel ${viewport.width}`);
    await page.goto(`/app?view=circles&circle=${room.id}`);
    const composer = page.getByLabel(`Message ${room.name}`);
    await composer.fill('Keep my breakfast draft');
    const before = await page.locator('.circle-timeline').boundingBox();
    await page.getByRole('button', {name: 'Members and circle settings', exact: true}).click();
    await page.getByLabel('Invite an existing friend').fill('newfriend@example.test');
    await page.getByRole('button', {name: 'Invite friend', exact: true}).click();
    await expect(page.locator('.circle-members')).toContainText('newfriend@example.test · pending');
    await page.getByRole('button', {name: 'Back to conversation'}).click();
    await expect(composer).toHaveValue('Keep my breakfast draft');
    const after = await page.locator('.circle-timeline').boundingBox();
    expect(after).toEqual(before);
    await expect(page.getByRole('button', {name: 'Send message'})).toBeInViewport();
    await page.getByRole('button', {name: 'Members and circle settings', exact: true}).click();
    await page.getByRole('button', {name: 'Cancel invite'}).click();
    await expect(page.locator('.circle-member')).toHaveCount(0);
    await page.getByRole('button', {name: 'Back to conversation'}).click();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  });
}

test('incoming activity updates while typing without replacing the composer or changing selection', async ({page}) => {
  await page.clock.install();
  const room = await circle(page, 'Typing friends');
  await page.goto(`/app?view=circles&circle=${room.id}`);
  const composer = page.getByLabel('Message Typing friends');
  await composer.fill('A draft while friends reply');
  await composer.evaluate(field => { window.originalComposer = field; field.setSelectionRange(3, 8); });
  const sent = await page.request.post(`/api/circles/${room.id}/messages`, {data: {body: 'A new message from another tab'}});
  expect(sent.ok()).toBe(true);
  await page.clock.runFor(3500);
  await expect(page.locator('.circle-post')).toContainText('A new message from another tab');
  await expect(composer).toHaveValue('A draft while friends reply');
  expect(await composer.evaluate(field => [field === window.originalComposer, document.activeElement === field, field.selectionStart, field.selectionEnd])).toEqual([true, true, 3, 8]);
});

test('cached room switches render before the network responds and retain separate drafts', async ({page}) => {
  const first = await circle(page, 'Cached breakfast');
  const second = await circle(page, 'Cached dinner');
  await page.request.post(`/api/circles/${first.id}/messages`, {data: {body: 'Breakfast history'}});
  await page.request.post(`/api/circles/${second.id}/messages`, {data: {body: 'Dinner history'}});
  await page.goto(`/app?view=circles&circle=${first.id}`);
  await expect(page.locator('.circle-post')).toContainText('Breakfast history');
  await page.getByLabel('Message Cached breakfast').fill('Breakfast draft');
  await page.locator(`.circle-room[data-id="${second.id}"]`).click();
  await expect(page.locator('.circle-post')).toContainText('Dinner history');
  await page.getByLabel('Message Cached dinner').fill('Dinner draft');
  let release;
  const held = new Promise(resolve => { release = resolve; });
  await page.route('**/api/circle-shares?circle_id=*', async route => { await held; await route.continue(); });
  await page.locator(`.circle-room[data-id="${first.id}"]`).click();
  await expect(page.locator('.circle-post')).toContainText('Breakfast history');
  await expect(page.getByLabel('Message Cached breakfast')).toHaveValue('Breakfast draft');
  await page.locator(`.circle-room[data-id="${second.id}"]`).click();
  await expect(page.locator('.circle-post')).toContainText('Dinner history');
  await expect(page.getByLabel('Message Cached dinner')).toHaveValue('Dinner draft');
  release();
  await expect(page.locator('.circle-post')).not.toContainText('Breakfast history');
});

test('send appears immediately and failure preserves draft without publishing or duplicating', async ({page}) => {
  const room = await circle(page, 'Sending friends');
  await page.goto(`/app?view=circles&circle=${room.id}`);
  let release;
  const held = new Promise(resolve => { release = resolve; });
  let fail = true;
  let attempts = 0;
  await page.route(`**/api/circles/${room.id}/messages`, async route => {
    attempts += 1;
    if (fail) { await held; await route.fulfill({status: 503, json: {detail: 'Message could not be sent'}}); }
    else await route.continue();
  });
  const composer = page.getByLabel('Message Sending friends');
  await composer.fill('Dinner is ready');
  await page.getByRole('button', {name: 'Send message'}).click();
  await expect(page.locator('.circle-post')).toContainText('Dinner is ready');
  await expect(page.locator('.circle-send-state')).toContainText('Sending');
  await composer.press('Enter');
  await expect(page.locator('.circle-post')).toHaveCount(1);
  expect(attempts).toBe(1);
  expect((await (await page.request.get(`/api/circle-shares?circle_id=${room.id}`)).json()).items).toEqual([]);
  release();
  await expect(page.locator('#toast')).toContainText('Message could not be sent');
  await expect(page.locator('.circle-post')).toHaveCount(0);
  await expect(composer).toHaveValue('Dinner is ready');
  fail = false;
  await page.getByRole('button', {name: 'Send message'}).click();
  await expect(page.locator('.circle-post')).toHaveCount(1);
  await expect(page.locator('.circle-send-state')).toHaveCount(0);
  await expect(composer).toHaveValue('');
  const posts = (await (await page.request.get(`/api/circle-shares?circle_id=${room.id}`)).json()).items;
  expect(posts.map(post => post.snapshot.text)).toEqual(['Dinner is ready']);
});

test('food search is deferred and a slow picker does not block plain chat', async ({page}) => {
  const room = await circle(page, 'Fast plain chat');
  await page.request.put('/api/recipes', {data: {title: 'Snappy breakfast', ingredients: [], instructions: ['Toast bread']}});
  let release;
  let foodRequests = 0;
  const held = new Promise(resolve => { release = resolve; });
  await page.route('**/api/recipes?*', async route => { foodRequests += 1; await held; await route.continue(); });
  await page.goto(`/app?view=circles&circle=${room.id}`, {waitUntil: 'domcontentloaded'});
  const composer = page.getByLabel('Message Fast plain chat');
  await composer.fill('No need to wait for recipes');
  await page.getByRole('button', {name: 'Send message'}).click();
  await expect(page.locator('.circle-post')).toContainText('No need to wait for recipes');
  await expect(page.locator('.circle-send-state')).toHaveCount(0);
  expect(foodRequests).toBe(0);
  await composer.pressSequentially('@recipeSnappy');
  await expect.poll(() => foodRequests).toBeGreaterThan(0);
  await expect(page.getByRole('button', {name: 'Members and circle settings', exact: true})).toBeEnabled();
  release();
  await page.locator('.mention-item').filter({hasText: 'Snappy breakfast'}).click();
  await expect(page.locator('.circle-attachment')).toContainText('Snappy breakfast');
});

test('a stale background read cannot erase a message acknowledged after it started', async ({page}) => {
  await page.clock.install();
  const room = await circle(page, 'Read race');
  await page.goto(`/app?view=circles&circle=${room.id}`);
  await expect(page.getByLabel('Message Read race')).toBeVisible();
  let release;
  let reads = 0;
  const held = new Promise(resolve => { release = resolve; });
  await page.route('**/api/circle-shares?circle_id=*', async route => {
    reads += 1; await held;
    await route.fulfill({json: {items: [], nextOffset: null}});
  });
  await page.clock.runFor(3500);
  await expect.poll(() => reads).toBeGreaterThan(0);
  await page.getByLabel('Message Read race').fill('Confirmed after the read started');
  await page.getByRole('button', {name: 'Send message'}).click();
  await expect(page.locator('.circle-send-state')).toHaveCount(0);
  await expect(page.locator('.circle-post')).toContainText('Confirmed after the read started');
  const finished = page.waitForResponse(response => response.url().includes('circle-shares?circle_id='));
  release(); await finished;
  await expect(page.locator('.circle-post')).toContainText('Confirmed after the read started');
});
