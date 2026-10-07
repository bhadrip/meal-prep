const {test, expect} = require('@playwright/test');

test('chat searches people before food and scrolls through a large food library', async ({page}) => {
  const existing = (await (await page.request.get('/api/circles')).json()).items.find(item => item.myStatus === 'accepted');
  const circle = existing || await (await page.request.post('/api/circles', {data: {name: 'Large food library chat'}})).json();
  const recipeIds = [];
  try {
    for (let index = 0; index < 110; index++) {
      const recipe = await (await page.request.put('/api/recipes', {data: {title: `Bulk recipe ${String(index).padStart(3, '0')}`}})).json();
      recipeIds.push(recipe.id);
    }
    const recipe = await (await page.request.put('/api/recipes', {data: {title: 'Quinoa herb bowls'}})).json();
    const ready = await (await page.request.put('/api/recipes', {data: {title: 'Quinoa snack cup', kind: 'ready_food'}})).json();
    const described = await (await page.request.put('/api/recipes', {data: {
      title: 'Korean tofu rice bowls', description: 'Serve with quinoa'}})).json();
    const ingredient = await (await page.request.put('/api/recipes', {data: {
      title: 'No-cook couscous bowls', ingredients: [{name: 'quinoa'}]}})).json();
    recipeIds.push(recipe.id, ready.id, described.id, ingredient.id);
    const meal = await (await page.request.put('/api/meals', {data: {name: 'Quinoa family supper', servings: 2,
      components: [{name: recipe.title, source: 'cook', recipeId: recipe.id}]}})).json();

    await page.goto(`/app?view=circles&circle=${circle.id}`);
    const message = page.getByLabel(`Message ${circle.name}`);
    const dropdown = page.locator('.mention-dropdown.active');
    await message.pressSequentially('@');
    await expect(dropdown.locator('.mention-item[data-index]').first()).toContainText('Person');
    await expect(dropdown.locator('.mention-item[data-index]').nth(1)).toContainText('Recipe');
    await message.pressSequentially('qui');
    for (const name of [recipe.title, ready.title, meal.name]) {
      await expect(dropdown.locator('.mention-item').filter({hasText: name})).toBeVisible();
    }
    await message.pressSequentially('noa');
    await expect(dropdown.locator('.mention-item').filter({hasText: recipe.title})).toBeVisible();
    for (const name of [described.title, ingredient.title]) {
      await expect(dropdown.locator('.mention-item').filter({hasText: name})).toHaveCount(0);
    }
    await dropdown.locator('.mention-item').filter({hasText: ready.title}).click();
    await expect(page.locator('#circle-message-form .circle-attachment')).toContainText('Ready food attached: Quinoa snack cup');
    await page.getByRole('button', {name: 'Send message'}).click();
    await page.getByRole('button', {name: 'Confirm share'}).click();
    await expect(page.locator('.circle-post').last()).toContainText(ready.title);
    const shared = (await (await page.request.get(`/api/circle-shares?circle_id=${circle.id}`)).json()).items;
    expect(shared.find(post => post.snapshot.recipe?.id === ready.id)).toBeTruthy();

    await message.fill('');
    await message.pressSequentially('@Bulk');
    await expect(dropdown.locator('.mention-item[data-index]')).toHaveCount(25);
    expect(await dropdown.evaluate(el => el.scrollHeight > el.clientHeight)).toBe(true);
    for (const count of [50, 75, 100, 110]) {
      await dropdown.evaluate(el => {el.scrollTop = el.scrollHeight;});
      await expect(dropdown.locator('.mention-item[data-index]')).toHaveCount(count);
    }
    await dropdown.locator('.mention-item').filter({hasText: 'Bulk recipe 109'}).click();
    await expect(page.locator('#circle-message-form .circle-attachment')).toContainText('Bulk recipe 109');
    await page.getByRole('button', {name: 'Send message'}).click();
    await page.getByRole('button', {name: 'Confirm share'}).click();
    await expect(page.locator('.circle-post').last()).toContainText('Bulk recipe 109');
    expect((await (await page.request.get(`/api/circle-shares?circle_id=${circle.id}`)).json()).items
      .some(post => post.snapshot.recipe?.id === recipeIds[109])).toBe(true);

    await page.getByRole('button', {name: '+ Share', exact: true}).click();
    await page.getByRole('button', {name: 'Share a recipe', exact: true}).click();
    const search = page.getByRole('searchbox', {name: 'Search your food library'});
    await search.fill('quinoa');
    const panel = page.getByRole('region', {name: 'Food suggestions'});
    await expect(panel.locator('.chat-food-option').filter({hasText: recipe.title})).toBeVisible();
    for (const name of [described.title, ingredient.title]) {
      await expect(panel.locator('.chat-food-option').filter({hasText: name})).toHaveCount(0);
    }
    await search.fill('Bulk recipe');
    await expect(panel.locator('.chat-food-option')).toHaveCount(25);
    expect(await panel.evaluate(el => el.scrollHeight > el.clientHeight)).toBe(true);
    for (const count of [50, 75, 100, 110]) {
      await panel.getByRole('button', {name: 'Show more food'}).click();
      await expect(panel.locator('.chat-food-option')).toHaveCount(count);
    }
    await panel.getByRole('button', {name: 'Bulk recipe 108 Recipe'}).click();
    await expect(page.getByRole('region', {name: 'Review food share'})).toContainText('Bulk recipe 108');
    await page.getByRole('button', {name: 'Confirm share'}).click();
    await expect(page.locator('.circle-post').last()).toContainText('Bulk recipe 108');
  } finally {
    for (const id of recipeIds) await page.request.delete(`/api/recipes/${id}`);
  }
});
