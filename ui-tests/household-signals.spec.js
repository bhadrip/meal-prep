const {test,expect}=require('@playwright/test');
const {navigateToView}=require('./navigation');
const editor=page=>page.locator('#editor-dialog');
async function choose(page,name,value){const parent=editor(page).locator(`input[type=hidden][name="${name}"]`).locator('..');await parent.locator('.choice-trigger').click();await parent.locator(`[data-choice-value="${value}"]`).click();}
async function records(page){const response=await page.request.get('/api/feedback?limit=100');expect(response.ok()).toBeTruthy();return (await response.json()).items;}
async function history(page,table){const response=await page.request.get(`/api/signals/history?source_table=${table}&limit=100`);expect(response.ok()).toBeTruthy();return (await response.json()).items;}
async function save(page){await editor(page).locator('#dialog-save').click();await expect(editor(page)).toBeHidden();}
test.beforeEach(async({page})=>{await page.goto('/app');await navigateToView(page,'reviews');await expect(page.locator('#view-title')).toHaveText('Reviews');});

test('structured reports preserve the goal, actual work, audience and zero amounts after reload',async({page})=>{
  const note=`Kitchen report ${test.info().project.name} ${Date.now()}`;
  await page.getByRole('button',{name:'Review this week',exact:true}).click();
  await editor(page).locator('[name=note]').fill(note);
  await editor(page).getByText('Add details, if useful',{exact:true}).click();
  await choose(page,'signalGoal','shared_work');await choose(page,'planStatus','changed');
  await choose(page,'kidsResponse','mixed');await choose(page,'adultsResponse','liked');
  await choose(page,'signalContext','late_schedule');await choose(page,'leftovers','saved');await choose(page,'wasteUnit','portion');
  for(const [name,value] of Object.entries({actualMinutes:'15',effort:'2',stressBefore:'5',stressAfter:'2',actualMeal:'Rotis and yogurt',whoCooked:'Arjun',changeReason:'Late pickup',wasteQuantity:'0',actualCost:'0',currency:'USD',occurredOn:'2026-10-05'}))await editor(page).locator(`[name=${name}]`).fill(value);
  await save(page);
  let report=(await records(page)).find(row=>row.note===note);
  expect(report.input_source).toBe('website');expect(report.occurred_on).toBe('2026-10-05');
  expect(report.signals).toEqual({goal:'shared_work',planStatus:'changed',actualMinutes:15,effort:2,stressBefore:5,stressAfter:2,actualMeal:'Rotis and yogurt',whoCooked:'Arjun',changeReason:'Late pickup',context:['late_schedule'],responses:[{audience:'kids',response:'mixed'},{audience:'adults',response:'liked'}],leftovers:'saved',wasteQuantity:0,wasteUnit:'portion',actualCost:0,currency:'USD'});
  await expect(page.locator('.feedback').filter({hasText:note})).toContainText('15 kitchen minutes reported');
  await page.reload();await navigateToView(page,'reviews');
  await expect(page.locator('.feedback').filter({hasText:note})).toContainText('Cost: 0 USD');
  expect((await history(page,'feedback_entries')).filter(row=>row.sourceId===report.id)).toHaveLength(1);
});

test('a quick household observation needs no outcome or invented metrics',async({page})=>{
  const note=`Guests this Friday ${Date.now()}`;
  await page.getByRole('button',{name:'What’s changed at home?',exact:true}).click();
  await editor(page).locator('[name=note]').fill(note);await save(page);
  const report=(await records(page)).find(row=>row.note===note);
  expect(report.feedback_type).toBe('context_update');expect(report.signals).toEqual({});expect(report.occurred_on).toBeNull();
  const response=await page.request.get('/api/what-worked');
  expect((await response.json()).items.some(row=>row.id===report.id)).toBe(false);
  await expect(page.locator('.feedback').filter({hasText:note})).toBeVisible();
});

test('an acknowledgement failure retains the draft; retry saves the same report and one event',async({page})=>{
  const note=`Retry signal ${Date.now()}`;
  await page.getByRole('button',{name:'Review this week',exact:true}).click();
  await editor(page).locator('[name=note]').fill(note);await editor(page).getByText('Add details, if useful',{exact:true}).click();
  await editor(page).locator('[name=actualMinutes]').fill('0');
  await page.route('**/api/feedback',async route=>{await route.fetch();await route.fulfill({status:503,contentType:'application/json',body:JSON.stringify({detail:'Acknowledgement unavailable; retry this report.'})});});
  await editor(page).locator('#dialog-save').click();await expect(editor(page).locator('#dialog-error')).toContainText('Acknowledgement unavailable');
  await expect(editor(page).locator('[name=note]')).toHaveValue(note);await expect(editor(page).locator('[name=actualMinutes]')).toHaveValue('0');
  await page.unroute('**/api/feedback');await save(page);
  const reports=(await records(page)).filter(row=>row.note===note);expect(reports).toHaveLength(1);
  expect((await history(page,'feedback_entries')).filter(row=>row.sourceId===reports[0].id)).toHaveLength(1);
});

test('a rejected metric keeps the note; correction saves reported fields and safe text at 320px',async({page})=>{
  await page.setViewportSize({width:320,height:740});
  const note=`<img src=x onerror="window.signalInjection=true"> Report ${Date.now()}`;
  await page.getByRole('button',{name:'Review this week',exact:true}).click();await editor(page).locator('[name=note]').fill(note);
  await editor(page).getByText('Add details, if useful',{exact:true}).click();
  await choose(page,'signalGoal','other');await editor(page).locator('#dialog-save').click();
  await expect(editor(page).locator('#dialog-error')).toContainText('Describe the other household goal');
  expect((await records(page)).some(row=>row.note===note)).toBe(false);await expect(editor(page).locator('[name=note]')).toHaveValue(note);
  await editor(page).locator('[name=goalNote]').fill('Less washing up');await save(page);
  await expect(page.locator('.feedback').filter({hasText:note})).toContainText('Less washing up');
  expect(await page.evaluate(()=>window.signalInjection)).toBeUndefined();
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
});

test('meal reports link to the planned food, and subsequent plan edits preserve the original intention',async({page})=>{
  const eid=crypto.randomUUID(), week='2049-02-01'; // Monday, isolated from existing examples.
  const created=await page.request.put('/api/meal-plan',{data:{weekStart:week,entries:[{id:eid,date:week,slot:'dinner',meal:'Original planned dinner',components:[]}]}});expect(created.ok(),await created.text()).toBeTruthy();
  await page.goto(`/app?view=plan&week=${week}`);await expect(page.locator('#week-picker')).toHaveValue(week);
  await navigateToView(page,'reviews');await page.getByRole('button',{name:'Review a meal',exact:true}).click();
  await choose(page,'mealPlanEntryId',eid);const note=`Linked actual dinner ${Date.now()}`;await editor(page).locator('[name=note]').fill(note);await save(page);
  const report=(await records(page)).find(row=>row.note===note);expect(report.plan_snapshot.meal).toBe('Original planned dinner');expect(report.occurrence.meal_plan_entry_id).toBe(eid);
  const edited=await page.request.patch('/api/meal-plan/items',{data:{weekStart:week,kind:'meal',item:{...report.plan_snapshot,meal:'Revised dinner'}}});expect(edited.ok(),await edited.text()).toBeTruthy();
  expect((await records(page)).find(row=>row.id===report.id).plan_snapshot.meal).toBe('Original planned dinner');
  const changes=await history(page,'meal_plan_entries');expect(changes.some(row=>row.sourceId===eid&&row.before?.meal==='Original planned dinner'&&row.after?.meal==='Revised dinner')).toBe(true);
});
