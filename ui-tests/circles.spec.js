const {test, expect} = require('@playwright/test');

async function countSharesInCircle(page, circleId) {
  const feed = await (await page.request.get('/api/circle-shares?limit=100')).json();
  return feed.items.filter(item => item.circleId === circleId).length;
}

test('Circle feed shares a whole week and recipe, supports discussion and saving food', async ({page}) => {
  await page.setViewportSize({width: 390, height: 844});
  await page.goto('/app?view=circles');
  await page.getByRole('button', {name: 'Create circle'}).click();
  await page.getByLabel('Circle name').fill('Friday friends');
  await page.getByRole('button', {name: 'Create', exact: true}).click();
  await expect(page.locator('.circle-card')).toContainText('Friday friends');
  await page.getByLabel('Invite an existing friend').fill('friend@example.test');
  await page.getByRole('button', {name: 'Invite friend'}).click();
  await expect(page.locator('.circle-members')).toContainText('friend@example.test · pending');
  await page.getByLabel('Invite an existing friend').fill('friend@example.test');
  await page.getByRole('button', {name: 'Invite friend'}).click();
  await expect(page.locator('#toast')).toContainText('Friend is already invited or a member');
  await page.getByRole('button', {name: 'Cancel invite'}).click();
  await expect(page.locator('.circle-members')).toHaveCount(0);
  await page.locator('.circle-card').filter({hasText: 'Friday friends'}).getByRole('button', {name: 'Share this week'}).click();
  await expect(page.locator('.circle-review')).toContainText('Review before sharing');
  await page.getByRole('button', {name: 'Publish week'}).click();
  await expect(page.locator('.circle-post').first()).toContainText('Weekly plan');
  await page.locator('.circle-post').first().getByRole('button', {name: 'View discussion'}).click();
  await expect(page.locator('.circle-detail')).toContainText('Tomato pasta');
  await page.getByLabel('Comment', {exact: true}).fill('What went well this week?');
  await page.getByRole('button', {name: 'Post comment'}).click();
  await expect(page.locator('.circle-detail')).toContainText('What went well this week?');
  await page.getByRole('button', {name: 'Remove comment'}).click();
  await expect(page.locator('.circle-comment')).toHaveCount(0);
  await page.getByRole('button', {name: 'Back to circle'}).click();
  await page.locator('.circle-card').filter({hasText: 'Friday friends'}).getByRole('button', {name: 'Share a recipe'}).click();
  await page.getByLabel('Recipe to share').selectOption({label: 'Paneer rice bowls'});
  await page.getByRole('button', {name: 'Share recipe', exact: true}).click();
  await expect(page.locator('.circle-post').first()).toContainText('Paneer rice bowls');
  await page.locator('.circle-post').first().getByRole('button', {name: 'View discussion'}).click();
  await page.getByRole('button', {name: 'Save recipe'}).click();
  await expect(page.locator('.circle-detail')).toContainText('Open saved recipe');
  await page.reload();
  await expect(page.locator('.circle-detail')).toContainText('Open saved recipe');
  await page.getByRole('button', {name: 'Open saved recipe'}).click();
  await expect(page).toHaveURL(/view=recipes/);
  await expect(page.locator('.hero')).toContainText('Paneer rice bowls');
  await page.goBack();
  await expect(page.locator('.circle-detail')).toBeVisible();
  await page.getByRole('button', {name: 'Back to circle'}).click();
  await expect(page.locator('.circle-post')).toHaveCount(2);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});

test('a shared week exposes its linked recipe snapshot for an independent save', async ({page}) => {
  const recipe = await (await page.request.put('/api/recipes', {data: {title: 'Circle breakfast oats',
    servings: 2, ingredients: [{name: 'Oats', quantity: 1, unit: 'cup'}], instructions: ['Simmer oats']}})).json();
  const week = '2030-02-04';
  const planResponse = await page.request.put('/api/meal-plan', {data: {weekStart: week, entries: [{
    date: week, slot: 'breakfast', meal: 'Oat bowls', components: [{name: 'Circle breakfast oats',
      quantity: 2, unit: 'servings', source: 'cook', recipeId: recipe.id}]}]}});
  expect(planResponse.ok()).toBe(true);
  await page.goto(`/app?view=plan&week=${week}`);
  await page.locator('.sidebar [data-view="circles"]').click();
  await page.getByRole('button', {name: 'Create circle'}).click();
  await page.getByLabel('Circle name').fill('Breakfast circle');
  await page.getByRole('button', {name: 'Create', exact: true}).click();
  await page.locator('.circle-card').filter({hasText: 'Breakfast circle'}).getByRole('button', {name: 'Share this week'}).click();
  await expect(page.locator('.circle-review')).toContainText('Oat bowls');
  await page.getByRole('button', {name: 'Publish week'}).click();
  await page.locator('.circle-post').first().getByRole('button', {name: 'View discussion'}).click();
  await expect(page.locator('.circle-detail')).toContainText('Oat bowls');
  await expect(page.locator('.circle-detail')).toContainText('Simmer oats');
  await page.getByRole('button', {name: 'Save recipe'}).click();
  await expect(page.locator('.circle-detail')).toContainText('Open saved recipe');
  await page.reload();
  await expect(page.locator('.circle-detail')).toContainText('Simmer oats');
  await expect(page.locator('.circle-detail')).toContainText('Open saved recipe');
  const savedId = await page.getByRole('button', {name: 'Open saved recipe'}).getAttribute('data-id');
  expect((await page.request.delete(`/api/recipes/${savedId}`)).ok()).toBe(true);
  await page.reload();
  await expect(page.getByRole('button', {name: 'Save recipe'})).toBeVisible();
  await page.getByRole('button', {name: 'Save recipe'}).click();
  const replacementId = await page.getByRole('button', {name: 'Open saved recipe'}).getAttribute('data-id');
  expect(replacementId).not.toBe(savedId);
  await page.getByRole('button', {name: 'Back to circle'}).click();
  await page.goto(`/app?view=plan&week=${week}`);
  await page.locator('.sidebar [data-view="circles"]').click();
  await page.locator('.circle-card').filter({hasText: 'Breakfast circle'}).getByRole('button', {name: 'Share this week'}).click();
  await page.getByRole('button', {name: 'Publish week'}).click();
  await page.locator('.circle-post').first().getByRole('button', {name: 'View discussion'}).click();
  await expect(page.getByRole('button', {name: 'Open saved recipe'})).toHaveAttribute('data-id', replacementId);
});

test('a circle notification opens the exact shared week', async ({page}) => {
  const circle = await (await page.request.post('/api/circles', {data: {name: 'Notification friends'}})).json();
  const plan = await (await page.request.get('/api/meal-plan')).json();
  const share = await (await page.request.post(`/api/circles/${circle.id}/weeks`, {data: {weekStart: plan.plan.weekStart}})).json();
  const notificationId = '00000000-0000-0000-0000-000000000099';
  let read = false;
  await page.route('**/api/notifications', route => route.fulfill({json: {items: [{id: notificationId,
    household_id: null, kind: 'circle_share', title: 'A friend shared a weekly meal plan',
    target_path: `/app?view=circles&share=${share.id}`, created_at: new Date().toISOString(),
    read_at: read ? new Date().toISOString() : null}], unreadCount: read ? 0 : 1}}));
  await page.route(`**/api/notifications/${notificationId}/read`, route => {
    read = true;
    return route.fulfill({json: {id: notificationId, readAt: new Date().toISOString()}});
  });
  await page.goto('/app');
  await page.getByRole('button', {name: 'Notifications, 1 unread'}).click();
  await page.getByRole('button', {name: 'Open', exact: true}).click();
  await expect(page).toHaveURL(new RegExp(`view=circles&share=${share.id}`));
  await expect(page.locator('.circle-detail')).toContainText(plan.plan.entries[0].meal);
  await expect(page.locator('#notification-count')).toBeHidden();
});

test('the Circle feed can reveal older shares beyond the first page', async ({page}) => {
  const circle = await (await page.request.post('/api/circles', {data: {name: 'Older shares circle'}})).json();
  const recipeId = '11111111-1111-1111-1111-111111111111';
  for (let index = 0; index < 51; index++) {
    const response = await page.request.post(`/api/circles/${circle.id}/recipes`, {data: {recipeId}});
    expect(response.ok()).toBe(true);
  }
  await page.goto('/app?view=circles');
  await expect(page.locator('.circle-post')).toHaveCount(50);
  await page.getByRole('button', {name: 'Show older shares'}).click();
  await expect.poll(() => page.locator('.circle-post').count()).toBeGreaterThan(50);
});

test('reviewing a whole week can be cancelled without publishing and shows meal notes', async ({page}) => {
  const week = '2030-02-04';
  const note = 'Dinner is later after soccer';
  const response = await page.request.put('/api/meal-plan', {data: {weekStart: week, entries: [
    {date: week, slot: 'dinner', meal: 'Pasta night', notes: note, components: [{name: 'Tomatoes'}]},
    {date: week, slot: 'snack', meal: 'Fruit plate', notes: 'For the kids'}
  ]}});
  expect(response.ok()).toBe(true);
  await page.goto(`/app?view=plan&week=${week}`);
  await page.locator('.sidebar [data-view="circles"]').click();
  await page.getByRole('button', {name: 'Create circle'}).click();
  await page.getByLabel('Circle name').fill('Review circle');
  await page.getByRole('button', {name: 'Create', exact: true}).click();
  const card = page.locator('.circle-card').filter({hasText: 'Review circle'});
  const circleId = await card.getByRole('button', {name: 'Share this week'}).getAttribute('data-id');
  const before = await countSharesInCircle(page, circleId);
  await card.getByRole('button', {name: 'Share this week'}).click();
  await expect(page.locator('.circle-review')).toContainText(note);
  await expect(page.locator('.circle-review')).toContainText('Fruit plate');
  await expect(page.locator('.circle-review')).toContainText('Pantry stock, prep tasks, and shopping stay private');
  await page.getByRole('button', {name: 'Cancel', exact: true}).click();
  expect(await countSharesInCircle(page, circleId)).toBe(before);
  await card.getByRole('button', {name: 'Share this week'}).click();
  await page.getByRole('button', {name: 'Publish week'}).click();
  await expect.poll(() => countSharesInCircle(page, circleId)).toBe(before + 1);
});

test('friend supplied HTML in a share and comment is rendered as text', async ({page}) => {
  const attack = '<img src=x onerror="window.circleXss=1">';
  const circle = await (await page.request.post('/api/circles', {data: {name: attack}})).json();
  const recipe = await (await page.request.put('/api/recipes', {data: {title: attack, ingredients: [], instructions: ['<script>window.circleXss=1</script>']}})).json();
  const post = await (await page.request.post(`/api/circles/${circle.id}/recipes`, {data: {recipeId: recipe.id}})).json();
  expect((await page.request.post(`/api/circle-shares/${post.id}/comments`, {data: {body: attack}})).ok()).toBe(true);
  await page.goto(`/app?view=circles&share=${post.id}`);
  await expect(page.locator('.circle-detail')).toContainText(attack);
  await expect(page.locator('.circle-detail img, .circle-detail script')).toHaveCount(0);
  expect(await page.evaluate(() => window.circleXss)).toBeUndefined();
});

test('a changed week must be reviewed again before publication', async ({page}) => {
  const week = '2030-02-04';
  expect((await page.request.put('/api/meal-plan', {data: {weekStart: week, entries: [
    {date: week, slot: 'dinner', meal: 'First version'}]}})).ok()).toBe(true);
  const circle = await (await page.request.post('/api/circles', {data: {name: 'Changing plan'}})).json();
  await page.goto(`/app?view=plan&week=${week}`);
  await page.locator('.sidebar [data-view="circles"]').click();
  const before = await countSharesInCircle(page, circle.id);
  await page.locator('.circle-card').filter({hasText: 'Changing plan'}).getByRole('button', {name: 'Share this week'}).click();
  await expect(page.locator('.circle-review')).toContainText('First version');
  expect((await page.request.put('/api/meal-plan', {data: {weekStart: week, entries: [
    {date: week, slot: 'dinner', meal: 'Second version'}]}})).ok()).toBe(true);
  await page.getByRole('button', {name: 'Publish week'}).click();
  await expect(page.locator('#toast')).toContainText('Review it again');
  await expect(page.locator('.circle-review')).toContainText('Second version');
  expect(await countSharesInCircle(page, circle.id)).toBe(before);
  await page.getByRole('button', {name: 'Publish week'}).click();
  await expect.poll(() => countSharesInCircle(page, circle.id)).toBe(before + 1);
  const feed = await (await page.request.get('/api/circle-shares')).json();
  expect(feed.items.find(item => item.circleId === circle.id).snapshot.entries[0].meal).toBe('Second version');
});

test('a comment flood is rejected without adding a thirty-first comment', async ({page}) => {
  const circle = await (await page.request.post('/api/circles', {data: {name: 'Busy discussion'}})).json();
  const post = await (await page.request.post(`/api/circles/${circle.id}/recipes`,
    {data: {recipeId: '11111111-1111-1111-1111-111111111111'}})).json();
  for (let index = 0; index < 30; index++) {
    expect((await page.request.post(`/api/circle-shares/${post.id}/comments`,
      {data: {body: `Thought ${index}`}})).ok()).toBe(true);
  }
  await page.goto(`/app?view=circles&share=${post.id}`);
  await expect(page.locator('.circle-comment')).toHaveCount(30);
  await page.getByLabel('Comment', {exact: true}).fill('One more thought');
  await page.getByRole('button', {name: 'Post comment'}).click();
  await expect(page.locator('#toast')).toContainText('Comment rate limit reached');
  await expect(page.locator('.circle-comment')).toHaveCount(30);
  expect((await (await page.request.get(`/api/circle-shares/${post.id}`)).json()).comments).toHaveLength(30);
});
