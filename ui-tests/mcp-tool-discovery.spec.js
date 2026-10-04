const { test, expect } = require('@playwright/test');
const { navigateToView } = require('./navigation');

test('recipe saving works with deferred MCP tools and preserves a rejected edit', async ({ page }) => {
  let requestId = 0;
  async function rpc(method, params) {
    const response = await page.request.post('/mcp', {
      headers: { Accept: 'application/json, text/event-stream' },
      data: { jsonrpc: '2.0', id: ++requestId, method, params },
    });
    expect(response.ok()).toBeTruthy();
    const payload = await response.json();
    expect(payload.error).toBeUndefined();
    return payload.result;
  }

  const initialized = await rpc('initialize', {
    protocolVersion: '2025-06-18', capabilities: {},
    clientInfo: { name: 'deferred-tools-browser-contract-test', version: '1.0' },
  });
  expect(initialized.instructions.slice(0, 2048)).toContain('save_recipe');
  const inventory = await rpc('tools/list', {});
  expect(inventory.nextCursor).toBeUndefined();
  expect(inventory.tools.length).toBeGreaterThan(43);

  // Simulate a host honoring the documented always-load metadata. This is a
  // server contract test, not an execution of Claude Code's tool registry.
  const loaded = inventory.tools.filter(tool => tool._meta?.['anthropic/alwaysLoad'] === true);
  const saveTool = loaded.find(tool => tool.name === 'save_recipe');
  expect(saveTool).toBeDefined();
  expect(loaded.some(tool => tool.name === 'search_recipes')).toBe(false);
  const saves = [];
  await page.route('**/api/recipes', async route => {
    if (route.request().method() !== 'PUT') return route.continue();
    // Drive the existing rendered editor, but send its writes through the
    // discovered MCP tool instead of the HTTP adapter. Reads share the service.
    const result = await rpc('tools/call', {
      name: saveTool.name, arguments: { recipe: route.request().postDataJSON() },
    });
    saves.push(result);
    const failure = result.isError === true;
    await route.fulfill({
      status: failure ? 422 : 200, contentType: 'application/json',
      body: JSON.stringify(failure
        ? { detail: result.content.filter(block => block.type === 'text').map(block => block.text).join('\n') }
        : result.structuredContent),
    });
  });

  const title = `Deferred MCP soup ${test.info().project.name}`;
  const content = page.locator('#app-content');
  const editor = page.locator('#editor-dialog');
  await page.goto('/app');
  await navigateToView(page, 'recipes');
  await content.getByRole('button', { name: 'Add recipe', exact: true }).click();
  await editor.locator('[name="title"]').fill(title);
  await editor.locator('[name="description"]').fill('Saved through MCP discovery');
  await editor.locator('[name="ingredients"]').fill('Lentils | 1 | cup');
  await editor.locator('[name="instructions"]').fill('Simmer until tender');
  await editor.locator('#dialog-save').click();
  await expect(editor).toBeHidden();
  await expect(content.locator('.hero h2')).toHaveText(title);
  await expect(content).toContainText('Simmer until tender');
  expect(saves).toHaveLength(1);
  expect(saves[0].isError).not.toBe(true);
  const recipeId = saves[0].structuredContent.id;

  await content.getByRole('button', { name: 'Edit recipe', exact: true }).click();
  await editor.locator('[name="description"]').fill('Retained draft after rejection');
  const kind = editor.locator('input[name="kind"]').locator('..');
  await kind.locator('.choice-trigger').click();
  await kind.locator('[data-choice-value="ready_food"]').click();
  await editor.locator('#dialog-save').click();
  await expect(editor.locator('#dialog-error')).toContainText('Ready food has no ingredient demand');
  await expect(editor.locator('[name="description"]')).toHaveValue('Retained draft after rejection');
  await expect(editor.locator('[name="ingredients"]')).toHaveValue('Lentils | 1 | cup');
  expect(saves).toHaveLength(2);
  expect(saves[1].isError).toBe(true);
  const unchanged = await rpc('tools/call', { name: 'get_recipe', arguments: { recipe_id: recipeId } });
  expect(unchanged.structuredContent.description).toBe('Saved through MCP discovery');
  expect(unchanged.structuredContent.kind).toBe('recipe');

  await kind.locator('.choice-trigger').click();
  await kind.locator('[data-choice-value="recipe"]').click();
  await editor.locator('#dialog-save').click();
  await expect(editor).toBeHidden();
  expect(saves).toHaveLength(3);
  expect(saves[2].isError).not.toBe(true);
  await page.reload();
  await expect(content.locator('.hero h2')).toHaveText(title);
  await expect(content).toContainText('Retained draft after rejection');
  await expect(content).toContainText('Simmer until tender');
  const persisted = await rpc('tools/call', { name: 'get_recipe', arguments: { recipe_id: recipeId } });
  expect(persisted.structuredContent.description).toBe('Retained draft after rejection');
  expect(persisted.structuredContent.kind).toBe('recipe');
});
