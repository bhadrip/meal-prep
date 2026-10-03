const { test: base, expect } = require('@playwright/test');
const test = base.extend({
  recipes: async ({ request }, use) => {
    const suffix = Date.now();
    const recipes = [];
    for (const title of ['Rasam', 'Pepper rasam', 'Sambar']) {
      const response = await request.put('/api/recipes', { data: { title: `${title} ${suffix}`, tags: [] } });
      expect(response.ok()).toBeTruthy(); recipes.push(await response.json());
    }
    await use(recipes);
    for (const recipe of recipes) await request.delete(`/api/recipes/${recipe.id}`);
  },
});
const graph = surface => surface.locator('#recipe-connections');
const focus = async (surface, recipe) => {
  await surface.getByRole('button', {name: `Explore ${recipe.title}`, exact: true}).click();
  await expect(graph(surface).locator('.rg-node[aria-pressed="true"]')).toHaveAttribute('data-graph-node', `recipe:${recipe.id}`);
};
async function add(surface, type, value) {
  await graph(surface).getByRole('button', { name: 'Add detail', exact: true }).click();
  await graph(surface).getByRole('combobox', { name: 'Detail type', exact: true }).selectOption(type);
  if (['tag','cuisine','goal','meal','diet'].includes(type)) await graph(surface).getByLabel({tag:'Tag',cuisine:'Cuisine',goal:'Eating goal',meal:'Meal',diet:'Diet'}[type], { exact: true }).fill(value);
  else await graph(surface).getByRole('combobox', { name: 'To recipe', exact: true }).selectOption(value);
  await graph(surface).getByRole('button', { name: 'Save detail', exact: true }).click();
}
async function apiEdges(request) { return (await (await request.get('/api/recipe-graph')).json()).edges; }

test('browse categories, add/edit/delete/undo connections, reject loops, and open recipes', async ({ page, request, recipes }) => {
  const [rasam, pepper, sambar] = recipes;
  await page.goto('/app?view=recipes');
  await page.getByRole('button', { name: 'Explore these results', exact: true }).click();
  await focus(page, rasam);
  await add(page, 'cuisine', 'South Indian');
  await expect(graph(page).getByRole('status')).toHaveText('Recipe detail saved.');
  await page.getByRole('button', { name: 'south indian, Cuisine', exact: true }).click();
  await expect(graph(page).locator('.rg-node[aria-pressed=\"true\"]')).toHaveAttribute('data-graph-node', 'cuisine:south indian');
  await page.getByRole('button', { name: `${rasam.title}, Recipe`, exact: true }).click();
  await expect(graph(page).locator('.rg-node[aria-pressed=\"true\"]')).toHaveAttribute('data-graph-node', `recipe:${rasam.id}`);
  await add(page, 'tag', 'protein rich');
  await expect.poll(async () => (await apiEdges(request)).some(e => e.sourceRecipeId === rasam.id && e.label === 'protein rich')).toBe(true);
  await graph(page).locator('.rg-edge-button').filter({ hasText: 'Tag' }).click();
  await graph(page).getByLabel('Tag', { exact: true }).fill('weeknight favorite');
  await graph(page).getByRole('button', { name: 'Save detail' }).click();
  await expect(graph(page).getByRole('button', { name: 'weeknight favorite, Tag' })).toBeVisible();
  await graph(page).getByRole('button', { name: 'Undo', exact: true }).click();
  await expect(graph(page).getByRole('button', { name: 'protein rich, Tag' })).toBeVisible();
  await graph(page).locator('.rg-edge-button').filter({ hasText: 'Tag' }).click();
  await graph(page).getByRole('button', { name: 'Remove detail' }).click();
  await expect.poll(async () => (await apiEdges(request)).some(e => e.sourceRecipeId === rasam.id && e.label === 'protein rich')).toBe(false);
  await graph(page).getByRole('button', { name: 'Undo', exact: true }).click();
  await expect(graph(page).getByRole('button', { name: 'protein rich, Tag' })).toBeVisible();
  await focus(page, pepper);
  await add(page, 'variant_of', rasam.id);
  await expect(graph(page).getByRole('status')).toHaveText('Recipe detail saved.');
  await focus(page, rasam);
  await expect(graph(page).locator('.rg-relationships')).toContainText('Other ways to make it');
  await add(page, 'variant_of', pepper.id);
  await expect(graph(page).getByRole('alert')).toContainText('loop');
  await expect.poll(async () => (await apiEdges(request)).filter(e => e.type === 'variant_of' && recipes.some(r => r.id === e.sourceRecipeId)).length).toBe(1);
  await graph(page).getByRole('button', { name: 'Cancel', exact: true }).click();
  await add(page, 'pairs_with', pepper.id);
  await expect(graph(page).getByRole('status')).toHaveText('Recipe detail saved.');
  await add(page, 'pairs_with', sambar.id);
  await expect(graph(page).getByRole('status')).toHaveText('Recipe detail saved.');
  await page.reload();
  await focus(page, rasam);
  await expect(graph(page).getByRole('button', { name: `${sambar.title}, Recipe`, exact: true })).toBeVisible();
  await graph(page).getByRole('button', { name: 'Open recipe', exact: true }).click();
  await expect(page.locator('.hero h2')).toHaveText(rasam.title);
  await page.getByRole('button', { name: '← All recipes', exact: true }).click();
  await expect(graph(page).locator('.rg-node[aria-pressed=\"true\"]')).toHaveAttribute('data-graph-node', `recipe:${rasam.id}`);
  await page.getByRole('button', { name: 'Explore these results', exact: true }).click();
  await page.getByRole('button', { name: 'Tags', exact: true }).click();
  await page.getByRole('searchbox', {name: 'Find a recipe tag'}).fill('protein rich');
  await page.getByRole('group', {name: 'Recipe tag filters'}).getByRole('button', { name: /protein rich/ }).click();
  await expect(page.locator('#recipe-results')).toContainText(rasam.title);
  expect((await (await request.get(`/api/recipes/${rasam.id}`)).json()).tags).toContain('protein rich');
});

test('mobile keyboard navigation and failed writes preserve the relationship draft', async ({ page, request, recipes }) => {
  for (const type of ['variant_of', 'pairs_with']) expect((await request.put('/api/recipe-relationships', { data: { type, sourceRecipeId: recipes[0].id, targetRecipeId: recipes[1].id } })).ok()).toBeTruthy();
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/app?view=recipes&mode=explore');
  await focus(page, recipes[0]);
  await add(page, 'tag', 'quick');
  await expect(graph(page).getByRole('status')).toHaveText('Recipe detail saved.');
  const node = graph(page).getByRole('button', { name: 'quick, Tag', exact: true });
  await node.focus(); await page.keyboard.press('Enter');
  await expect(graph(page).locator('.rg-node[aria-pressed=\"true\"]')).toHaveAttribute('data-graph-node', 'tag:quick');
  await graph(page).getByRole('button', { name: '← Back', exact: true }).click();
  await add(page, 'tag', 'quick');
  await expect(graph(page).getByRole('alert')).toContainText('already exists');
  await expect(graph(page).getByLabel('Tag', { exact: true })).toHaveValue('quick');
  await graph(page).getByRole('button', { name: 'Cancel', exact: true }).click();
  await page.route('**/api/recipe-relationships', route => route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ detail: 'Storage is temporarily unavailable' }) }));
  await add(page, 'cuisine', 'south indian');
  await expect(graph(page).getByRole('alert')).toContainText('temporarily unavailable');
  await expect(graph(page).getByLabel('Cuisine', { exact: true })).toHaveValue('south indian');
  expect((await apiEdges(request)).some(e => e.sourceRecipeId === recipes[0].id && e.type === 'cuisine')).toBe(false);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  const buttons = await graph(page).locator('.rg-edge-button').evaluateAll(nodes => nodes.map(n => { const b=n.getBoundingClientRect(); return {x:b.x,y:b.y,width:b.width,height:b.height}; }));
  for (let i=0;i<buttons.length;i++) for (let j=i+1;j<buttons.length;j++) {
    const a=buttons[i], b=buttons[j];
    expect(a.x+a.width<=b.x || b.x+b.width<=a.x || a.y+a.height<=b.y || b.y+b.height<=a.y).toBe(true);
  }
  const bounds = await graph(page).locator('.rg-canvas').boundingBox();
  for (const box of await graph(page).locator('.rg-node').evaluateAll(nodes => nodes.map(n => ({ left: n.getBoundingClientRect().left, right: n.getBoundingClientRect().right })))) {
    expect(box.left).toBeGreaterThanOrEqual(bounds.x); expect(box.right).toBeLessThanOrEqual(bounds.x + bounds.width);
  }
});

test('sandboxed MCP resource edits and restores real relationships through host tools', async ({ page, request, recipes }) => {
  const response = await request.post('/mcp', { headers: { Accept: 'application/json, text/event-stream' }, data: {
    jsonrpc: '2.0', id: 1, method: 'resources/read', params: { uri: 'ui://meal-prep/recipe-library-v1.html' },
  } });
  const html = (await response.json()).result.contents[0].text;
  // Exercise the actual self-contained resource in a sandbox without form permission.
  await page.route('**/graph-test-host', route => route.fulfill({ contentType: 'text/html; charset=utf-8', body: `<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><style>@media(pointer:coarse){iframe{height:calc(100dvh - 16px)!important}}</style></head><body><iframe sandbox="allow-scripts allow-same-origin" style="width:100%;max-width:100%;box-sizing:border-box;height:1100px;border:0"></iframe><script>
    window.calls=[]; window.ready=false;
    window.addEventListener('message', async event => {
      const m=event.data; if(!m.method)return;
      if(m.method==='ui/notifications/initialized'){window.ready=true;return;}
      if(m.method==='ui/initialize'){event.source.postMessage({jsonrpc:'2.0',id:m.id,result:{}},'*');return;}
      if(m.method!=='tools/call')return; window.calls.push(m.params);
      const a=m.params.arguments,n=m.params.name;
      const params=new URLSearchParams({query:a.query||'',limit:a.limit||25,offset:a.offset||0});for(const [key,values] of Object.entries(a.filters||{}))values.forEach(value=>params.append(key,value));if(a.max_minutes)params.set('max_minutes',a.max_minutes);
      const routes={browse_recipe_library:['/api/recipe-library?'+params,'GET'],get_recipe_graph:['/api/recipe-graph?'+params,'GET'],save_recipe_relationship:['/api/recipe-relationships','PUT',a.relationship],delete_recipe_relationship:['/api/recipe-relationships/'+encodeURIComponent(a.relationship_id),'DELETE'],get_recipe:['/api/recipes/'+a.recipe_id,'GET'],list_recipe_shares:['/api/recipe-shares','GET'],render_recipe_library:['/api/recipe-library?limit=25','GET']};
      const [url,method,body]=routes[n];const r=await fetch(url,{method,headers:{'Content-Type':'application/json'},...(body?{body:JSON.stringify(body)}:{})});let data=await r.json();
      if(n==='render_recipe_library')data={kind:'recipe_library',...data,recipes:data.items};
      event.source.postMessage({jsonrpc:'2.0',id:m.id,result:r.ok?{structuredContent:data}:{isError:true,content:[{type:'text',text:data.detail}]}},'*');
    });
    document.querySelector('iframe').srcdoc=${JSON.stringify(html).replaceAll('</script>', '<\\/script>')};
  </script></body></html>` }));
  await page.goto('/graph-test-host');
  await expect.poll(() => page.evaluate(() => window.ready)).toBe(true);
  const data = (await (await request.get('/api/recipe-graph')).json());
  await page.evaluate(data => document.querySelector('iframe').contentWindow.postMessage({ jsonrpc: '2.0', method: 'ui/notifications/tool-result', params: { structuredContent: { kind: 'recipe_graph', graph: data } } }, '*'), data);
  const frame = page.frameLocator('iframe');
  await focus(frame, recipes[0]);
  await add(frame, 'cuisine', 'south indian');
  await expect(graph(frame).getByRole('status')).toHaveText('Recipe detail saved.');
  await add(frame, 'cuisine', 'south indian');
  await expect(graph(frame).getByRole('alert')).toContainText('already exists');
  await graph(frame).getByRole('button', { name: 'Cancel', exact: true }).click();
  await graph(frame).getByRole('button', { name: 'Open recipe', exact: true }).click();
  await expect(frame.locator('.recipe-detail').getByRole('heading', { name: recipes[0].title, exact: true })).toBeVisible();
  await frame.getByRole('button', { name: '← All recipes', exact: true }).click();
  await graph(frame).locator('.rg-edge-button').filter({ hasText: 'Cuisine' }).click();
  await graph(frame).getByRole('button', { name: 'Remove detail' }).click();
  await expect(graph(frame).getByRole('status')).toHaveText('Recipe detail removed.');
  await graph(frame).getByRole('button', { name: 'Undo', exact: true }).click();
  await expect(graph(frame).getByRole('button', { name: 'south indian, Cuisine', exact: true })).toBeVisible();
  expect((await apiEdges(request)).some(e => e.sourceRecipeId === recipes[0].id && e.label === 'south indian')).toBe(true);
  await add(frame, 'goal', 'protein rich');
  await expect(graph(frame).getByRole('status')).toHaveText('Recipe detail saved.');
  await add(frame, 'meal', 'dinner');
  await expect(graph(frame).getByRole('status')).toHaveText('Recipe detail saved.');
  await frame.getByRole('button', { name: 'Explore these results', exact: true }).click();
  await expect(frame.getByRole('button', { name: 'Explore these results', exact: true })).toHaveAttribute('aria-expanded','false');
  await frame.locator('#recipe-browser [data-rb-tab="goal"]').click();
  await frame.locator('.rb-options').getByRole('button', {name: /^protein rich /}).click();
  await frame.locator('#recipe-browser [data-rb-tab="meal"]').click();
  await frame.locator('.rb-options').getByRole('button', {name: /^dinner /}).click();
  await expect(frame.locator('#recipe-results .recipe-card')).toHaveCount(1);
  await expect(frame.locator('#recipe-results')).toContainText(recipes[0].title);
  await frame.getByRole('button', {name: `Open ${recipes[0].title}`, exact: true}).click();
  await expect(frame.locator('.recipe-detail').getByRole('heading', {name: recipes[0].title, exact: true})).toBeVisible();
  await frame.getByRole('button', {name: '← All recipes', exact: true}).click();
  await expect(frame.locator('#recipe-results .recipe-card')).toHaveCount(1);

  await frame.getByRole('button', { name: 'Explore these results', exact: true }).click();
  await expect(graph(frame).locator('.rg-node[aria-pressed=\"true\"]')).toHaveAttribute('data-graph-node', `recipe:${recipes[0].id}`);
  expect(await page.evaluate(() => window.calls.some(c => c.name === 'save_recipe_relationship'))).toBe(true);
});

test.describe('touch graph',()=>{
  test.use({viewport:{width:390,height:844},hasTouch:true,isMobile:true});
  test('parallel serving and variation edges have separate touch targets and open the correct editor',async({page,request,recipes})=>{
    for(const type of ['variant_of','pairs_with'])expect((await request.put('/api/recipe-relationships',{data:{type,sourceRecipeId:recipes[0].id,targetRecipeId:recipes[1].id}})).ok()).toBe(true);
    await page.goto('/app?view=recipes&mode=explore');
    await focus(page,recipes[0]);
    const edges=graph(page).locator('.rg-edge-button');
    await expect(edges).toHaveCount(2);
    const [a,b]=await edges.evaluateAll(nodes=>nodes.map(n=>{const r=n.getBoundingClientRect();return{x:r.x,y:r.y,width:r.width,height:r.height};}));
    expect(a.height).toBeGreaterThanOrEqual(44);expect(b.height).toBeGreaterThanOrEqual(44);
    expect(a.x+a.width<=b.x||b.x+b.width<=a.x||a.y+a.height<=b.y||b.y+b.height<=a.y).toBe(true);
    await edges.filter({hasText:'Variation'}).click();
    await expect(graph(page).getByRole('combobox',{name:'Detail type',exact:true})).toHaveValue('variant_of');
    await graph(page).getByRole('button',{name:'Cancel',exact:true}).click();
    await graph(page).locator('.rg-edge-button').filter({hasText:'Serve with'}).click();
    await expect(graph(page).getByRole('combobox',{name:'Detail type',exact:true})).toHaveValue('pairs_with');
  });
});

test('main search chooses a graph starting recipe beyond the first card page with keyboard and empty-result recovery',async({page,request,recipes})=>{
  const fillers=[];
  try{
    for(let i=0;i<26;i++)fillers.push((await(await request.put('/api/recipes',{data:{title:`A search filler ${Date.now()} ${i}`}})).json()).id);
    await page.goto('/app?view=recipes');
    const search=page.getByRole('searchbox',{name:'Search recipes',exact:true});
    await search.fill(recipes[1].title.toUpperCase());
    await expect(page.locator('#recipe-results .recipe-card')).toHaveCount(1);
    await page.getByRole('button',{name:`Explore ${recipes[1].title}`,exact:true}).press('Enter');
    const selected=graph(page).locator('.rg-node[aria-pressed="true"]');
    await expect(selected).toHaveAttribute('data-graph-node',`recipe:${recipes[1].id}`);
    await expect(selected).toBeFocused();
    await expect(graph(page).getByRole('combobox',{name:'Start from a recipe',exact:true})).toHaveCount(0);
    await graph(page).getByRole('button',{name:'Open recipe',exact:true}).click();
    await expect(page.locator('.hero h2')).toHaveText(recipes[1].title);
    await page.getByRole('button',{name:'← All recipes',exact:true}).click();
    await search.fill('no such saved recipe');
    await expect(page.locator('#recipe-results .recipe-card')).toHaveCount(0);
    await expect(page.getByRole('button',{name:'Explore these results',exact:true})).not.toBeVisible();
    await search.fill(recipes[0].title);
    await expect(page.getByRole('button',{name:`Explore ${recipes[0].title}`,exact:true})).toBeVisible();
    await focus(page,recipes[0]);
  }finally{for(const id of fillers)await request.delete(`/api/recipes/${id}`);}
});
