const { test, expect } = require('@playwright/test');

const recipe = {
  id: 'recipe-ui-test', title: 'Lentil bowls', description: 'Simple family dinner',
  ingredients: [{ name: 'Lentils', quantity: 2, unit: 'cups' }],
  instructions: ['Cook lentils', 'Serve warm'], tags: ['weeknight'], servings: 4,
};

async function host(page, live = false) {
  await page.route('**/mcp-test-host', (route) => route.fulfill({
    contentType: 'text/html',
    body: `<!doctype html><html><body><iframe src="/static/mcp-app.html" style="width:100%;height:900px;border:0"></iframe>
      <script>
        window.calls = [];
        window.ready = false;
        window.revoked = false;
        window.addEventListener('message', async (event) => {
          const message = event.data;
          if (message?.jsonrpc !== '2.0' || !message.method) return;
          if (message.method === 'ui/notifications/initialized') { window.ready = true; return; }
          if (message.method === 'ui/initialize') {
            event.source.postMessage({ jsonrpc: '2.0', id: message.id, result: {} }, '*');
            return;
          }
          if (message.method !== 'tools/call') return;
          window.calls.push(message.params);
          if (${JSON.stringify(live)}) {
            const response = await fetch('/mcp', {
              method: 'POST',
              headers: { 'Content-Type': 'application/json', Accept: 'application/json, text/event-stream' },
              body: JSON.stringify({ jsonrpc: '2.0', id: message.id, method: 'tools/call', params: message.params }),
            });
            const payload = await response.json();
            event.source.postMessage({ ...payload, id: message.id }, '*');
            return;
          }
          const name = message.params.name;
          let result = {};
          if (name === 'get_recipe') result = ${JSON.stringify(recipe)};
          if (name === 'search_recipes') {
            const query = String(message.params.arguments.query || '').toLowerCase();
            const tag = String(message.params.arguments.tag || '').toLowerCase();
            const items = (window.mcpRecipes || []).filter((item) =>
              (!tag || item.tags?.some((value) => value.toLowerCase() === tag)) &&
              (!query || [item.title, item.description, ...(item.tags || [])].some((value) => String(value || '').toLowerCase().includes(query))));
            result = { items, count: items.length };
          }
          if (name === 'create_recipe_share') result = { url: 'https://example.test/s/share-test' };
          if (name === 'revoke_recipe_share') window.revoked = true;
          if (name === 'list_recipe_shares') result = { items: window.revoked ? [] : [{ id: 'share-test', recipeId: 'recipe-ui-test', createdAt: '2026-09-30T00:00:00Z' }] };
          if (name === 'update_household_preferences') result = { onboardingCompletedAt: '2026-09-30T00:00:00Z' };
          if (name === 'record_pantry_use') result = { itemId: 'spinach-1', name: 'Spinach', quantityBefore: 1, quantityRemaining: 0.5, unit: 'bag', recipeTitle: 'Lentil bowls', item: { id: 'spinach-1', name: 'Spinach', quantity: 0.5, unit: 'bag', reference_quantity: 1 } };
          event.source.postMessage({ jsonrpc: '2.0', id: message.id, result: { structuredContent: result } }, '*');
        });
      </script></body></html>`,
  }));
  await page.goto('/mcp-test-host');
  await expect.poll(() => page.evaluate(() => window.ready)).toBe(true);
  return page.frameLocator('iframe');
}

async function show(page, data) {
  await page.evaluate((payload) => {
    if (payload.kind === 'recipe_library') window.mcpRecipes = payload.allRecipes || payload.recipes;
    document.querySelector('iframe').contentWindow.postMessage({
      jsonrpc: '2.0', method: 'ui/notifications/tool-result', params: { structuredContent: payload },
    }, '*');
  }, data);
}

test('MCP dashboard, plan, feedback, and shopping views', async ({ page }) => {
  const frame = await host(page);
  const sections = {
    recipes: { status: 'ok', value: [recipe] },
    pantry: { status: 'ok', value: [{ name: 'Spinach', quantity: 1, unit: 'bag' }] },
    mealPlan: { status: 'ok', value: { weekStart: '2026-09-28', entries: [{ day: 'Monday', meal: 'Lentil bowls', servings: 4 }] } },
    shoppingList: { status: 'ok', value: { name: 'Weekly groceries', items: [{ id: 'item-1', name: 'Lentils', store: 'Costco', purchased: false }] } },
    feedback: { status: 'ok', value: [{ note: 'Kids liked it', meal_title: 'Lentil bowls', feedback_type: 'worked_well' }] },
    memories: { status: 'ok', value: [{ content: 'Serve sauce separately', status: 'confirmed' }] },
    schedule: { status: 'ok', value: { days: [{ day: 'Monday', mode: 'quick' }] } },
  };
  await show(page, { kind: 'household_snapshot', household: { householdName: 'Test kitchen', householdSize: 4 }, sections });
  await expect(frame.getByRole('heading', { name: 'Test kitchen' })).toBeVisible();
  await expect(frame.locator('.dashboard-grid')).toContainText('Lentil bowls');
  await expect(frame.locator('.dashboard-grid')).toContainText('Spinach');
  await show(page, { kind: 'meal_plan', plan: sections.mealPlan.value });
  await expect(frame.getByRole('heading', { name: 'Weekly meal plan' })).toBeVisible();
  await expect(frame.locator('.day')).toContainText('Lentil bowls');
  await show(page, { kind: 'feedback', sections: { feedback: sections.feedback } });
  await expect(frame.locator('.feedback-list')).toContainText('Kids liked it');
  await show(page, { kind: 'shopping_list', shoppingList: sections.shoppingList.value });
  await frame.getByRole('checkbox').check();
  await expect(frame.locator('label.done')).toContainText('Lentils');
  await expect.poll(() => page.evaluate(() => window.calls.at(-1))).toEqual({
    name: 'mark_item_purchased', arguments: { item_id: 'item-1', purchased: true },
  });
  await frame.getByRole('checkbox').uncheck();
  await expect(frame.locator('label.done')).toHaveCount(0);
  await expect.poll(() => page.evaluate(() => window.calls.at(-1))).toEqual({
    name: 'mark_item_purchased', arguments: { item_id: 'item-1', purchased: false },
  });
});

test('MCP pantry use updates the remaining amount', async ({ page }) => {
  const frame = await host(page);
  await show(page, { kind: 'household_snapshot', household: { householdName: 'Test kitchen' }, sections: {
    pantry: { status: 'ready', value: [{ id: 'spinach-1', name: 'Spinach', quantity: 1, unit: 'bag', reference_quantity: 1 }] },
    recipes: { status: 'ready', value: [recipe] },
  } });
  await frame.getByRole('button', { name: 'Use' }).click();
  await frame.locator('#pantry-use-form input[name="quantity"]').fill('0.5');
  await frame.locator('#pantry-use-form select[name="recipeId"]').selectOption('recipe-ui-test');
  await frame.getByRole('button', { name: 'Record use' }).click();
  await expect(frame.locator('[data-card-id="pantry"]')).toContainText('0.5 bag left');
  await expect(frame.locator('[data-card-id="pantry"] [role="meter"]')).toHaveAttribute('aria-valuenow', '50');
  await expect.poll(() => page.evaluate(() => window.calls.at(-1))).toEqual({
    name: 'record_pantry_use', arguments: { item_id: 'spinach-1', quantity: 0.5, recipe_id: 'recipe-ui-test', meal_title: null },
  });
});

test('MCP pantry category filters and search narrow the saved inventory', async ({ page }) => {
  const frame = await host(page);
  await show(page, { kind: 'household_snapshot', household: { householdName: 'Test kitchen' }, sections: {
    pantry: { status: 'ready', value: [
      { id: 'chili-1', name: 'Chili oil', category: 'condiments', quantity: 1, unit: 'jar' },
      { id: 'apple-1', name: 'Apples', category: 'fruits', quantity: 3, unit: 'each' },
      { id: 'mystery-1', name: 'Mystery tin', category: 'uncategorized', quantity: 1, unit: 'tin' },
    ] },
  } });
  const card = frame.locator('[data-card-id="pantry"]');
  await card.locator('[data-pantry-category="condiments"]').click();
  await expect(card.locator('.pantry-row')).toHaveCount(1);
  await expect(card.locator('.pantry-row')).toContainText('Chili oil');
  await card.locator('[data-pantry-category="uncategorized"]').click();
  await expect(card.locator('.pantry-row')).toContainText('Mystery tin');
  await card.locator('[data-pantry-category="all"]').click();
  await card.locator('#mcp-pantry-search').fill('apple');
  await expect(card.locator('.pantry-row')).toHaveCount(1);
  await expect(card.locator('.pantry-row')).toContainText('Apples');
  await card.locator('#mcp-pantry-search').fill('missing');
  await expect(card.locator('.pantry-row')).toHaveCount(0);
  await expect(card).toContainText('No matching items.');
});

test('MCP onboarding and recipe library actions', async ({ page }) => {
  const frame = await host(page);
  await show(page, { kind: 'onboarding', household: {} });
  await expect(frame.getByRole('heading', { name: 'Feeding a family takes planning.' })).toBeVisible();
  await frame.getByRole('button', { name: 'Save household setup' }).click();
  await expect(frame.locator('[name="householdSize"]')).toBeFocused();
  await frame.locator('[name="householdSize"]').fill('3');
  await frame.locator('[name="dietaryRestrictions"]').fill('none');
  await frame.locator('[name="stores"]').fill('Costco, Safeway');
  await frame.locator('[name="focusAreas"][value="dinners"]').check();
  await frame.getByRole('button', { name: 'Save household setup' }).click();
  await expect(frame.getByRole('heading', { name: 'Your household setup is saved.' })).toBeVisible();
  await expect.poll(() => page.evaluate(() => window.calls.at(-1))).toMatchObject({
    name: 'update_household_preferences', arguments: { household_size: 3, store_priority: [{ store: 'Costco', priority: 1 }, { store: 'Safeway', priority: 2 }], complete_onboarding: true },
  });
  await show(page, { kind: 'recipe_library', recipes: [recipe] });
  await frame.getByRole('searchbox', { name: 'Search recipes' }).fill('missing');
  await expect(frame.getByText('No matching recipes')).toBeVisible();
  await frame.getByRole('searchbox', { name: 'Search recipes' }).fill('Lentil');
  await frame.getByRole('button', { name: 'Open Lentil bowls' }).click();
  await expect(frame.getByRole('heading', { name: 'Ingredients' })).toBeVisible();
  await frame.getByRole('button', { name: 'Create share link' }).click();
  await expect(frame.getByRole('textbox', { name: 'Share link' })).toHaveValue('https://example.test/s/share-test');
  await frame.getByRole('button', { name: 'Copy link' }).click();
  await expect(frame.locator('[data-copy-recipe-share]')).toHaveText(/Copied|Selected for copying/);
  await frame.getByRole('button', { name: 'Revoke' }).click();
  await expect(frame.locator('#recipe-share-result')).toHaveText('Share link revoked.');
  await frame.getByRole('button', { name: '← All recipes' }).click();
  await expect(frame.getByRole('heading', { name: 'Your recipes' })).toBeVisible();
});

test('MCP recipe tags filter the rendered library and open matching recipes', async ({ page }) => {
  const frame = await host(page);
  await show(page, { kind: 'recipe_library', recipes: [recipe, {
    id: 'guest-recipe', title: 'Guest dinner', description: 'Dinner for visitors', tags: ['guest-friendly'],
  }] });
  await frame.getByRole('button', { name: 'weeknight', exact: true }).click();
  await expect(frame.locator('#recipe-results .recipe-card')).toHaveCount(1);
  await expect(frame.locator('#recipe-results')).toContainText('Lentil bowls');
  await expect(frame.locator('#recipe-results')).not.toContainText('Guest dinner');
  await frame.getByRole('button', { name: 'Open Lentil bowls' }).click();
  await frame.getByRole('button', { name: 'Show recipes tagged weeknight' }).click();
  await expect(frame.locator('#recipe-results .recipe-card')).toHaveCount(1);
  await frame.getByRole('button', { name: 'All recipes' }).click();
  await expect(frame.locator('#recipe-results .recipe-card')).toHaveCount(2);
});

test('MCP recipe search suggests saved tags and finds recipes beyond the initial cards', async ({ page }) => {
  const frame = await host(page);
  const hidden = { id: 'hidden-recipe', title: 'Recovery broth', description: 'Warm soup', tags: ['sickness-friendly'] };
  await show(page, { kind: 'recipe_library', recipes: [recipe], allRecipes: [recipe, hidden], tags: [
    { tag: 'weeknight', recipe_count: 1 }, { tag: 'sickness-friendly', recipe_count: 1 },
  ] });
  await frame.getByRole('searchbox', { name: 'Search recipes' }).fill('sick');
  await expect(frame.getByRole('group', { name: 'Suggested recipe tags' }).getByRole('button', { name: 'sickness-friendly' })).toBeVisible();
  await expect(frame.locator('#recipe-results')).toContainText('Recovery broth');
  await frame.getByRole('group', { name: 'Suggested recipe tags' }).getByRole('button', { name: 'sickness-friendly' }).click();
  await expect(frame.locator('#recipe-results .recipe-card')).toHaveCount(1);
  await expect(frame.locator('#recipe-results')).toContainText('Recovery broth');
  await frame.getByRole('searchbox', { name: 'Search recipes' }).fill('invented');
  await expect(frame.getByRole('group', { name: 'Suggested recipe tags' }).getByRole('button')).toHaveCount(0);
  await expect(frame.getByText('No matching recipes')).toBeVisible();
});

test('MCP views explain empty and unavailable data', async ({ page }) => {
  const frame = await host(page);
  await show(page, { kind: 'meal_plan', plan: null });
  await expect(frame.locator('#root')).toContainText('No meal plan has been saved yet.');
  await show(page, { kind: 'shopping_list', shoppingList: null });
  await expect(frame.locator('#root')).toContainText('No items yet. Add one above.');
  await show(page, { kind: 'feedback', sections: { feedback: { status: 'unavailable', value: null } } });
  await expect(frame.locator('#root')).toContainText('Feedback unavailable');
  await show(page, { kind: 'recipe_library', recipes: [] });
  await expect(frame.locator('#root')).toContainText('No saved recipes yet');
  await show(page, { kind: 'household_snapshot', household: {
    householdName: 'Test kitchen', planningPreferences: {
      dashboard: { hiddenCards: ['food-rules', 'planning-defaults', 'stores', 'schedule', 'meal-plan', 'shopping-list', 'pantry', 'recipes', 'feedback', 'memories'] },
    },
  }, sections: {} });
  await expect(frame.locator('#root')).toContainText('All cards are hidden');
});


test('direct MCP client receives shared workflow and persists pantry use without a plugin', async ({ page, request }) => {
  let requestId = 950;
  async function call(method, params) {
    const response = await request.post('/mcp', {
      headers: { Accept: 'application/json, text/event-stream' },
      data: { jsonrpc: '2.0', id: requestId++, method, params },
    });
    expect(response.ok()).toBeTruthy();
    return (await response.json()).result;
  }
  const initialized = await call('initialize', {
    protocolVersion: '2025-06-18', capabilities: {},
    clientInfo: { name: 'browser-without-plugin', version: '1.0' },
  });
  expect(initialized.instructions).toContain('## Required sequence');
  expect(initialized.instructions).toContain('## Client compatibility');
  const created = await call('tools/call', { name: 'update_pantry_item', arguments: {
    item: { name: 'Direct connection chickpeas', quantity: 2, unit: 'cups' },
  } });
  const item = created.structuredContent;
  const snapshot = await call('tools/call', { name: 'render_household_snapshot', arguments: {} });
  const frame = await host(page, true);
  await show(page, snapshot.structuredContent);
  const row = frame.locator('.pantry-row').filter({ hasText: 'Direct connection chickpeas' });
  await row.getByRole('button', { name: 'Use', exact: true }).click();
  await frame.locator('#pantry-use-form input[name="quantity"]').fill('0.5');
  await frame.locator('#pantry-use-form input[name="mealTitle"]').fill('Tuesday dinner');
  await frame.getByRole('button', { name: 'Record use' }).click();
  await expect(row).toContainText('1.5 cups left');
  const saved = await call('tools/call', { name: 'get_pantry', arguments: {} });
  expect(saved.structuredContent.items.find((value) => value.id === item.id).quantity).toBe(1.5);
  const refreshed = await call('tools/call', { name: 'render_household_snapshot', arguments: {} });
  await show(page, refreshed.structuredContent);
  await expect(row).toContainText('1.5 cups left');
});
