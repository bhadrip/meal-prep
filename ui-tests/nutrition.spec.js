const {test, expect} = require('@playwright/test');
const week = '2045-02-06';
async function choose(row, nutrient, value) {
  const nutrition = row.locator('details.variation-nutrition-editor');
  if (await nutrition.count() && !(await nutrition.getAttribute('open') !== null)) await nutrition.locator('summary').click();
  const parent = row.locator(`input[name$="-${nutrient}"]`).locator('..');
  await parent.locator('.choice-trigger').click();
  await parent.locator(`[data-choice-value="${value}"]`).click();
}
test('serving variations save macro amounts and food sources, reject invalid amounts, and clear', async ({page}) => {
  await page.request.put('/api/meal-plan', {data: {weekStart: week, entries: [], tasks: []}});
  await page.goto(`/app?view=plan&week=${week}`);
  await expect(page.locator('.nutrition-card')).toHaveCount(0);
  await expect(page.getByText('One meal, different plates', {exact:true})).toHaveCount(0);
  await page.getByRole('button', {name: 'Add meal', exact: true}).click();
  await page.locator('#editor-dialog').getByRole('button', {name: 'Advanced meal details'}).click();
  const editor = page.locator('#editor-dialog');
  await editor.locator('[name="meal"]').fill('Teriyaki noodles');
  await editor.getByLabel('Food or dish', {exact: true}).fill('Noodles, tofu, edamame and broccoli');
  await editor.getByLabel('Nutrition basis / assumptions').fill('Ingredient estimate, portions unverified');
  for (const [name, serving, protein, carbs] of [['Standard', 'Mild steamed noodles', 'low', 'high'], ['Protein-heavy', 'Smaller noodle portion, add tofu and gochujang', 'high', 'moderate']]) {
    await editor.getByRole('button', {name: 'Add variation'}).click();
    const row = editor.locator('[data-nutrition-profile]').last();
    await row.getByLabel('Variation name').fill(name);
    await row.getByLabel('What changes in this variation?').fill(serving);
    await choose(row, 'protein', protein); await choose(row, 'carbs', carbs);
  }
  const proteinPlate = editor.locator('[data-nutrition-profile]').last();
  await proteinPlate.getByLabel('Portion for numeric values').fill('1 protein-heavy bowl');
  await proteinPlate.getByLabel('Calories (kcal)', {exact:true}).fill('520');
  await proteinPlate.getByLabel('Protein (g)', {exact:true}).fill('35.5');
  await proteinPlate.getByLabel('Fat (g)', {exact:true}).fill('0');
  await proteinPlate.getByLabel('Micronutrients').fill('Iron | Tofu | -3 | mg');
  await editor.locator('#dialog-save').click();
  await expect(editor.locator('#dialog-error')).toContainText('nonnegative');
  expect((await (await page.request.get(`/api/meal-plan?week_start=${week}`)).json()).plan.entries).toHaveLength(0);
  await proteinPlate.getByLabel('Micronutrients').fill('Iron | Tofu | 3.2 | mg\nVitamin C | Broccoli');
  await editor.locator('#dialog-save').click();
  await expect(editor).toBeHidden();
  await page.reload();
  const meal = page.locator('.meal').filter({hasText: 'Teriyaki noodles'});
  await meal.locator('.nutrition-details summary').click();
  const guide = meal.locator('.nutrition-guide');
  await expect(guide.locator('.nutrition-profile:visible')).toHaveCount(1);
  await expect(guide.locator('.nutrition-profile').filter({hasText:'Protein-heavy'})).toBeHidden();
  await guide.getByRole('button', {name:'Protein-heavy', exact:true}).click();
  await expect(guide.locator('.nutrition-profile').filter({hasText:'Standard'})).toBeHidden();

  await expect(meal.locator('.nutrition-profile').filter({hasText: 'Protein-heavy'}).locator('[data-nutrient="protein"]')).toHaveAttribute('data-level', 'high');
  await expect(meal.locator('.nutrition-profile').filter({hasText: 'Standard'}).locator('[data-nutrient="carbs"]')).toHaveAttribute('data-level', 'high');
  await expect(meal).toContainText('Broccoli');
  await expect(meal.locator('[data-amount="calories"]')).toHaveText('≈ 520 kcal');
  await expect(meal.locator('[data-amount="protein"]')).toHaveText('≈ 35.5 g');
  await expect(meal.locator('[data-amount="fat"]')).toHaveText('≈ 0 g');
  await expect(meal.locator('[data-amount="fiber"]')).toHaveText('Unknown');
  await expect(meal).toContainText('Iron · ≈ 3.2 mg · Tofu');
  await meal.locator('.nutrition-guide').screenshot({path: '/tmp/meal-nutrition-numbers-preview.png'});
  await page.setViewportSize({width:390, height:844});
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await meal.getByRole('button', {name:'Edit', exact:true}).click();
  await expect(editor.locator('[data-nutrition-profile]')).toHaveCount(2);
  await expect(editor.getByLabel('Protein (g)', {exact:true}).last()).toHaveValue('35.5');
  await editor.getByLabel('Variation name').first().fill('Quick');
  await editor.locator('#dialog-save').click();
  await expect(editor).toBeHidden();
  await expect(page.locator('[data-weekly-profile="Quick"]')).toHaveCount(0);
  await expect(meal.locator('.nutrition-details')).toContainText('Quick');

  await expect(page.locator('[data-weekly-profile="Protein-heavy"] [data-weekly-amount="protein"]')).toHaveText('35.5 g');
  await meal.getByRole('button', {name:'Edit', exact:true}).click();

  await editor.getByRole('button', {name:'Remove variation'}).first().click();
  await editor.getByRole('button', {name:'Remove variation'}).click();
  await editor.locator('#dialog-save').click();
  await expect(editor).toBeHidden();
  await expect(meal.locator('.nutrition-details')).toHaveCount(0);
  await expect(page.locator('.weekly-nutrition')).toHaveCount(0);
  expect((await (await page.request.get(`/api/meal-plan?week_start=${week}`)).json()).plan.entries[0].nutrition).toBeNull();
});

test('self-contained MCP App shows saved plates without meal completion actions', async ({page}) => {
  const nutrition = {basis:'Ingredient estimate', profiles:[{name:'Protein-heavy', serving:'Add tofu', portion:'1 labeled serving', valueType:'label', amounts:{calories:400, protein:28, fat:0}, macros:{protein:'high'}, micronutrients:[{nutrient:'Iron', source:'Tofu', amount:3, unit:'mg'}]}]};
  nutrition.profiles.push({name:'Standard', serving:'Original noodles', portion:'1 bowl', valueType:'estimated', amounts:{protein:12}, micronutrients:[]});
  const response = await page.request.put('/api/meal-plan', {data:{weekStart:week, entries:[{date:week, slot:'dinner', meal:'MCP noodles', nutrition}], tasks:[]}});
  expect(response.ok()).toBeTruthy(); const plan = await response.json();
  plan.nutritionSummary = await (await page.request.get(`/api/meal-plan/nutrition?week_start=${week}`)).json();
  const resource = await page.request.post('/mcp', {headers:{Accept:'application/json, text/event-stream'}, data:{jsonrpc:'2.0', id:1, method:'resources/read', params:{uri:'ui://meal-prep/meal-plan-v2.html'}}});
  const html = (await resource.json()).result.contents[0].text;
  await page.route('**/nutrition-host', route => route.fulfill({contentType:'text/html',body:`<!doctype html><iframe style="width:100%;height:900px"></iframe><script>
    window.ready=false;
    addEventListener('message',async event=>{const m=event.data;if(m?.jsonrpc!=='2.0'||!m.method)return;
      if(m.method==='ui/notifications/initialized'){window.ready=true;return;}
      if(m.method==='ui/initialize'){event.source.postMessage({jsonrpc:'2.0',id:m.id,result:{}},'*');return;}
      if(m.method==='tools/call'){const r=await fetch('/mcp',{method:'POST',headers:{'Content-Type':'application/json',Accept:'application/json, text/event-stream'},body:JSON.stringify(m)});event.source.postMessage(await r.json(),'*');}
    });</script>`}));
  await page.goto('/nutrition-host');
  await page.evaluate(html => {document.querySelector('iframe').srcdoc=html;}, html);
  await expect.poll(() => page.evaluate(() => window.ready)).toBe(true);
  await page.evaluate(plan => document.querySelector('iframe').contentWindow.postMessage({jsonrpc:'2.0',method:'ui/notifications/tool-result',params:{structuredContent:{kind:'meal_plan',plan}}},'*'),plan);
  const frame=page.frameLocator('iframe');
  await frame.locator('.nutrition-details summary').click();
  const guide = frame.locator('.nutrition-guide');
  await expect(guide.locator('.nutrition-profile:visible')).toHaveCount(1);
  await expect(guide.locator('.nutrition-profile:visible [data-amount="protein"]')).toHaveText('≈ 12 g');
  await guide.getByRole('button', {name:'Protein-heavy',exact:true}).press('Enter');
  await expect(guide.getByRole('button', {name:'Protein-heavy',exact:true})).toHaveAttribute('aria-pressed','true');
  await expect(guide.locator('.nutrition-profile:visible')).toHaveCount(1);

  await expect(guide.locator('.nutrition-profile:visible [data-nutrient="protein"]')).toHaveAttribute('data-level','high');
  await expect(guide.locator('.nutrition-profile:visible')).toContainText('Iron · 3 mg · Tofu');
  await expect(guide.locator('.nutrition-profile:visible [data-amount="protein"]')).toHaveText('28 g');
  await expect(guide.locator('.nutrition-profile:visible [data-amount="fat"]')).toHaveText('0 g');
  await expect(guide.locator('.nutrition-profile:visible [data-amount="carbs"]')).toHaveText('Unknown');
  await expect(guide.locator('.nutrition-profile:visible .nutrition-numbers')).toContainText('From label · 1 labeled serving');
  await expect(frame.getByRole('button',{name:'Record eaten',exact:true})).toHaveCount(0);
  const saved=(await (await page.request.get(`/api/meal-plan?week_start=${week}`)).json()).plan;
  expect(saved.entries[0].nutrition).toEqual(plan.entries[0].nutrition);
  await frame.locator('.weekly-nutrition').getByRole('button',{name:'Protein-heavy',exact:true}).click();
  await expect(frame.locator('.weekly-nutrition .nutrition-profile:visible [data-weekly-amount="protein"]')).toHaveText('28 g');
  const recipe = await (await page.request.put('/api/recipes', {data:{title:'MCP recipe numbers', nutrition}})).json();
  await page.evaluate(recipe => document.querySelector('iframe').contentWindow.postMessage({jsonrpc:'2.0',method:'ui/notifications/tool-result',params:{structuredContent:{kind:'recipe_library',recipes:[recipe]}}},'*'),recipe);
  await frame.getByRole('button',{name:'Open MCP recipe numbers'}).click();
  await frame.locator('.recipe-nutrition').getByRole('button',{name:'Protein-heavy',exact:true}).click();
  await expect(frame.locator('.recipe-nutrition .nutrition-profile:visible [data-amount="protein"]')).toHaveText('28 g');
  await expect(frame.locator('.recipe-nutrition')).toContainText('Iron · 3 mg · Tofu');
  const emptyPlan = await (await page.request.put('/api/meal-plan', {data:{weekStart:'2045-02-20', entries:[{date:'2045-02-20',slot:'dinner',meal:'No facts dinner'}],tasks:[]}})).json();
  await page.evaluate(plan => document.querySelector('iframe').contentWindow.postMessage({jsonrpc:'2.0',method:'ui/notifications/tool-result',params:{structuredContent:{kind:'meal_plan',plan}}},'*'),emptyPlan);
  await expect(frame.locator('[data-plan-meal]')).toContainText('No facts dinner');
  await expect(frame.locator('.nutrition-details')).toHaveCount(0);
  await expect(frame.locator('.weekly-nutrition')).toHaveCount(0);
  await expect(frame.getByText('preview only', {exact:false})).toHaveCount(0);
  const noFacts = await (await page.request.put('/api/recipes', {data:{title:'MCP no facts'}})).json();
  await page.evaluate(recipe => document.querySelector('iframe').contentWindow.postMessage({jsonrpc:'2.0',method:'ui/notifications/tool-result',params:{structuredContent:{kind:'recipe_library',recipes:[recipe]}}},'*'),noFacts);
  await frame.getByRole('button',{name:'Open MCP no facts'}).click();
  await expect(frame.getByRole('heading',{name:'MCP no facts',exact:true})).toBeVisible();
  await expect(frame.locator('.recipe-nutrition')).toHaveCount(0);
});

test('weekly totals update after clearing saved nutrition and show incomplete coverage', async ({page}) => {
  const week = '2045-02-13';
  const guide = protein => ({basis:'Test estimates', profiles:[{name:'Protein-heavy',serving:'Tofu bowl',portion:'1 bowl',amounts:{protein,fat:0},micronutrients:[{nutrient:'Iron',source:'Tofu',amount:2,unit:'mg'}]}]});
  const response = await page.request.put('/api/meal-plan', {data:{weekStart:week, entries:[
    {date:week,slot:'dinner',meal:'Monday bowl',nutrition:guide(30)},
    {date:'2045-02-14',slot:'dinner',meal:'Tuesday bowl',nutrition:guide(25)},
    {date:'2045-02-15',slot:'dinner',meal:'Unassessed dinner'}], tasks:[]}});
  expect(response.ok()).toBeTruthy();
  await page.goto(`/app?view=plan&week=${week}`);
  const summary = page.locator('.weekly-nutrition');
  await expect(summary.locator('[data-weekly-amount="protein"]')).toHaveText('55 g');
  await expect(summary).toContainText('2 of 3 meals recorded');
  await expect(summary.locator('[data-weekly-amount="calories"]')).toHaveText('Unknown');
  await page.locator('.meal').filter({hasText:'Tuesday bowl'}).getByRole('button',{name:'Edit',exact:true}).click();
  await page.locator('#editor-dialog').getByRole('button',{name:'Remove variation',exact:true}).click();
  await page.locator('#dialog-save').click();
  await expect(page.locator('#editor-dialog')).toBeHidden();
  await expect(summary.locator('[data-weekly-amount="protein"]')).toHaveText('30 g');
  await expect(summary).toContainText('1 of 3 meals recorded');
  await page.reload();
  await expect(summary.locator('[data-weekly-amount="protein"]')).toHaveText('30 g');
  const api = await (await page.request.get(`/api/meal-plan/nutrition?week_start=${week}`)).json();
  expect(api.profiles[0].amounts.protein).toEqual({total:30, coveredMeals:1});
});

test('recipe nutrition edits persist, reject invalid units, and clear without changing the recipe', async ({page}) => {
  const saved = await (await page.request.put('/api/recipes',{data:{title:`Numeric recipe ${Date.now()}`,servings:4}})).json();
  await page.goto(`/app?view=recipes&recipe=${saved.id}`);
  const section = page.locator('.recipe-nutrition');
  await expect(section).toHaveCount(0);
  await page.getByRole('button',{name:'Edit recipe',exact:true}).click();
  const editor = page.locator('#editor-dialog');
  await editor.getByLabel('Nutrition basis / assumptions').fill('Ingredient estimate');
  await editor.getByRole('button',{name:'Add variation'}).click();
  const row = editor.locator('[data-nutrition-profile]');
  await row.getByLabel('Variation name').fill('Base serving');
  await row.getByLabel('What changes in this variation?').fill('Serve one bowl');
  await row.locator('.variation-nutrition-editor summary').click();
  await row.getByLabel('Portion for numeric values').fill('1 bowl, one quarter of recipe');
  await row.getByLabel('Protein (g)',{exact:true}).fill('28');
  await row.getByLabel('Calories (kcal)',{exact:true}).fill('450');
  await row.getByLabel('Micronutrients').fill('Iron | Tofu | 3 | cups');
  await editor.locator('#dialog-save').click();
  await expect(editor.locator('#dialog-error')).toContainText('unit');
  expect((await (await page.request.get(`/api/recipes/${saved.id}`)).json()).nutrition ?? null).toBeNull();
  await row.getByLabel('Micronutrients').fill('Iron | Tofu | 3 | mg');
  await editor.locator('#dialog-save').click();
  await expect(editor).toBeHidden();
  await expect(section.locator('[data-amount="protein"]')).toHaveText('≈ 28 g');
  await page.reload();
  await expect(section.locator('[data-amount="calories"]')).toHaveText('≈ 450 kcal');
  await expect(section).toContainText('Iron · ≈ 3 mg · Tofu');
  await page.getByRole('button',{name:'Edit recipe',exact:true}).click();
  await editor.getByRole('button',{name:'Remove variation'}).click();
  await editor.locator('#dialog-save').click();
  await expect(editor).toBeHidden();
  await expect(section).toHaveCount(0);
  await expect(page.getByRole('heading',{name:saved.title,exact:true})).toBeVisible();
});

test('recipe variation toggle shows exactly one plate and leaves saved numbers unchanged', async ({page}) => {
  const nutrition = {basis:'Estimates for test',profiles:[
    {name:'Standard',serving:'Original noodles',portion:'1 bowl',amounts:{protein:14}},
    {name:'Protein-heavy',serving:'Add tofu',portion:'1 bowl',amounts:{protein:35}}]};
  const recipe = await (await page.request.put('/api/recipes', {data:{title:'Toggle recipe',nutrition}})).json();
  await page.goto(`/app?view=recipes&recipe=${recipe.id}`);
  const card=page.locator('.recipe-nutrition');
  await expect(card.locator('.nutrition-profile:visible')).toHaveCount(1);
  await expect(card.locator('.nutrition-profile:visible [data-amount="protein"]')).toHaveText('≈ 14 g');
  await card.getByRole('button',{name:'Protein-heavy',exact:true}).click();
  await expect(card.locator('.nutrition-profile:visible')).toHaveCount(1);
  await expect(card.locator('.nutrition-profile:visible [data-amount="protein"]')).toHaveText('≈ 35 g');
  await expect(card.getByRole('button',{name:'Standard',exact:true})).toHaveAttribute('aria-pressed','false');
  await card.getByRole('button',{name:'Standard',exact:true}).press('Enter');
  await expect(card.locator('.nutrition-profile:visible [data-amount="protein"]')).toHaveText('≈ 14 g');
  expect((await (await page.request.get(`/api/recipes/${recipe.id}`)).json()).nutrition).toEqual(recipe.nutrition);
  await page.setViewportSize({width:390,height:844});
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});

test('adding a recipe accepts custom variations without nutrition, shows only saved choices, and hides removed toggles', async ({page}) => {
  await page.goto('/app?view=recipes');
  await page.getByRole('button',{name:'Add recipe',exact:true}).click();
  const editor=page.locator('#editor-dialog');
  const title=`Custom variations ${Date.now()}`;
  await editor.getByLabel('Recipe name',{exact:true}).fill(title);
  const notes = ['Toast sesame seeds and finish with lime.', 'Add butter and a richer sauce.', 'Use olive oil and extra vegetables.'];
  for (const [index,name] of ['Tasty','Decadent','Heart healthy'].entries()) {
    await editor.getByRole('button',{name:'Add variation',exact:true}).click();
    const row=editor.locator('[data-nutrition-profile]').last();
    await row.getByLabel('Variation name').fill(name);
    await row.getByLabel('What changes in this variation?').fill(notes[index]);
    await expect(row.locator('.variation-nutrition-editor')).not.toHaveAttribute('open','');
  }
  await editor.locator('#dialog-save').click();
  await expect(editor).toBeHidden();
  const card=page.locator('.recipe-nutrition');
  await expect(card.getByRole('button',{name:'Tasty',exact:true})).toHaveAttribute('aria-pressed','true');
  await expect(card.getByRole('button',{name:'Standard',exact:true})).toHaveCount(0);
  await card.getByRole('button',{name:'Decadent',exact:true}).click();
  await expect(card.locator('.nutrition-profile:visible')).toContainText(notes[1]);
  await expect(card.locator('.nutrition-profile:visible')).toHaveCount(1);
  await expect(card.locator('.nutrition-macros')).toHaveCount(0);
  await expect(card.getByRole('heading', {name:'Variations',exact:true})).toBeVisible();
  await expect(card).not.toContainText('Nutrition');
  await page.reload();
  await card.getByRole('button',{name:'Heart healthy',exact:true}).click();
  await expect(card.locator('.nutrition-profile:visible')).toContainText(notes[2]);
  await page.getByRole('button',{name:'Edit recipe',exact:true}).click();
  await editor.getByLabel('Variation name').last().fill('Tasty');
  await editor.locator('#dialog-save').click();
  await expect(editor.locator('#dialog-error')).toContainText('unique');
  await editor.getByLabel('Variation name').last().fill('Heart healthy');
  while (await editor.getByRole('button',{name:'Remove variation',exact:true}).count()) {
    await editor.getByRole('button',{name:'Remove variation',exact:true}).first().click();
  }
  await editor.locator('#dialog-save').click();
  await expect(editor).toBeHidden();
  await expect(card).toHaveCount(0);
  await expect(page.getByRole('heading',{name:title,exact:true})).toBeVisible();
});
