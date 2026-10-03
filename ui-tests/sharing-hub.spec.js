const {test, expect} = require('@playwright/test');

async function chooseFood(page, field, prefix, title) {
  await field.fill('');
  await field.pressSequentially(`@${prefix}`);
  await page.locator('.mention-item').filter({hasText: title}).click();
}

test('landing shows circles and direct shares, and @recipe attaches a snapshot to chat', async ({page}) => {
  const circle = await (await page.request.post('/api/circles', {data: {name: 'Supper club'}})).json();
  const recipe = await (await page.request.put('/api/recipes', {data: {
    title: 'Ginger noodles', servings: 2, ingredients: [{name: 'Noodles'}], instructions: ['Cook noodles']}})).json();
  await page.goto('/app?view=circles');
  if (await page.locator('.mobile-nav').isVisible()) await page.getByRole('button', {name: '⌂ All activity', exact: true}).click();
  await expect(page.getByRole('heading', {name: 'All activity'})).toBeVisible();
  await expect(page.locator('.circle-hub-groups')).toContainText('Supper club');
  if (await page.locator('.circle-rail').isHidden()) await page.getByRole('button', {name: '‹ Chats', exact: true}).click();
  await page.getByRole('searchbox', {name: 'Search conversations'}).fill('Supper');
  await expect(page.locator('.circle-room').filter({hasText: 'Supper club'})).toBeVisible();
  await page.getByRole('searchbox', {name: 'Search conversations'}).fill('No matching conversation');
  await expect(page.locator('.circle-room')).toHaveCount(0);
  await page.getByRole('searchbox', {name: 'Search conversations'}).fill('');
  await page.locator(`.circle-room[data-id="${circle.id}"]`).click();
  await chooseFood(page, page.getByLabel('Message Supper club'), 'recipeGinger', 'Ginger noodles');
  await expect(page.locator('.circle-attachment')).toContainText('Ginger noodles');
  await page.getByRole('button', {name: 'Send message'}).click();
  await expect(page.getByRole('region', {name: 'Review food share'})).toContainText('Ginger noodles');
  await expect(page.locator('.circle-post')).toHaveCount(0);
  await page.getByRole('button', {name: 'Confirm share'}).click();
  await expect(page.locator('.circle-post').first()).toContainText('Ginger noodles');
  const feed = await (await page.request.get(`/api/circle-shares?circle_id=${circle.id}`)).json();
  expect(feed.items[0].snapshot.recipe.id).toBe(recipe.id);
  await page.request.put('/api/recipes', {data: {id: recipe.id, title: 'Changed noodles', servings: 2,
    ingredients: [{name: 'Different ingredient'}], instructions: ['Different method']}});
  await page.getByRole('button', {name: 'Open recipe snapshot: Ginger noodles'}).click();
  await expect(page.locator('.circle-thread-panel')).toContainText('Noodles');
  await expect(page.locator('.circle-thread-panel')).toContainText('Cook noodles');
  await expect(page.locator('.circle-thread-panel')).not.toContainText('Different ingredient');
  await page.getByRole('button', {name: 'Close thread'}).click();
  await page.getByLabel('Message Supper club').pressSequentially('@demo');
  await page.locator('.mention-item').filter({hasText: 'demo'}).click();
  await page.getByRole('button', {name: 'Send message'}).click();
  await expect(page.locator('.circle-post').first()).toContainText('@demo');
  await page.locator('.circle-post').first().getByRole('button', {name: /Reply in thread/}).click();
  await expect(page.locator('.circle-thread-panel')).toContainText('@demo');
  await page.getByRole('button', {name: 'Close thread'}).click();
  if (await page.locator('.circle-rail').isHidden()) await page.getByRole('button', {name: '‹ Chats', exact: true}).click();
  else await page.getByRole('button', {name: 'All activity'}).first().click();
  if (await page.locator('.mobile-nav').isVisible()) await page.getByRole('button', {name: '⌂ All activity', exact: true}).click();
  await expect(page.locator('.circle-hub-groups')).toBeVisible();
  await expect(page.locator('.circle-hub-groups')).toContainText('@demo');
  await page.reload();
  await expect(page.locator('.circle-hub-groups')).toBeVisible();
  await expect(page.locator('.circle-hub-groups')).toContainText('@demo');
});

test('a direct @meal share opens its own private discussion without joining a circle', async ({page}) => {
  const meal = await (await page.request.put('/api/meals', {data: {name: 'Chickpea supper', servings: 2,
    components: [{name: 'Chickpeas', source: 'external', action: 'serve'}]}})).json();
  await page.goto('/app?view=circles');
  await page.getByRole('button', {name: 'Share with a friend'}).click();
  await page.getByLabel('Friend’s account email').fill('friend@example.test');
  await chooseFood(page, page.getByLabel('Food to share'), 'mealChickpea', 'Chickpea supper');
  await page.getByRole('button', {name: 'Review share'}).click();
  await expect(page.getByRole('region', {name: 'Review food share'})).toContainText('friend@example.test');
  expect((await (await page.request.get('/api/direct-shares')).json()).items).toHaveLength(0);
  await page.getByRole('button', {name: 'Confirm share'}).click();
  await expect(page.locator('.circle-hub-groups')).toContainText('Chickpea supper');
  const direct = await (await page.request.get('/api/direct-shares')).json();
  expect(direct.items[0].kind).toBe('meal');
  expect(direct.items[0].snapshot.meal.id).toBe(meal.id);
  await page.locator('.direct-room').first().click();
  await expect(page.locator('.circle-direct-detail')).toContainText('Chickpea supper');
  await page.getByLabel('Reply', {exact: true}).fill('Would this keep for lunch?');
  await page.getByRole('button', {name: 'Send reply'}).click();
  await expect(page.locator('.circle-direct-detail')).toContainText('Would this keep for lunch?');
  await page.getByRole('button', {name: 'Remove share'}).click();
  await expect(page.locator('.direct-room')).toHaveCount(0);
});

test('World manages recoverable read-only meal links and revocation', async ({page}) => {
  await page.request.put('/api/meals', {data: {name: 'Weekend toast', servings: 2,
    components: [{name: 'Toast', source: 'external', action: 'serve'}]}});
  await page.request.put('/api/recipes', {data: {title: 'Weekend jam', servings: 2,
    ingredients: [{name: 'Berries'}], instructions: ['Simmer berries']}});
  await page.goto('/app?view=circles');
  await page.getByRole('button', {name: /World is a circle/}).first().click();
  await expect(page.locator('.circle-world')).toContainText('Public links do not have comments');
  const beforeLinks = (await (await page.request.get('/api/public-shares')).json()).items.length;
  await page.getByRole('button', {name: 'Share a meal'}).click();
  await chooseFood(page, page.getByLabel('Recipe or saved meal'), 'mealWeekend', 'Weekend toast');
  await page.getByRole('button', {name: 'Create public link'}).click();
  await expect(page.getByRole('region', {name: 'Review food share'})).toContainText('Anyone with the link');
  expect((await (await page.request.get('/api/public-shares')).json()).items).toHaveLength(beforeLinks);
  await page.getByRole('button', {name: 'Create public link'}).click();
  const link = await page.getByRole('textbox', {name: 'Public link for Weekend toast'}).inputValue();
  expect(link).toContain('/s/');
  await page.reload();
  await expect(page.getByRole('textbox', {name: 'Public link for Weekend toast'})).toHaveValue(link);
  await page.goto(link);
  await expect(page.getByRole('heading', {name: 'Weekend toast'})).toBeVisible();
  await expect(page.getByText('Read only')).toBeVisible();
  await expect(page.getByRole('textbox', {name: 'Reply'})).toHaveCount(0);
  await page.goto('/app?view=circles&space=world');
  await page.locator('.circle-public-row').filter({hasText: 'Weekend toast'}).getByRole('button', {name: 'Revoke'}).click();
  await expect(page.getByRole('textbox', {name: 'Public link for Weekend toast'})).toHaveCount(0);
  await page.goto(link);
  await expect(page.getByText('Share not found or no longer available')).toBeVisible();
  await page.goto('/app?view=circles&space=world');
  await page.getByRole('button', {name: 'Share a recipe'}).click();
  await chooseFood(page, page.getByLabel('Recipe or saved meal'), 'recipeWeekend', 'Weekend jam');
  await page.getByRole('button', {name: 'Create public link'}).click();
  await page.getByRole('button', {name: 'Create public link'}).click();
  const recipeLink = await page.getByRole('textbox', {name: 'Public link for Weekend jam'}).inputValue();
  await page.goto(recipeLink);
  await expect(page.getByRole('heading', {name: 'Weekend jam'})).toBeVisible();
  await expect(page.getByRole('textbox', {name: 'Reply'})).toHaveCount(0);
});

test('direct weekly plan is reviewed before a friend receives the whole snapshot', async ({page}) => {
  const week = '2030-02-04';
  const response = await page.request.put('/api/meal-plan', {data: {weekStart: week,
    entries: [{date: week, slot: 'breakfast', meal: 'Overnight oats', notes: 'Personal note shared with friend',
      components: [{name: 'Milk', source: 'external', action: 'serve'}]},
      {date: week, slot: 'dinner', meal: 'Rice bowls'}],
    tasks: [{title: 'Private prep task'}]}});
  expect(response.ok()).toBe(true);
  await page.goto('/app?view=circles');
  await page.getByRole('button', {name: 'Share a week'}).click();
  await page.getByLabel('Friend’s account email').fill('friend@example.test');
  await page.getByLabel('Week starting Monday').fill(week);
  await page.getByRole('button', {name: 'Review week'}).click();
  await expect(page.locator('.circle-review')).toContainText('Overnight oats');
  await expect(page.locator('.circle-review')).toContainText('Rice bowls');
  await expect(page.locator('.circle-review')).toContainText('Personal note shared with friend');
  await expect(page.locator('.circle-review')).toContainText('Included food: Milk');
  const before = await (await page.request.get('/api/direct-shares')).json();
  await page.getByRole('button', {name: 'Publish to friend'}).click();
  await expect(page.locator('.direct-room').first()).toContainText('Week of');
  const after = await (await page.request.get('/api/direct-shares')).json();
  expect(after.count).toBe(before.count + 1);
  expect(after.items[0].snapshot.entries.map(item => item.meal)).toEqual(['Overnight oats', 'Rice bowls']);
  expect(JSON.stringify(after.items[0].snapshot)).not.toContain('Private prep task');
});

test('food review prevents an accidental or stale circle share', async ({page}) => {
  const circle = await (await page.request.post('/api/circles', {data: {name: 'Careful sharing'}})).json();
  const recipe = await (await page.request.put('/api/recipes', {data: {
    title: 'Private soup', servings: 2, ingredients: [{name: 'Peas'}], instructions: ['Simmer']}})).json();
  await page.goto(`/app?view=circles&circle=${circle.id}`);
  await chooseFood(page, page.getByLabel('Message Careful sharing'), 'recipePrivate', 'Private soup');
  await page.getByRole('button', {name: 'Send message'}).click();
  await expect(page.getByRole('region', {name: 'Review food share'})).toContainText('Private soup');
  await page.getByRole('button', {name: 'Cancel', exact: true}).click();
  expect((await (await page.request.get(`/api/circle-shares?circle_id=${circle.id}`)).json()).items).toHaveLength(0);
  await chooseFood(page, page.getByLabel('Message Careful sharing'), 'recipePrivate', 'Private soup');
  await page.getByRole('button', {name: 'Send message'}).click();
  await page.request.put('/api/recipes', {data: {id: recipe.id, title: 'Updated soup', servings: 2,
    ingredients: [{name: 'Peas'}, {name: 'Milk'}], instructions: ['Simmer']}});
  await page.getByRole('button', {name: 'Confirm share'}).click();
  await expect(page.locator('#toast')).toContainText('food changed');
  expect((await (await page.request.get(`/api/circle-shares?circle_id=${circle.id}`)).json()).items).toHaveLength(0);
});

test('mobile opens one chat from the conversation list and returns to the list', async ({page}) => {
  await page.setViewportSize({width: 390, height: 844});
  const circle = await (await page.request.post('/api/circles', {data: {name: 'Mobile supper'}})).json();
  await page.goto('/app?view=circles');
  await expect(page.locator('.circle-rail')).toBeVisible();
  await expect(page.locator('.circle-hub')).toBeHidden();
  await page.locator(`.circle-room[data-id="${circle.id}"]`).click();
  await expect(page.locator('.circle-rail')).toBeHidden();
  await page.getByLabel('Message Mobile supper').fill('Dinner is served');
  await page.getByRole('button', {name: 'Send message'}).click();
  await expect(page.locator('.circle-post').first()).toContainText('Dinner is served');
  await page.getByRole('button', {name: '‹ Chats'}).click();
  await expect(page.locator('.circle-rail')).toBeVisible();
  await expect(page.locator(`.circle-room[data-id="${circle.id}"]`)).toContainText('Dinner is served');
});
