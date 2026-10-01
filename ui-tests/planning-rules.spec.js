const { test, expect } = require('@playwright/test');

const editor = (page) => page.locator('#editor-dialog');
const rulesCard = (page) => page.locator('article.card').filter({ has: page.getByRole('heading', { name: 'Planning rules', exact: true }) });

async function openPlan(page) {
  await page.goto('/app?view=plan');
  await expect(page.locator('#view-title')).toHaveText('Weekly plan');
  await expect(rulesCard(page)).toBeVisible();
}

async function saveRules(page, text) {
  await page.getByRole('button', { name: 'Edit planning rules', exact: true }).click();
  await editor(page).locator('[name="text"]').fill(text);
  const saved = page.waitForResponse((r) => r.url().endsWith('/api/meal-plan-rules') && r.request().method() === 'PUT');
  await editor(page).locator('#dialog-save').click();
  const response = await saved;
  expect(response.ok()).toBeTruthy();
  await expect(editor(page)).toBeHidden();
  await expect(rulesCard(page).locator('.planning-text').first()).toHaveText(text || 'No recurring rules in this version.');
  return response.json();
}

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
  await page.getByRole('button', { name: 'View rule history', exact: true }).click();
  const old = page.locator('#planning-rule-history .feedback').filter({ has: page.locator('strong', { hasText: new RegExp(`^Version ${first.revision}$`) }) });
  await expect(old.locator('.planning-text')).toHaveText(text);
  expect((await (await page.request.get(`/api/meal-plan?week_start=${week}`)).json()).plan).toEqual(original);
  await saveRules(page, '');
  await page.getByRole('button', { name: 'View rule history', exact: true }).click();
  await expect(page.locator('#planning-rule-history')).toContainText(text);
});

test('a stale editor retains its draft and can reload a concurrent change', async ({ page }) => {
  await openPlan(page);
  const current = (await (await page.request.get('/api/meal-plan-rules')).json()).rules;
  await page.getByRole('button', { name: 'Edit planning rules', exact: true }).click();
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
  await page.getByRole('button', { name: 'Edit planning rules', exact: true }).click();
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
  await page.getByRole('button', { name: 'Edit weekly rhythm', exact: true }).click();
  await editor(page).locator('[name="notes"]').fill(note);
  await editor(page).locator('#dialog-save').click();
  await expect(editor(page)).toBeHidden();
  const notes = page.locator('article.card').filter({ has: page.getByRole('heading', { name: 'Notes for this week', exact: true }) });
  await expect(notes).toContainText(note);
  await page.locator('#week-picker').fill(nextWeek);
  await expect(notes).not.toContainText(note);
  await page.locator('#week-picker').fill(week);
  await expect(notes).toContainText(note);
  await page.reload();
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
  await page.locator('#week-picker').fill(week);
  const source = page.locator('#plan-rule-source');
  await expect(source).toContainText(`version ${first.revision}`);
  await page.locator('.meal').filter({ hasText: 'Pasta from Saturday' }).getByRole('button', { name: 'Edit', exact: true }).click();
  await editor(page).locator('[name="meal"]').fill('Pasta with a vegetable side');
  await editor(page).locator('#dialog-save').click();
  await expect(editor(page)).toBeHidden();
  await expect(page.locator('.meal')).toContainText('Pasta with a vegetable side');
  await expect(source).toContainText(`version ${first.revision}`);
  await source.locator('summary').click();
  await expect(source.locator('.planning-text')).toHaveText(first.text);
  expect((await (await page.request.get(`/api/meal-plan?week_start=${week}`)).json()).plan.ruleRevisionId).toBe(first.id);
});
