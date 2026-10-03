const { test, expect } = require('@playwright/test');

const editor = (page) => page.locator('#editor-dialog');
const rulesCard = (page) => page.locator('article.card').filter({ has: page.getByRole('heading', { name: 'Meal preferences', exact: true }) });

async function openPlan(page) {
  await page.goto('/app?view=plan');
  await expect(page.locator('#view-title')).toHaveText('Weekly plan');
  await expect(page.getByRole('tab', { name: 'Meals', exact: true })).toHaveAttribute('aria-selected', 'true');
  await expect(page.locator('#week-picker')).toBeVisible();
}

async function saveRules(page, text) {
  await page.getByRole('tab', { name: 'Preferences', exact: true }).click();
  await page.getByRole('button', { name: 'Edit meal preferences', exact: true }).click();
  await editor(page).locator('[name="text"]').fill(text);
  const saved = page.waitForResponse((r) => r.url().endsWith('/api/meal-plan-rules') && r.request().method() === 'PUT');
  await editor(page).locator('#dialog-save').click();
  const response = await saved;
  expect(response.ok()).toBeTruthy();
  await expect(editor(page)).toBeHidden();
  await expect(rulesCard(page).locator('.planning-text').first()).toHaveText(text || 'No recurring preferences in this version.');
  return response.json();
}

test('unavailable planning rules leave the plan usable and retry from the rules tab', async ({ page }) => {
  let fail = true;
  let rulesReads = 0;
  await page.route('**/api/app/snapshot?*', async (route) => {
    const params = new URL(route.request().url()).searchParams;
    if (params.get('sections') !== 'mealPlanRules') return route.continue();
    rulesReads += 1;
    if (fail) return route.fulfill({ status: 503, json: { detail: 'Rules unavailable' } });
    const data = await (await route.fetch()).json();
    data.sections.mealPlanRules = { status: 'ready', value: { revision: 3, text: 'Keep Tuesday dinner quick.' } };
    await route.fulfill({ json: data });
  });
  await page.goto('/app');
  await expect(page.locator('[data-home-section="mealPlan"] .section-loading')).toHaveCount(0);
  expect(rulesReads).toBe(0);
  await page.getByRole('button', { name: 'Open weekly plan', exact: true }).click();
  await expect(page.locator('#week-picker')).toBeVisible();
  await expect.poll(() => rulesReads).toBe(1);
  await page.getByRole('tab', { name: 'Preferences', exact: true }).click();
  await expect(page.locator('#app-content')).toContainText('Could not load meal preferences');
  await page.getByRole('tab', { name: 'Meals', exact: true }).click();
  await expect(page.locator('#week-picker')).toBeVisible();
  await page.getByRole('tab', { name: 'Preferences', exact: true }).click();
  fail = false;
  await page.getByRole('button', { name: 'Try again', exact: true }).click();
  await expect(rulesCard(page).locator('.planning-text')).toHaveText('Keep Tuesday dinner quick.');
  await page.getByRole('tab', { name: 'Meals', exact: true }).click();
  await expect(page.locator('#week-picker')).toBeVisible();
  await page.getByRole('button', { name: 'Add meal', exact: true }).click();
  await editor(page).locator('[name="meal"]').fill('Dinner after retry');
  await editor(page).locator('#dialog-save').click();
  await expect(editor(page)).toBeHidden();
  await expect(page.locator('.meal').filter({ hasText: 'Dinner after retry' })).toBeVisible();
});

test('English rule revisions persist, retain history, and leave existing plans intact', async ({ page }) => {
  await openPlan(page);
  const week = await page.locator('#week-picker').inputValue();
  const original = (await (await page.request.get(`/api/meal-plan?week_start=${week}`)).json()).plan;
  const text = `Saturday pasta.\nBulk cook ambta baaji for Tuesday and Thursday. ${Date.now()}`;
  const first = await saveRules(page, text);
  const secondText = `${text}\nRotate new recipes; intentional leftovers are welcome.`;
  const second = await saveRules(page, secondText);
  expect(second.revision).toBe(first.revision + 1);
  await page.reload();
  await expect(rulesCard(page).locator('.planning-text').first()).toHaveText(secondText);
  await page.getByRole('button', { name: 'View preference history', exact: true }).click();
  await page.locator('#planning-rule-history').getByRole('button', { name: `View version ${first.revision}`, exact: true }).click();
  await expect(page.locator('#planning-rule-preview .planning-text')).toHaveText(text);
  await expect(page.getByRole('button', { name: 'Edit meal preferences', exact: true })).toHaveCount(0);
  await page.getByRole('button', { name: 'View current preferences', exact: true }).click();
  await expect(rulesCard(page).locator('.planning-text').first()).toHaveText(secondText);
  expect((await (await page.request.get(`/api/meal-plan?week_start=${week}`)).json()).plan).toEqual(original);
  await saveRules(page, '');
  await page.getByRole('button', { name: 'View preference history', exact: true }).click();
  await page.locator('#planning-rule-history').getByRole('button', { name: `View version ${first.revision}`, exact: true }).click();
  await expect(page.locator('#planning-rule-preview .planning-text')).toHaveText(text);
});

test('a stale editor retains its draft and can reload a concurrent change', async ({ page }) => {
  await openPlan(page);
  const current = (await (await page.request.get('/api/meal-plan-rules')).json()).rules;
  await page.getByRole('tab', { name: 'Preferences', exact: true }).click();
  await page.getByRole('button', { name: 'Edit meal preferences', exact: true }).click();
  const draft = `My draft ${Date.now()}`;
  await editor(page).locator('[name="text"]').fill(draft);
  const otherText = `Another household member's change ${Date.now()}`;
  const response = await page.request.put('/api/meal-plan-rules', { data: { text: otherText, expectedRevision: current?.revision || 0 } });
  expect(response.ok()).toBeTruthy();
  await editor(page).locator('#dialog-save').click();
  await expect(editor(page).locator('#dialog-error')).toContainText('Meal plan rules changed.');
  await expect(editor(page).locator('[name="text"]')).toHaveValue(draft);
  expect((await (await page.request.get('/api/meal-plan-rules')).json()).rules.text).toBe(otherText);
  await editor(page).getByRole('button', { name: 'Cancel', exact: true }).click();
  await page.getByRole('button', { name: 'Edit meal preferences', exact: true }).click();
  await expect(editor(page).locator('[name="text"]')).toHaveValue(otherText);
  await editor(page).locator('[name="text"]').fill(`${otherText}\n${draft}`);
  await editor(page).locator('#dialog-save').click();
  await expect(editor(page)).toBeHidden();
  await expect(rulesCard(page)).toContainText(draft);
});

test('week notes stay with their week and reach MCP planning context', async ({ page }) => {
  await openPlan(page);
  const week = await page.locator('#week-picker').inputValue();
  const date = new Date(`${week}T12:00:00Z`);
  date.setUTCDate(date.getUTCDate() + 7);
  const nextWeek = date.toISOString().slice(0, 10);
  const note = `Guests Saturday; use leftover spinach. ${Date.now()}`;
  const rhythm = (await (await page.request.get(`/api/schedule?week_start=${week}`)).json()).schedule;
  const rules = (await (await page.request.get('/api/meal-plan-rules')).json()).rules;
  await page.getByRole('button', { name: 'Edit notes', exact: true }).click();
  await editor(page).locator('[name="notes"]').fill(note);
  await editor(page).locator('#dialog-save').click();
  await expect(editor(page)).toBeHidden();
  const notes = page.locator('#week-notes');
  await notes.locator('summary').click();
  await expect(notes).toContainText(note);
  expect((await (await page.request.get(`/api/schedule?week_start=${week}`)).json()).schedule.days).toEqual(rhythm.days);
  for (const text of await page.locator('.day-card > .mode').allTextContents()) expect(text).toMatch(/^[A-Za-z]+ \d{1,2}$/);
  expect((await (await page.request.get('/api/meal-plan-rules')).json()).rules).toEqual(rules);
  await expect(page.getByRole('button', { name: 'Edit weekly rhythm', exact: true })).toHaveCount(0);
  await page.locator('#week-picker').fill(nextWeek);
  await expect(notes).not.toContainText(note);
  await page.locator('#week-picker').fill(week);
  await notes.locator('summary').click();
  await expect(notes).toContainText(note);
  await page.reload();
  await notes.locator('summary').click();
  await expect(notes).toContainText(note);
  const response = await page.request.post('/mcp', {
    headers: { Accept: 'application/json, text/event-stream' },
    data: { jsonrpc: '2.0', id: 1, method: 'tools/call', params: { name: 'get_planning_context', arguments: { week_start: week } } },
  });
  expect((await response.json()).result.structuredContent.schedule.notes).toBe(note);
});

test('manual meal edits keep the rule version used to create the plan', async ({ page }) => {
  await openPlan(page);
  const first = await saveRules(page, `Saturday pasta. ${Date.now()}`);
  const week = '2030-02-04';
  const response = await page.request.put('/api/meal-plan', { data: { weekStart: week, ruleRevisionId: first.id,
    entries: [{ date: week, slot: 'dinner', meal: 'Pasta from Saturday', notes: 'Reuse the batch.' }] } });
  expect(response.ok()).toBeTruthy();
  await saveRules(page, `Saturday stir-fry. ${Date.now()}`);
  await page.getByRole('tab', { name: 'Meals', exact: true }).click();
  await page.locator('#week-picker').fill(week);
  const source = page.locator('#plan-rule-source');
  await expect(source).toContainText(`version ${first.revision}`);
  await page.locator('.meal').filter({ hasText: 'Pasta from Saturday' }).getByRole('button', { name: 'Edit', exact: true }).click();
  await editor(page).locator('[name="meal"]').fill('Pasta with a vegetable side');
  await editor(page).locator('#dialog-save').click();
  await expect(editor(page)).toBeHidden();
  await expect(page.locator('.meal')).toContainText('Pasta with a vegetable side');
  await expect(source).toContainText(`version ${first.revision}`);
  await source.click();
  await expect(page.locator('#planning-rule-preview .planning-text')).toHaveText(first.text);
  await expect(page).toHaveURL(new RegExp(`tab=rules&revision=${first.id}`));
  await page.reload();
  await expect(page.locator('#planning-rule-preview .planning-text')).toHaveText(first.text);
  await expect(page.locator('#planning-panel')).toContainText(`Used for the week of ${week}`);
  await page.getByRole('tab', { name: 'Meals', exact: true }).click();
  await expect(page.locator('#week-picker')).toHaveValue(week);
  await expect(page.locator('.meal')).toContainText('Pasta with a vegetable side');
  expect((await (await page.request.get(`/api/meal-plan?week_start=${week}`)).json()).plan.ruleRevisionId).toBe(first.id);
});

test('tabs preserve the selected week through reload, browser navigation, and keyboard use', async ({ page }) => {
  await openPlan(page);
  const week = '2031-03-03';
  await page.locator('#week-picker').fill(week);
  await expect(page).toHaveURL(new RegExp(`week=${week}`));
  await page.getByRole('tab', { name: 'Preferences', exact: true }).click();
  await expect(page.locator('#week-picker')).toHaveCount(0);
  await expect(page.locator('.week-grid')).toHaveCount(0);
  await page.reload();
  await expect(page.getByRole('tab', { name: 'Preferences', exact: true })).toHaveAttribute('aria-selected', 'true');
  await page.goBack();
  await expect(page.getByRole('tab', { name: 'Meals', exact: true })).toHaveAttribute('aria-selected', 'true');
  await expect(page.locator('#week-picker')).toHaveValue(week);
  await page.goForward();
  await expect(page.getByRole('tab', { name: 'Preferences', exact: true })).toHaveAttribute('aria-selected', 'true');
  await page.getByRole('tab', { name: 'Preferences', exact: true }).focus();
  await page.keyboard.press('Home');
  await expect(page.getByRole('tab', { name: 'Meals', exact: true })).toBeFocused();
  await expect(page.locator('#week-picker')).toHaveValue(week);
  await expect(rulesCard(page)).toHaveCount(0);
});

test('mobile notes editing preserves a failed draft, saves an empty week, and keeps days readable', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await openPlan(page);
  const week = '2031-04-07';
  await page.locator('#week-picker').fill(week);
  await expect(page).toHaveURL(new RegExp(`week=${week}`));
  await page.getByRole('button', { name: 'Edit notes', exact: true }).click();
  await editor(page).locator('[name="notes"]').fill('x'.repeat(3001));
  await editor(page).locator('#dialog-save').click();
  await expect(editor(page).locator('#dialog-error')).toContainText('Week notes');
  await expect(editor(page).locator('[name="notes"]')).toHaveValue('x'.repeat(3001));
  expect((await (await page.request.get(`/api/schedule?week_start=${week}`)).json()).schedule).toBeNull();
  const note = `Guests on Saturday ${Date.now()}`;
  await editor(page).locator('[name="notes"]').fill(note);
  await editor(page).locator('#dialog-save').click();
  await expect(editor(page)).toBeHidden();
  await page.locator('#week-notes summary').click();
  await expect(page.locator('#week-notes .planning-text')).toHaveText(note);
  const monday = page.locator('.day-card').nth(0);
  const tuesday = page.locator('.day-card').nth(1);
  const firstBox = await monday.boundingBox();
  const secondBox = await tuesday.boundingBox();
  expect(secondBox.y).toBeGreaterThan(firstBox.y + firstBox.height);
  expect(secondBox.x).toBe(firstBox.x);
  await tuesday.getByRole('button', { name: 'Add meal to Tuesday' }).click();
  await expect(editor(page).locator('[name="date"]')).toHaveValue('2031-04-08');
  await editor(page).locator('[name="meal"]').fill('Ambta baaji leftovers');
  await editor(page).locator('#dialog-save').click();
  await expect(editor(page)).toBeHidden();
  await expect(tuesday.locator('.meal')).toContainText('Ambta baaji leftovers');
  await page.getByRole('tab', { name: 'Preferences', exact: true }).click();
  await page.getByRole('tab', { name: 'Meals', exact: true }).click();
  await expect(page.locator('#week-picker')).toHaveValue(week);
  await expect(tuesday.locator('.meal')).toContainText('Ambta baaji leftovers');
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy();
});

test('an unavailable rule revision shows an error and can return to the current rules', async ({ page }) => {
  await openPlan(page);
  const current = await saveRules(page, `Usual Saturday pasta ${Date.now()}`);
  await page.goto('/app?view=plan&week=2030-02-04&tab=rules&revision=aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa');
  await expect(page.locator('#planning-panel')).toContainText('Could not load this version');
  await expect(page.locator('#planning-panel')).toContainText('not found');
  await expect(page.locator('#planning-rule-preview')).toHaveCount(0);
  await page.getByRole('button', { name: 'View current preferences', exact: true }).click();
  await expect(rulesCard(page).locator('.planning-text')).toHaveText(current.text);
  await page.getByRole('tab', { name: 'Meals', exact: true }).click();
  await expect(page.locator('#week-picker')).toHaveValue('2030-02-04');
});


test('weekly plan preferences save household defaults, meal rules, and weekly needs together and retain failed drafts', async ({ page }) => {
  await openPlan(page);
  const week = '2032-04-05';
  await page.locator('#week-picker').fill(week);
  await expect(page.getByRole('button', {name:'Edit weekly rhythm',exact:true})).toHaveCount(0);
  await page.getByRole('tab', {name:'Preferences',exact:true}).click();
  const form = page.locator('#settings-form');
  await form.getByLabel('People in household').fill('5');
  await form.getByLabel('Maximum weeknight cooking minutes').fill('25');
  await form.getByLabel('Dietary restrictions').fill('vegetarian, no peanuts');
  await form.getByLabel('Preferred stores, in order').fill('Costco, Safeway');
  await form.getByLabel('Plan dinner leftovers for lunch').check();
  await form.getByLabel('Dinners', {exact:true}).check();
  const before = (await (await page.request.get('/api/household')).json());
  let fail = true;
  await page.route('**/api/household', route => route.request().method() === 'PATCH' && fail
    ? route.fulfill({status:503,json:{detail:'Could not save preferences'}}) : route.continue());
  await form.getByRole('button', {name:'Save preferences',exact:true}).click();
  await expect(page.locator('#toast')).toContainText('Could not save preferences');
  await expect(form.getByLabel('People in household')).toHaveValue('5');
  expect((await (await page.request.get('/api/household')).json())).toEqual(before);
  fail = false;
  await form.getByRole('button', {name:'Save preferences',exact:true}).click();
  await expect(page.locator('#toast')).toContainText('Preferences saved');
  await saveRules(page, 'Use protein-heavy variations when available; keep Tuesday quick.');
  await page.getByRole('button', {name:'Edit notes',exact:true}).click();
  await editor(page).getByLabel('Guests, ingredients to use, or other changes').fill('Guests on Saturday; use the spinach.');
  await editor(page).locator('#dialog-save').click();
  await expect(editor(page)).toBeHidden();
  await page.reload();
  await expect(form.getByLabel('People in household')).toHaveValue('5');
  await expect(form.getByLabel('Maximum weeknight cooking minutes')).toHaveValue('25');
  await expect(form.getByLabel('Dietary restrictions')).toHaveValue('vegetarian, no peanuts');
  await expect(page.locator('#planning-panel')).toContainText('Guests on Saturday; use the spinach.');
  const context = await (await page.request.get(`/api/planning-context?week_start=${week}`)).json();
  expect(context.household.householdSize).toBe(5);
  expect(context.household.planningPreferences.weeknightMaxMinutes).toBe(25);
  expect(context.household.planningPreferences.leftoversForLunch).toBe(true);
  expect(context.mealPlanRules.text).toContain('protein-heavy');
  expect(context.schedule.notes).toBe('Guests on Saturday; use the spinach.');
  await page.getByRole('tab',{name:'Meals',exact:true}).click();
  await expect(page.locator('#week-picker')).toHaveValue(week);
  await page.locator('#week-picker').fill('2032-04-12');
  await page.getByRole('tab',{name:'Preferences',exact:true}).click();
  await expect(form.getByLabel('People in household')).toHaveValue('5');
  await expect(page.locator('#planning-panel')).not.toContainText('Guests on Saturday; use the spinach.');
  await page.setViewportSize({width:390,height:844});
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});


test('initial setup uses the weekly preference editor, retains failed answers, and leaves Settings without duplicate forms', async ({page}) => {
  let incomplete = true;
  let fail = true;
  await page.route('**/api/app/bootstrap?*', async route => {
    const data = await (await route.fetch()).json();
    if (incomplete) Object.assign(data.snapshot.household, {
      onboardingComplete:false, householdSize:null, dietaryRestrictions:null, storePriority:[],
      planningPreferences:{...data.snapshot.household.planningPreferences,weeknightMaxMinutes:null,leftoversForLunch:undefined}
    });
    await route.fulfill({json:data});
  });
  await page.route('**/api/household', async route => {
    if (route.request().method() !== 'PATCH') return route.continue();
    if (fail) return route.fulfill({status:503,json:{detail:'Could not save setup'}});
    const response = await route.fetch();
    if (response.ok()) incomplete = false;
    await route.fulfill({response});
  });
  await page.goto('/app?view=settings');
  await expect(page).toHaveURL(/view=plan.*tab=rules/);
  await expect(page.getByRole('tab',{name:'Preferences',exact:true})).toHaveAttribute('aria-selected','true');
  const form=page.locator('#settings-form');
  await expect(form).toHaveCount(1);
  await form.getByLabel('People in household').fill('2');
  await form.getByLabel('Maximum weeknight cooking minutes').fill('20');
  await form.getByLabel('Dietary restrictions').fill('none');
  await form.getByLabel('Preferred stores, in order').fill('Local market');
  const before=await (await page.request.get('/api/household')).json();
  await form.getByRole('button',{name:'Save preferences',exact:true}).click();
  await expect(page.locator('#toast')).toHaveText('Could not save setup');
  await expect(form.getByLabel('People in household')).toHaveValue('2');
  expect(await (await page.request.get('/api/household')).json()).toEqual(before);
  fail=false;
  await form.getByRole('button',{name:'Save preferences',exact:true}).click();
  await expect(page.locator('#toast')).toHaveText('Preferences saved.');
  const saved=await (await page.request.get('/api/planning-context?week_start=2030-02-04')).json();
  expect(saved.household).toMatchObject({householdSize:2,dietaryRestrictions:[],storePriority:[{store:'Local market',priority:1}]});
  expect(saved.household.planningPreferences.weeknightMaxMinutes).toBe(20);
  await page.locator('.sidebar [data-view="settings"]').click();
  await expect(page.locator('#view-title')).toHaveText('Settings');
  await expect(form).toHaveCount(0);
  await expect(page.getByRole('button',{name:'Edit meal slots',exact:true})).toHaveCount(0);
  await expect(page.locator('#dashboard-form')).toBeVisible();
  await page.reload();
  await expect(form).toHaveCount(0);
  await page.locator('.sidebar [data-view="plan"]').click();
  await page.getByRole('tab',{name:'Preferences',exact:true}).click();
  await expect(form.getByLabel('People in household')).toHaveValue('2');
  await expect(form.getByLabel('Preferred stores, in order')).toHaveValue('Local market');
  await expect(page.getByRole('button',{name:'Edit meal slots',exact:true})).toBeVisible();
});
