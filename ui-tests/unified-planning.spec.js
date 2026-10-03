const { test, expect } = require('@playwright/test');
const editor = (page) => page.locator('#editor-dialog');
let week;

async function choose(scope, suffix, value) {
  const input = scope.locator(`input[type="hidden"][name$="${suffix}"]`);
  const parent = input.locator('..');
  await parent.locator('.choice-trigger').click();
  await parent.locator(`[data-choice-value="${value}"]`).click();
  await expect(input).toHaveValue(value);
}
async function saveEditor(page) {
  await editor(page).locator('#dialog-save').click();
  await expect(editor(page)).toBeHidden();
}
async function request(page, method, path, data) {
  const result = await page.request[method](path, { data });
  expect(result.ok(), await result.text()).toBeTruthy();
  return result.json();
}
async function resetSlots(page) {
  const h = await request(page, 'get', '/api/household');
  const ids = ['breakfast', 'lunch', 'snack', 'dinner'];
  await request(page, 'put', '/api/meal-slots', { slots: [
    ...ids.map((id) => ({ id, name: id[0].toUpperCase() + id.slice(1), enabled: true })),
    ...h.mealSlots.filter((slot) => !ids.includes(slot.id)).map((slot) => ({ ...slot, enabled: false })),
  ] });
}
test.beforeEach(async ({ page }) => {
  await resetSlots(page);
  const date = new Date('2040-01-02T12:00:00Z');
  date.setUTCDate(date.getUTCDate() - ((date.getUTCDay() + 6) % 7) + 7 * (test.info().line + test.info().retry * 1000));
  week = date.toISOString().slice(0, 10);
  await request(page, 'put', '/api/meal-plan', { weekStart: week, entries: [], tasks: [] });
});
test.afterEach(async ({ page }) => { await resetSlots(page); });

async function openPlan(page) {
  await page.goto(`/app?view=plan&week=${week}`);
  await expect(page.locator('#week-picker')).toHaveValue(week);
  await expect(page.getByRole('button', { name: 'Add meal', exact: true })).toBeVisible();
}

test('households add, reorder, rename, and disable slots without losing planned meals', async ({ page }) => {
  await page.goto('/app?view=settings');
  await page.getByRole('button', { name: 'Edit meal slots' }).click();
  await editor(page).getByRole('button', { name: 'Add slot', exact: true }).click();
  const slot = editor(page).locator('[data-slot-id]').last();
  const id = await slot.getAttribute('data-slot-id');
  await slot.getByLabel('Slot name').fill(`Kids snack AM ${id.slice(0, 6)}`);
  const count = await editor(page).locator('[data-slot-id]').count();
  for (let i = 1; i < count; i++) await editor(page).locator(`[data-slot-id="${id}"] [data-editor-action="slot-up"]`).click();
  await saveEditor(page);
  expect((await request(page, 'get', '/api/household')).mealSlots[0].id).toBe(id);
  const popcorn = await request(page, 'put', '/api/recipes', {title: `School popcorn ${id}`, kind: 'ready_food'});
  await openPlan(page);
  await page.getByRole('button', { name: 'Add meal', exact: true }).click();
  await editor(page).locator('#plan-food-search').fill(popcorn.title);
  await editor(page).locator('.plan-food-result').filter({hasText: popcorn.title}).click();
  await choose(editor(page), 'slot', id);
  await saveEditor(page);
  const meal = page.locator('.meal').filter({ hasText: popcorn.title });
  await expect(meal).toContainText('Kids snack AM');
  const before = (await request(page, 'get', `/api/meal-plan?week_start=${week}`)).plan;
  await page.goto('/app?view=settings');
  await page.getByRole('button', { name: 'Edit meal slots' }).click();
  const row = editor(page).locator(`[data-slot-id="${id}"]`);
  await row.getByLabel('Slot name').fill(`School snack ${id.slice(0, 6)}`);
  await row.getByLabel('Enabled').uncheck();
  await saveEditor(page);
  await openPlan(page);
  await expect(page.locator('.meal')).toContainText('School snack');
  expect((await request(page, 'get', `/api/meal-plan?week_start=${week}`)).plan.entries[0].id).toBe(before.entries[0].id);
  await page.getByRole('button', { name: 'Add meal', exact: true }).click();
  await editor(page).locator('input[name="slot"]').locator('..').locator('.choice-trigger').click();
  await expect(editor(page).locator(`[data-choice-value="${id}"]`)).toHaveCount(0);
  await editor(page).getByRole('button', { name: 'Cancel', exact: true }).click();
});

test('tasks need no slot, date, recipe, or meal link and completion preserves stock', async ({ page }) => {
  await openPlan(page);
  const before = (await request(page, 'get', '/api/pantry')).items;
  await page.getByRole('tab', { name: 'Tasks', exact: true }).click();
  await page.getByRole('button', { name: 'Add task', exact: true }).click();
  await editor(page).locator('[name="title"]').fill('Pack kids and parents snacks');
  await editor(page).locator('[name="notes"]').fill('Put the bought popcorn in lunch bags.');
  await saveEditor(page);
  const task = page.locator('.plan-task').filter({ hasText: 'Pack kids and parents snacks' });
  await expect(task).toBeVisible();
  await page.reload();
  await expect(page.getByRole('tab', {name:'Tasks',exact:true})).toHaveAttribute('aria-selected','true');
  await task.getByRole('checkbox', { name: 'Complete Pack kids and parents snacks' }).check();
  await expect(task.getByRole('checkbox')).toBeChecked();
  await expect(task.getByRole('checkbox')).toBeDisabled();
  const plan = (await request(page, 'get', `/api/meal-plan?week_start=${week}`)).plan;
  expect(plan.tasks[0]).toMatchObject({ date: null, mealIds: [] });
  expect(plan.tasks[0].completedAt).toBeTruthy();
  expect((await request(page, 'get', '/api/pantry')).items).toEqual(before);
});

test('mixed meals reuse one batch, calculate shortages once, and preserve manual shopping', async ({ page }) => {
  const suffix = week;
  const dal = await request(page, 'put', '/api/recipes', { title: `Dal ${suffix}`, servings: 4, ingredients: [{ name: `Lentils ${suffix}`, quantity: 200, unit: 'g' }] });
  const stocks = {};
  for (const [name, quantity, unit] of [['Rotis', 12, 'pieces'], ['Lentils', 250, 'g'], ['Yogurt', 300, 'g']]) stocks[name] = await request(page, 'put', '/api/pantry', { name: `${name} ${suffix}`, quantity, unit, quantityConfidence: 'exact' });
  const soap = await request(page, 'post', '/api/shopping-list/items', { item: { name: `Soap ${suffix}`, quantity: 1, unit: 'bottle' } });
  await openPlan(page);
  await page.getByRole('tab', { name: 'Tasks', exact: true }).click();
  await page.getByRole('button', { name: 'Add task', exact: true }).click();
  await editor(page).locator('[name="title"]').fill(`Cook dal ${suffix}`);
  await choose(editor(page), 'recipeId', dal.id);
  await editor(page).locator('[name="servings"]').fill('8');
  const sunday = new Date(`${week}T12:00:00Z`); sunday.setUTCDate(sunday.getUTCDate() - 1);
  await editor(page).locator('[name="date"]').fill(sunday.toISOString().slice(0, 10));
  await saveEditor(page);
  const task = (await request(page, 'get', `/api/meal-plan?week_start=${week}`)).plan.tasks[0];
  await page.getByRole('tab', {name:'Meals',exact:true}).click();
  for (let day = 0; day < 2; day++) {
    const date = new Date(`${week}T12:00:00Z`); date.setUTCDate(date.getUTCDate() + day);
    await request(page, 'patch', '/api/meal-plan/items', {weekStart: week, kind: 'meal', item: {
      date: date.toISOString().slice(0, 10), slot: 'dinner', meal: `Roti dinner ${suffix} ${day}`,
      components: [
        {name: `Rotis ${suffix}`, quantity: 8, unit: 'pieces', source: 'ready', pantryItemId: stocks.Rotis.id},
        {name: dal.title, quantity: 4, unit: 'servings', source: 'task', taskId: task.id},
        {name: `Yogurt ${suffix}`, quantity: 200, unit: 'g', source: 'ready', pantryItemId: stocks.Yogurt.id},
      ]}});
  }
  await page.reload();
  expect((await request(page, 'get', '/api/pantry')).items.find((row) => row.id === stocks.Rotis.id).quantity).toBe(12);
  await page.getByRole('button', { name: 'Shopping needs', exact: true }).click();
  await expect(editor(page)).toContainText(`Lentils ${suffix}`);
  const needs = await request(page, 'get', `/api/meal-plan/shopping-preview?week_start=${week}`);
  expect(Object.fromEntries(needs.items.map((row) => [row.name, row.quantity]))).toEqual({ [`Rotis ${suffix}`]: 4, [`Lentils ${suffix}`]: 150, [`Yogurt ${suffix}`]: 100 });
  await editor(page).getByRole('button', { name: 'Update shopping list' }).click();
  await expect(editor(page)).toBeHidden();
  const list = (await request(page, 'get', '/api/shopping-list')).shoppingList;
  expect(list.items.some((row) => row.name === `Soap ${suffix}`)).toBe(true);
  expect(list.items.filter((row) => row.source?.weekStart === week)).toHaveLength(3);
  await page.reload();
  await expect(page.locator('.meal').filter({ hasText: `Roti dinner ${suffix} 0` })).toContainText(dal.title);
});

test('cooking rejects overuse, records actual output, and eating consumes that stock once', async ({ page }) => {
  const lentils = await request(page, 'put', '/api/pantry', { name: `Activity lentils ${week}`, quantity: 500, unit: 'g', quantityConfidence: 'exact' });
  const recipe = await request(page, 'put', '/api/recipes', { title: `Activity dal ${week}`, servings: 4, ingredients: [{ name: lentils.name, quantity: 200, unit: 'g' }] });
  let plan = await request(page, 'patch', '/api/meal-plan/items', { weekStart: week, kind: 'task', item: { title: 'Cook eight servings', recipeId: recipe.id, servings: 8 } });
  const task = plan.tasks[0];
  for (let day = 0; day < 2; day++) {
    const date = new Date(`${week}T12:00:00Z`); date.setUTCDate(date.getUTCDate() + day);
    plan = await request(page, 'patch', '/api/meal-plan/items', { weekStart: week, kind: 'meal', item: { date: date.toISOString().slice(0, 10), slot: 'dinner', meal: `Dal dinner ${day}`, components: [{ name: recipe.title, quantity: 4, unit: 'servings', source: 'task', taskId: task.id }] } });
  }
  await openPlan(page);
  await page.getByRole('tab', {name:'Tasks',exact:true}).click();
  await page.getByRole('button', { name: 'Record cooking' }).click();
  await editor(page).getByRole('button', { name: 'Add food used', exact: true }).click();
  const used = editor(page).locator('[data-stock-input]');
  await choose(used, '-itemId', lentils.id);
  await used.getByLabel('Actual amount used').fill('600');
  await editor(page).locator('[data-stock-output]').getByLabel('Actual quantity remaining').fill('7');
  await editor(page).getByRole('button', { name: 'Record completion' }).click();
  await expect(editor(page).locator('#dialog-error')).toContainText('Not enough');
  await expect(used.getByLabel('Actual amount used')).toHaveValue('600');
  expect((await request(page, 'get', '/api/pantry')).items.find((row) => row.id === lentils.id).quantity).toBe(500);
  await used.getByLabel('Actual amount used').fill('400');
  await saveEditor(page);
  const output = (await request(page, 'get', '/api/pantry')).items.find(row => row.name === recipe.title);
  await request(page, 'post', '/api/meal-plan/complete', {weekStart:week,kind:'meal',itemId:plan.entries[0].id,inputs:[{itemId:output.id,quantity:4}]});
  await page.getByRole('tab', {name:'Meals',exact:true}).click();
  await expect(page.getByRole('button', {name:'Record eaten',exact:true})).toHaveCount(0);
  const pantry = (await request(page, 'get', '/api/pantry')).items;
  const dal = pantry.find((row) => row.name === recipe.title);
  expect(dal.quantity).toBe(3);
  const replay = await request(page, 'post', '/api/meal-plan/complete', { weekStart: week, kind: 'meal', itemId: plan.entries[0].id });
  expect((await request(page, 'get', '/api/pantry')).items.find((row) => row.id === dal.id).quantity).toBe(3);
  expect((await request(page, 'get', `/api/meal-plan/shopping-preview?week_start=${week}`)).items.find((row) => row.name === recipe.title).quantity).toBe(1);
});

test('receiving a bought pack records the actual pantry unit and survives reload', async ({ page }) => {
  const list = await request(page, 'post', '/api/shopping-list/items', { item: { name: `Bought rotis ${week}`, quantity: 1, unit: 'pack' } });
  const line = list.items.find((row) => row.name === `Bought rotis ${week}`);
  await page.goto('/app?view=shopping');
  const row = page.locator('.check-row').filter({ hasText: line.name });
  await row.getByRole('button', { name: 'Add to pantry' }).click();
  await editor(page).getByLabel('Quantity received').fill('20');
  await editor(page).getByLabel('Pantry unit').fill('pieces');
  await saveEditor(page);
  await expect(row).toContainText('Added to pantry');
  await expect(row.getByRole('checkbox')).toBeChecked();
  await page.reload();
  await expect(row.getByRole('checkbox')).toBeDisabled();
  const stocks = (await request(page, 'get', '/api/pantry')).items.filter((item) => item.provenance?.shoppingItemId === line.id);
  expect(stocks).toHaveLength(1);
  expect(stocks[0]).toMatchObject({ quantity: 20, unit: 'pieces' });
});

test('mobile meal editor links a recipe without exposing legacy food fields or losing a task link', async ({ page }) => {
  const plan = await request(page, 'patch', '/api/meal-plan/items', { weekStart: week, kind: 'task', item: { title: 'Make a snack box' } });
  const popcorn = await request(page, 'put', '/api/recipes', {title: `Popcorn ${week}`, kind: 'ready_food'});
  const planned = await request(page, 'patch', '/api/meal-plan/items', {weekStart: week, kind: 'meal', item: {
    date: week, slot: 'dinner', meal: 'Snack box and popcorn', components: [
      {name: 'Snack box', quantity: 1, unit: 'portion', source: 'task', taskId: plan.tasks[0].id}]}});
  await page.setViewportSize({ width: 390, height: 844 });
  await openPlan(page);
  await page.locator('.meal').filter({hasText: 'Snack box and popcorn'}).getByRole('button', {name: 'Edit'}).click();
  await expect(editor(page).locator('.component-row')).toHaveCount(0);
  await expect(editor(page).getByRole('button', {name: 'Advanced meal details'})).toHaveCount(0);
  await choose(editor(page), 'plannedRecipeId', popcorn.id);
  await saveEditor(page);
  const updated = (await request(page, 'get', `/api/meal-plan?week_start=${week}`)).plan.entries.find(row => row.id === planned.entries[0].id);
  expect(updated.components.map(part => [part.taskId, part.recipeId])).toEqual([[plan.tasks[0].id, null], [null, popcorn.id]]);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});

test('rendered MCP App completes an independent task through the real MCP service', async ({ page }) => {
  const plan = await request(page, 'patch', '/api/meal-plan/items', { weekStart: week, kind: 'task', item: { title: 'Pack school snacks' } });
  await mountMcpPlan(page, plan);
  const frame = page.frameLocator('iframe');
  await frame.getByRole('button', {name:'Tasks',exact:true}).click();
  await frame.getByRole('button', { name: 'Complete task' }).click();
  await expect(frame.locator('[data-plan-task]')).toContainText('Completed');
  const saved = (await request(page, 'get', `/api/meal-plan?week_start=${week}`)).plan;
  expect(saved.tasks[0].completedAt).toBeTruthy();
  expect(await page.evaluate(() => window.calls[0].name)).toBe('complete_plan_item');
});

async function mountMcpPlan(page, plan) {
  await page.route('**/unified-mcp-host', (route) => route.fulfill({ contentType: 'text/html', body: `<!doctype html><iframe src="/static/mcp-app.html" style="width:100%;height:900px"></iframe><script>
    window.ready=false; window.calls=[];
    addEventListener('message',async(event)=>{const message=event.data;if(message?.jsonrpc!=='2.0'||!message.method)return;
      if(message.method==='ui/notifications/initialized'){window.ready=true;return;}
      if(message.method==='ui/initialize'){event.source.postMessage({jsonrpc:'2.0',id:message.id,result:{}},'*');return;}
      if(message.method==='tools/call'){window.calls.push(message.params);const response=await fetch('/mcp',{method:'POST',headers:{'Content-Type':'application/json',Accept:'application/json, text/event-stream'},body:JSON.stringify(message)});event.source.postMessage(await response.json(),'*');}
    });</script>` }));
  await page.goto('/unified-mcp-host');
  await expect.poll(() => page.evaluate(() => window.ready)).toBe(true);
  const household = await request(page,'get','/api/household');
  await page.evaluate(({plan,household}) => document.querySelector('iframe').contentWindow.postMessage({ jsonrpc: '2.0', method: 'ui/notifications/tool-result', params: { structuredContent: { kind: 'meal_plan', plan,household } } }, '*'), {plan,household});
}

test('MCP App cooking retains an invalid actual amount and records corrected stock', async ({ page }) => {
  const stock = await request(page, 'put', '/api/pantry', { name: `MCP lentils ${week}`, quantity: 250, unit: 'g', quantityConfidence: 'exact' });
  const recipe = await request(page, 'put', '/api/recipes', { title: `MCP dal ${week}`, servings: 4, ingredients: [{ name: stock.name, quantity: 200, unit: 'g' }] });
  const plan = await request(page, 'patch', '/api/meal-plan/items', { weekStart: week, kind: 'task', item: { title: 'Cook dal in chat', recipeId: recipe.id, servings: 4 } });
  await mountMcpPlan(page, plan);
  const frame = page.frameLocator('iframe');
  await frame.getByRole('button', {name:'Tasks',exact:true}).click();
  await frame.getByRole('button', { name: 'Record cooking' }).click();
  const form = frame.locator('#plan-completion-form');
  await choose(form, 'item-0', stock.id);
  await form.getByLabel('Actual amount used (in pantry unit)').fill('300');
  await form.getByLabel('Actual quantity remaining').fill('5');
  await form.getByRole('button', { name: 'Record completion' }).click();
  await expect(form.locator('.form-error')).toContainText('Not enough');
  await expect(form.getByLabel('Actual amount used (in pantry unit)')).toHaveValue('300');
  expect((await request(page, 'get', '/api/pantry')).items.find((row) => row.id === stock.id).quantity).toBe(250);
  await form.getByLabel('Actual amount used (in pantry unit)').fill('200');
  await form.getByRole('button', { name: 'Record completion' }).click();
  await expect(frame.locator('[data-plan-task]')).toContainText('Completed');
  const pantry = (await request(page, 'get', '/api/pantry')).items;
  expect(pantry.find((row) => row.id === stock.id).quantity).toBe(50);
  expect(pantry.filter((row) => row.name === recipe.title)).toHaveLength(1);
  expect(pantry.find((row) => row.name === recipe.title).quantity).toBe(5);
});


test('meal cards open their saved recipes, hide descriptions and actions, and Meals/Tasks only change the display', async ({page}) => {
  const recipe = await request(page,'put','/api/recipes',{title:`Linked recipe ${week}`,ingredients:[{name:'Tofu'}],instructions:['Steam and serve.']});
  const plan = await request(page,'put','/api/meal-plan',{weekStart:week,entries:[
    {date:week,slot:'dinner',meal:'Simple tofu dinner',notes:'A long description that should stay in the editor.',components:[{name:recipe.title,recipeId:recipe.id,source:'cook'}]},
    {date:week,slot:'lunch',meal:'Meal without a saved recipe'}],tasks:[{title:'Saved task',date:week}]});
  await openPlan(page);
  await expect(page.getByRole('tab',{name:'Meals',exact:true})).toHaveAttribute('aria-selected','true');
  await expect(page.locator('.plan-task')).toHaveCount(0);
  await expect(page.getByRole('button',{name:'Add task',exact:true})).toHaveCount(0);
  const card = page.locator('.meal').filter({hasText:recipe.title});
  await expect(card).not.toContainText('A long description');
  await expect(card.getByRole('button',{name:'Remove',exact:true})).toHaveCount(0);
  await expect(card.getByRole('button',{name:'Record eaten',exact:true})).toHaveCount(0);
  await expect(page.locator('.meal').filter({hasText:'Meal without a saved recipe'}).getByRole('link')).toHaveCount(0);
  await card.getByRole('link',{name:recipe.title,exact:true}).click();
  await expect(page.getByRole('heading',{name:recipe.title,exact:true})).toBeVisible();
  await expect(page.locator('#app-content')).toContainText('Steam and serve.');
  await page.goBack();
  await expect(card).toBeVisible();
  await page.route(`**/api/recipes/${recipe.id}`, route=>route.fulfill({status:503,json:{detail:'Recipe temporarily unavailable'}}));
  await card.getByRole('link',{name:recipe.title,exact:true}).press('Enter');
  await expect(page.locator('#toast')).toContainText('Recipe temporarily unavailable');
  await expect(card).toBeVisible();
  await page.unroute(`**/api/recipes/${recipe.id}`);
  const preferences = await request(page,'get','/api/household');
  const writes = [];
  page.on('request', req => { if (req.url().includes('/api/') && !['GET','HEAD'].includes(req.method())) writes.push(req.url()); });
  await page.getByRole('tab',{name:'Tasks',exact:true}).click();
  await expect(page.locator('.meal')).toHaveCount(0);
  await expect(page.locator('.plan-task')).toContainText('Saved task');
  await page.getByRole('button',{name:'Add task',exact:true}).click();
  await editor(page).getByLabel('Task name').fill('Requested prep');
  await saveEditor(page);
  await expect(page.locator('.plan-task')).toHaveCount(2);
  await page.reload();
  await expect(page.locator('.plan-task')).toHaveCount(2);
  await page.getByRole('tab',{name:'Meals',exact:true}).click();
  await expect(page.locator('.plan-task')).toHaveCount(0);
  await expect(card).toBeVisible();
  expect(writes).toHaveLength(1); // Only the requested Add task writes data.
  expect(await request(page,'get','/api/household')).toEqual(preferences);
  const context=await request(page,'get',`/api/planning-context?week_start=${week}`);
  expect(context.mealPlan.tasks).toHaveLength(2);
  await request(page,'patch','/api/meal-plan/items',{weekStart:week,kind:'task',item:{title:'Prep added while Meals is displayed'}});
  await page.reload();
  await expect(page.locator('.plan-task')).toHaveCount(0);
  await expect(card).toBeVisible();
  const updated=await request(page,'get',`/api/planning-context?week_start=${week}`);
  expect(updated.mealPlan.tasks).toHaveLength(3);
  const savedPlan=updated.mealPlan;
  const writesBeforeMcp = writes.length;
  await mountMcpPlan(page,savedPlan);
  const frame=page.frameLocator('iframe');
  await expect(frame.locator('[data-plan-task]')).toHaveCount(0);
  await expect(frame.getByRole('button',{name:'Record eaten',exact:true})).toHaveCount(0);
  await frame.getByRole('button',{name:'Simple tofu dinner',exact:true}).click();
  await expect(frame.getByRole('heading',{name:recipe.title,exact:true})).toBeVisible();
  await frame.getByRole('button',{name:'Back to weekly plan',exact:true}).click();
  await frame.getByRole('button',{name:'Tasks',exact:true}).click();
  await expect(frame.locator('[data-plan-meal]')).toHaveCount(0);
  await expect(frame.locator('[data-plan-task]')).toHaveCount(3);
  await frame.getByRole('button',{name:'Meals',exact:true}).click();
  await expect(frame.locator('[data-plan-task]')).toHaveCount(0);
  expect(writes).toHaveLength(writesBeforeMcp);
  expect(await request(page,'get','/api/household')).toEqual(preferences);
  expect((await request(page,'get',`/api/meal-plan?week_start=${week}`)).plan).toEqual(savedPlan);
});
