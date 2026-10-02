const {test, expect} = require('@playwright/test');
const dialog = page => page.locator('#editor-dialog');
let week, suffix, createdRecipes = [], createdMeals = [];
async function request(page, method, path, data) {
  const res = await page.request[method](path, {data});
  expect(res.ok(), await res.text()).toBeTruthy();
  const result = await res.json();
  if (method === 'put' && path === '/api/recipes') createdRecipes.push(result.id);
  if (method === 'put' && path === '/api/meals') createdMeals.push(result.id);
  return result;
}
async function choose(scope, suffix, value) {
  const input = scope.locator(`input[type="hidden"][name$="${suffix}"]`), parent = input.locator('..');
  await parent.locator('.choice-trigger').click(); await parent.locator(`[data-choice-value="${value}"]`).click();
  await expect(input).toHaveValue(value);
}
async function save(page) { await dialog(page).locator('#dialog-save').click(); await expect(dialog(page)).toBeHidden(); }
async function fillComponent(row, data) {
  await row.getByLabel('Food or dish', {exact: true}).fill(data.name);
  if (data.quantity) await row.getByLabel('Amount', {exact: true}).fill(String(data.quantity));
  if (data.unit) await row.getByLabel('Unit', {exact: true}).fill(data.unit);
  if (data.source) await choose(row, '-source', data.source);
  if (data.recipeId) await choose(row, '-recipeId', data.recipeId);
}
async function search(page, query) {
  await page.locator('#recipe-search').fill(query);
  await expect(page.locator('#recipe-search')).toHaveValue(query);
  await expect(page.locator('#recipe-results')).toHaveAttribute('aria-busy', 'false');
}
test.beforeEach(async ({page}) => {
  createdRecipes = []; createdMeals = [];
  suffix = `${test.info().line}-${test.info().retry}-${Date.now()}`;
  const date = new Date('2042-01-06T12:00:00Z'); date.setUTCDate(date.getUTCDate() + 7 * test.info().line);
  week = date.toISOString().slice(0,10);
  const household = await request(page, 'get', '/api/household');
  await request(page, 'put', '/api/meal-slots', {slots: household.mealSlots.map(slot => ({...slot, enabled: slot.id === 'dinner' || slot.enabled}))});
  await request(page, 'put', '/api/meal-plan', {weekStart: week, entries: [], tasks: []});
});

test.afterEach(async ({page}) => {
  for (const id of createdMeals) await request(page, 'delete', `/api/meals/${id}`);
  for (const id of createdRecipes) await request(page, 'delete', `/api/recipes/${id}`);
});

test('Meals category creates recipes plus ready food, scales a dated copy, and calculates pantry-aware shopping', async ({page}) => {
  const dal = await request(page, 'put', '/api/recipes', {title: `Dal ${suffix}`, servings: 4, ingredients: [{name: `Lentils ${suffix}`, quantity: 200, unit: 'g'}]});
  const salad = await request(page, 'put', '/api/recipes', {title: `Salad ${suffix}`, servings: 2, ingredients: [{name: `Carrots ${suffix}`, quantity: 100, unit: 'g'}]});
  const stock = await request(page, 'put', '/api/pantry', {name: `Rotis ${suffix}`, quantity: 10, unit: 'pieces', quantityConfidence: 'exact'});
  await page.goto(`/app?view=plan&week=${week}`);
  await page.getByRole('button', {name: 'Use saved meal', exact: true}).click();
  await expect(page.locator('#view-title')).toHaveText('Recipes');
  await expect(page.getByRole('combobox', {name:'Library type'})).toHaveValue('meals');
  await page.getByRole('button', {name: 'Create meal', exact: true}).click();
  await dialog(page).getByLabel('Meal name', {exact: true}).fill(`Dinner ${suffix}`);
  await dialog(page).getByLabel('Default servings').fill('4');
  await dialog(page).getByLabel('Notes', {exact: true}).fill(`Quick family dinner ${suffix}`);
  const values = [{name: stock.name, quantity: 8, unit: 'pieces'}, {name: dal.title, quantity: 4, unit: 'servings', source: 'cook', recipeId: dal.id}, {name: salad.title, quantity: 4, unit: 'servings', source: 'cook', recipeId: salad.id}];
  for (let i=0; i<values.length; i++) {
    if (i) await dialog(page).getByRole('button', {name: 'Add component', exact: true}).click();
    await fillComponent(dialog(page).locator('.component-row').nth(i), values[i]);
  }
  await save(page);
  await search(page, suffix);
  const card = page.locator('[data-saved-meal]').filter({hasText: `Dinner ${suffix}`});
  await expect(card).toContainText(dal.title); await expect(card).toContainText(salad.title);
  const id = await card.getAttribute('data-saved-meal');
  await card.getByRole('button', {name: 'Plan this meal'}).click();
  await expect(dialog(page).getByLabel('Date', {exact: true})).toHaveValue(week);
  await dialog(page).getByLabel('Servings to plan').fill('8'); await save(page);
  await expect(page.locator('.meal').filter({hasText: `Dinner ${suffix}`})).toContainText(`16 pieces`);
  const plan = (await request(page, 'get', `/api/meal-plan?week_start=${week}`)).plan;
  expect(plan.entries[0].sourceMeal.id).toBe(id);
  expect(plan.entries[0].components.map(row => row.quantity)).toEqual([16,8,8]);
  await page.getByRole('button', {name: 'Shopping needs', exact: true}).click();
  await expect(dialog(page)).toContainText(`Lentils ${suffix}`);
  await dialog(page).getByRole('button', {name: 'Update shopping list'}).click(); await expect(dialog(page)).toBeHidden();
  const list = (await request(page, 'get', '/api/shopping-list')).shoppingList.items;
  expect(list.find(row => row.name === stock.name).quantity).toBe(6);
  expect(list.find(row => row.name === `Lentils ${suffix}`).quantity).toBe(400);
  expect(list.find(row => row.name === `Carrots ${suffix}`).quantity).toBe(400);
  expect((await request(page, 'get', '/api/pantry')).items.find(row => row.id === stock.id).quantity).toBe(10);
  await page.goto(`/app?view=recipes&type=meals&query=${suffix}`);
  await card.getByRole('button', {name: 'Edit', exact: true}).click();
  await dialog(page).getByLabel('Meal name', {exact: true}).fill(`Changed dinner ${suffix}`); await save(page);
  const revised = await request(page, 'get', `/api/meals/${id}`); expect(revised.revision).toBe(2);
  expect((await request(page, 'get', `/api/meal-plan?week_start=${week}`)).plan).toEqual(plan);
  await card.getByRole('button', {name: 'Archive', exact: true}).click(); await expect(card).toHaveCount(0);
  await page.goto(`/app?view=plan&week=${week}`);
  await expect(page.locator('.meal')).toContainText(`Dinner ${suffix}`);
  expect((await request(page, 'get', `/api/meal-plan?week_start=${week}`)).plan).toEqual(plan);
  await page.locator('.meal').getByRole('button', {name: 'Edit', exact: true}).click();
  await dialog(page).getByRole('textbox', {name: 'Notes', exact: true}).fill('Serve after school'); await save(page);
  const edited = (await request(page, 'get', `/api/meal-plan?week_start=${week}`)).plan.entries[0];
  expect(edited.sourceMeal).toEqual(plan.entries[0].sourceMeal);
  expect(edited.components).toEqual(plan.entries[0].components);
  expect(edited.notes).toBe('Serve after school');
});

test('mobile library retains a failed recipe draft, saves corrected food, and searches notes and components', async ({page}) => {
  await page.setViewportSize({width:390,height:844}); await page.goto('/app?view=recipes&type=meals');
  await page.locator('.mobile-nav [data-view="recipes"]').click();
  await expect(page.getByRole('combobox', {name:'Library type'})).toHaveValue('meals');
  await page.getByRole('button', {name:'Create meal'}).click();
  await dialog(page).getByLabel('Meal name', {exact:true}).fill(`Snack ${suffix}`);
  const row=dialog(page).locator('.component-row');
  await fillComponent(row,{name:`Popcorn ${suffix}`,quantity:2,unit:'portions',source:'cook'});
  await dialog(page).locator('#dialog-save').click();
  await expect(dialog(page).locator('#dialog-error')).toContainText('recipeId');
  await expect(row.getByLabel('Food or dish')).toHaveValue(`Popcorn ${suffix}`);
  expect((await request(page,'get',`/api/meals?query=${suffix}`)).total).toBe(0);
  await choose(row,'-source','ready');
  await dialog(page).getByLabel('Notes',{exact:true}).fill(`School pickup ${suffix}`); await save(page);
  await search(page,`popcorn ${suffix}`); await expect(page.locator('[data-saved-meal]')).toHaveCount(1);
  await search(page,`pickup ${suffix}`); await expect(page.locator('[data-saved-meal]')).toHaveCount(1);
  await page.reload(); await expect(page.locator('[data-saved-meal]')).toHaveCount(1);
  expect(await page.evaluate(()=>document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});

test('search and pagination find older meals beyond the first page', async ({page}) => {
  const older = await request(page,'put','/api/meals',{name:`Old ${suffix}`,servings:1,components:[{name:`Rare popcorn ${suffix}`}]});
  for(let i=0;i<52;i++) await request(page,'put','/api/meals',{name:`Page meal ${suffix} ${i}`,servings:1,components:[{name:'Roti'}]});
  await page.goto(`/app?view=recipes&type=meals&query=${suffix}`);
  await expect(page.locator('[data-saved-meal]')).toHaveCount(50);
  await page.getByRole('button',{name:'Show more meals'}).click(); await expect(page.locator('[data-saved-meal]')).toHaveCount(53);
  await expect(page.locator(`[data-saved-meal="${older.id}"]`)).toBeVisible();
  await search(page,`Rare popcorn ${suffix}`); await expect(page.locator('[data-saved-meal]')).toHaveCount(1);
  await expect(page.locator('[data-saved-meal]')).toHaveAttribute('data-saved-meal',older.id);
});

test('Save as meal from a dated batch detaches pantry/task links and single recipes can also become meals', async ({page}) => {
  const recipe = await request(page,'put','/api/recipes',{title:`Batch dal ${suffix}`,servings:4,ingredients:[{name:'Lentils',quantity:200,unit:'g'}]});
  const taskId=require('crypto').randomUUID(), stock=await request(page,'put','/api/pantry',{name:`Roti ${suffix}`,quantity:8,unit:'pieces'});
  const plan=await request(page,'put','/api/meal-plan',{weekStart:week,tasks:[{id:taskId,title:'Cook once',recipeId:recipe.id,servings:8}],entries:[{date:week,slot:'dinner',meal:`Batch dinner ${suffix}`,servings:4,components:[{name:recipe.title,quantity:4,unit:'servings',source:'task',taskId},{name:stock.name,quantity:8,unit:'pieces',pantryItemId:stock.id}]}]});
  await page.goto(`/app?view=plan&week=${week}`); await page.locator('.meal').getByRole('button',{name:'Save as meal'}).click();
  await expect(dialog(page).locator('[data-source="task"]')).toHaveCount(0); await save(page);
  const saved=(await request(page,'get',`/api/meals?query=${suffix}`)).items.find(row=>row.name===`Batch dinner ${suffix}`);
  expect(saved.components[0]).toMatchObject({source:'cook',recipeId:recipe.id,taskId:null,pantryItemId:null});
  expect(saved.components[1].pantryItemId).toBeNull();
  expect((await request(page,'get',`/api/meal-plan?week_start=${week}`)).plan).toEqual(plan);
  await page.goto(`/app?view=recipes&recipe=${recipe.id}`); await page.getByRole('button',{name:'Save as meal'}).click(); await save(page);
  const single=(await request(page,'get',`/api/meals?query=${suffix}`)).items.find(row=>row.name===recipe.title);
  expect(single.servings).toBe(4); expect(single.components).toHaveLength(1); expect(single.components[0].recipeId).toBe(recipe.id);
  const ready=await request(page,'put','/api/recipes',{title:`Ready rotis ${suffix}`,kind:'ready_food'});
  const readyTask=require('crypto').randomUUID();
  await request(page,'put','/api/meal-plan',{weekStart:week,tasks:[{id:readyTask,title:'Heat rotis',recipeId:ready.id,servings:4}],entries:[{date:week,slot:'dinner',meal:`Heated rotis ${suffix}`,servings:4,components:[{name:ready.title,source:'task',taskId:readyTask,action:'heat',quantity:8,unit:'pieces'}]}]});
  await page.goto(`/app?view=plan&week=${week}`); await page.locator('.meal').getByRole('button',{name:'Save as meal'}).click();await save(page);
  const heated=(await request(page,'get',`/api/meals?query=Heated%20rotis%20${suffix}`)).items[0];createdMeals.push(heated.id);
  expect(heated.components[0]).toMatchObject({source:'ready',recipeId:ready.id,action:'heat',taskId:null});
});

async function mountMcp(page, data) {
  await page.route('**/meal-library-host', route=>route.fulfill({contentType:'text/html',body:`<!doctype html><iframe src="/static/mcp-app.html" style="width:100%;height:1000px"></iframe><script>
  window.ready=false;window.calls=[];addEventListener('message',async event=>{const m=event.data;if(m?.jsonrpc!=='2.0'||!m.method)return;
  if(m.method==='ui/notifications/initialized'){window.ready=true;return;}
  if(m.method==='ui/initialize'){event.source.postMessage({jsonrpc:'2.0',id:m.id,result:{}},'*');return;}
  if(m.method==='tools/call'){window.calls.push(m.params);const res=await fetch('/mcp',{method:'POST',headers:{'Content-Type':'application/json',Accept:'application/json, text/event-stream'},body:JSON.stringify(m)});event.source.postMessage(await res.json(),'*');}});</script>`}));
  await page.goto('/meal-library-host');await expect.poll(()=>page.evaluate(()=>window.ready)).toBe(true);
  await page.evaluate(data=>document.querySelector('iframe').contentWindow.postMessage({jsonrpc:'2.0',method:'ui/notifications/tool-result',params:{structuredContent:data}},'*'),data);
}
test('MCP App Meals category searches via real tools, preserves failed planning, and plans scaled food', async ({page})=>{
  const meal=await request(page,'put','/api/meals',{name:`Chat dinner ${suffix}`,servings:2,components:[{name:`Ready rotis ${suffix}`,quantity:4,unit:'pieces'}]});
  const household=await request(page,'get','/api/household');
  await mountMcp(page,{kind:'meal_library',library:await request(page,'get','/api/meals'),household});
  const frame=page.frameLocator('iframe');
  await frame.getByLabel('Search recipes', {exact:true}).fill(`Ready rotis ${suffix}`);
  await expect(frame.locator('[data-saved-meal]')).toHaveCount(1);
  await frame.getByRole('button',{name:'Plan this meal'}).click();
  const form=frame.locator('#plan-saved-meal-form');
  await form.getByLabel('Date',{exact:true}).fill(week);await form.getByLabel('Servings to plan').fill('6');
  await request(page,'delete',`/api/meals/${meal.id}`);
  await form.getByRole('button',{name:'Add to weekly plan'}).click(); await expect(form.locator('.form-error')).toContainText('Archived');
  await expect(form.getByLabel('Servings to plan')).toHaveValue('6');
  expect((await request(page,'get',`/api/meal-plan?week_start=${week}`)).plan.entries).toHaveLength(0);
  const replacement=await request(page,'put','/api/meals',{...meal,id:undefined});
  await frame.getByLabel('Search recipes', {exact:true}).fill(suffix);
  await frame.locator(`[data-saved-meal="${replacement.id}"]`).getByRole('button',{name:'Plan this meal'}).click();
  await expect(form).toHaveAttribute('data-id',replacement.id);
  await form.getByLabel('Date',{exact:true}).fill(week);await form.getByLabel('Servings to plan').fill('6'); await form.getByRole('button',{name:'Add to weekly plan'}).click();
  await expect(frame.locator('[data-plan-meal]')).toContainText('12 pieces');
  const plan=(await request(page,'get',`/api/meal-plan?week_start=${week}`)).plan;
  expect(plan.entries[0].sourceMeal.id).toBe(replacement.id);expect(plan.entries[0].components[0].quantity).toBe(12);
  expect(await page.evaluate(()=>window.calls.map(row=>row.name))).toEqual(expect.arrayContaining(['browse_recipe_library','get_meal','plan_saved_meal']));
});

test('new meal recipe picker includes recipes beyond the first page and fills the dish name and serving unit', async ({page}) => {
  const older = await request(page, 'put', '/api/recipes', {title: `Old recipe ${suffix}`, servings: 4});
  for (let i=0; i<51; i++) await request(page, 'put', '/api/recipes', {title: `Picker recipe ${suffix} ${i}`});
  await page.goto('/app?view=recipes&type=meals'); await page.getByRole('button', {name:'Create meal'}).click();
  await dialog(page).getByLabel('Meal name', {exact:true}).fill(`Recipe meal ${suffix}`);
  const row=dialog(page).locator('.component-row');
  await choose(row, '-source', 'cook'); await choose(row, '-recipeId', older.id);
  await expect(row.getByLabel('Food or dish')).toHaveValue(older.title);
  await expect(row.getByLabel('Unit', {exact:true})).toHaveValue('servings');
  await row.getByLabel('Amount', {exact:true}).fill('4'); await save(page);
  const meal=(await request(page, 'get', `/api/meals?query=${suffix}`)).items[0];
  expect(meal.components[0]).toMatchObject({name:older.title, recipeId:older.id, unit:'servings', quantity:4});
});

test('one library mixes recipes, ready food and meals, filters them, and opens component details without losing the meal filter', async ({page}) => {
  const recipe=await request(page,'put','/api/recipes',{title:`Dal ${suffix}`,servings:4,ingredients:[{name:'Lentils',quantity:200,unit:'g'}]});
  await page.goto('/app?view=recipes');
  await page.getByRole('button',{name:'Add recipe',exact:true}).click();
  await choose(dialog(page),'kind','ready_food');
  await dialog(page).getByLabel('Recipe name',{exact:true}).fill(`Pre-cooked rotis ${suffix}`);
  await dialog(page).getByLabel('Tags, separated by commas',{exact:true}).fill('quick');
  await dialog(page).getByLabel('Ingredients — one per line: name | quantity | unit').fill('Flour | 100 | g');
  await dialog(page).locator('#dialog-save').click();
  await expect(dialog(page).locator('#dialog-error')).toContainText('Ready food has no ingredient demand');
  await dialog(page).getByLabel('Ingredients — one per line: name | quantity | unit').fill('');
  await save(page);
  const ready=(await request(page,'get',`/api/recipes?query=${suffix}&limit=25`)).items.find(row=>row.kind==='ready_food');
  expect(ready).toBeTruthy(); createdRecipes.push(ready.id);
  await page.getByRole('button',{name:'← All recipes',exact:true}).click();
  await page.getByRole('button',{name:'Create meal',exact:true}).click();
  await dialog(page).getByLabel('Meal name',{exact:true}).fill(`Dinner ${suffix}`);
  const first=dialog(page).locator('.component-row').first();
  await choose(first,'-recipeId',recipe.id); await expect(first.locator('input[name$="-source"]')).toHaveValue('cook');
  await expect(first.locator('input[name$="-action"]')).toHaveValue('cook');
  await first.getByLabel('Amount',{exact:true}).fill('4');
  await dialog(page).getByRole('button',{name:'Add component',exact:true}).click();
  const second=dialog(page).locator('.component-row').nth(1);
  await choose(second,'-recipeId',ready.id); await expect(second.locator('input[name$="-source"]')).toHaveValue('ready');
  await second.getByLabel('Amount',{exact:true}).fill('8'); await second.getByLabel('Unit',{exact:true}).fill('pieces');
  await save(page);
  const meal=(await request(page,'get',`/api/meals?query=${suffix}`)).items[0]; createdMeals.push(meal.id);
  expect(meal.components[1]).toMatchObject({recipeId:ready.id,source:'ready',name:ready.title});
  await page.goto(`/app?view=recipes&query=${suffix}`);
  await expect(page.locator('.recipe-card')).toHaveCount(2); await expect(page.locator('[data-saved-meal]')).toHaveCount(1);
  const type=page.getByRole('combobox',{name:'Library type'});
  await type.selectOption('ready_food'); await expect(page.locator('.recipe-card')).toHaveCount(1);
  await expect(page.locator('.recipe-card')).toContainText(ready.title); await expect(page.locator('[data-saved-meal]')).toHaveCount(0);
  await type.selectOption('meals'); await expect(page.locator('[data-saved-meal]')).toHaveAttribute('data-saved-meal',meal.id);
  await page.locator('#recipe-search').fill(`Dinner ${suffix}`);
  await page.getByRole('group',{name:'Browse recipes by'}).getByRole('button',{name:'Tags',exact:true}).click();
  await page.locator('.rb-options').getByRole('button',{name:/^quick /}).click();
  await expect(page.locator('[data-saved-meal]')).toHaveAttribute('data-saved-meal',meal.id);
  await page.getByRole('button',{name:'Clear tag',exact:true}).click();
  await page.locator('#recipe-search').fill(suffix);
  await page.locator('[data-saved-meal]').getByRole('button',{name:recipe.title,exact:true}).click();
  await expect(page.locator('.hero h2')).toHaveText(recipe.title); await expect(page.locator('#app-content')).toContainText('Lentils');
  await page.getByRole('button',{name:'← All recipes',exact:true}).click();
  await expect(type).toHaveValue('meals'); await expect(page.locator('#recipe-search')).toHaveValue(suffix);
  await page.locator('[data-saved-meal]').getByRole('button',{name:ready.title,exact:true}).click();
  await expect(page.locator('.hero h2')).toHaveText(ready.title); await expect(page.locator('.hero .eyebrow')).toHaveText('Ready food');
  await page.goBack(); await expect(page.locator('[data-saved-meal]')).toHaveAttribute('data-saved-meal',meal.id);
  await page.reload(); await expect(type).toHaveValue('meals'); await expect(page.locator('#recipe-search')).toHaveValue(suffix);
  expect(new URL(page.url()).searchParams.get('view')).toBe('recipes');
  await page.locator('[data-saved-meal]').getByRole('button',{name:ready.title,exact:true}).click();
  await page.getByRole('button',{name:'Create share link',exact:true}).click();
  const shareUrl=await page.getByRole('textbox',{name:'New recipe share link'}).inputValue();
  await page.goto(shareUrl);await page.locator('#save-recipe').click();
  await expect(page.locator('#message')).toHaveText('Saved to your household recipes.');
  const copies=(await request(page,'get',`/api/recipe-library?item_type=ready_food&query=${suffix}`)).items;
  expect(copies).toHaveLength(2);expect(copies.every(row=>row.kind==='ready_food')).toBe(true);
  createdRecipes.push(copies.find(row=>row.id!==ready.id).id);
});

test('MCP App shares type filters and opens recipes and ready food from a meal, retaining the filtered library', async ({page}) => {
  const recipe=await request(page,'put','/api/recipes',{title:`Dal ${suffix}`,servings:4,ingredients:[{name:'Lentils',quantity:200,unit:'g'}]});
  const ready=await request(page,'put','/api/recipes',{title:`Rotis ${suffix}`,kind:'ready_food',instructions:['Heat for a minute']});
  const meal=await request(page,'put','/api/meals',{name:`Dinner ${suffix}`,servings:4,components:[{name:recipe.title,recipeId:recipe.id,source:'cook',quantity:4,unit:'servings'},{name:ready.title,recipeId:ready.id,source:'ready',quantity:8,unit:'pieces'}]});
  const data=await request(page,'get',`/api/recipe-library?item_type=all&query=${suffix}`),household=await request(page,'get','/api/household');
  await mountMcp(page,{kind:'recipe_library',...data,household});
  const frame=page.frameLocator('iframe'),type=frame.getByRole('combobox',{name:'Library type'});
  await expect(frame.locator('.recipe-card')).toHaveCount(2); await expect(frame.locator('[data-saved-meal]')).toHaveCount(1);
  await type.selectOption('ready_food');await expect(frame.locator('.recipe-card')).toHaveCount(1);await expect(frame.locator('[data-saved-meal]')).toHaveCount(0);
  await type.selectOption('meals');await expect(frame.locator('[data-saved-meal]')).toHaveAttribute('data-saved-meal',meal.id);
  await frame.locator('[data-saved-meal]').getByRole('button',{name:ready.title,exact:true}).click();
  await expect(frame.locator('.recipe-detail')).toContainText('Heat for a minute');
  await frame.getByRole('button',{name:'← All recipes',exact:true}).click();
  await expect(type).toHaveValue('meals');await expect(frame.getByLabel('Search recipes',{exact:true})).toHaveValue(suffix);
  await frame.locator('[data-saved-meal]').getByRole('button',{name:recipe.title,exact:true}).click();
  await expect(frame.locator('.recipe-detail')).toContainText('Lentils');
  expect(await page.evaluate(()=>window.calls.filter(row=>row.name==='get_recipe').map(row=>row.arguments.recipe_id))).toEqual([ready.id,recipe.id]);
});
