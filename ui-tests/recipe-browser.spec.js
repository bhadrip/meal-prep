const {test:base,expect}=require('@playwright/test');
const test=base.extend({
  dishes:async({request},use)=>{
    const suffix=Date.now(),dishes=[];
    for(const data of [
      {title:'Tofu bhurji',cuisines:['north indian'],eating_goals:['protein rich'],meal_types:['dinner','lunch'],diets:['vegan'],totalMinutes:20},
      {title:'Paneer bhurji',cuisines:['north indian'],eating_goals:['protein rich'],meal_types:['dinner'],diets:['vegetarian'],totalMinutes:35},
      {title:'Rasam',cuisines:['south indian'],eating_goals:['comfort food'],meal_types:['dinner'],diets:['vegan'],totalMinutes:15},
      {title:'Pepper rasam',cuisines:['south indian'],eating_goals:['comfort food'],meal_types:['dinner'],diets:['vegan'],totalMinutes:20},
    ]){
      const response=await request.put('/api/recipes',{data:{...data,title:`${data.title} ${suffix}`}});
      expect(response.ok()).toBe(true);dishes.push(await response.json());
    }
    await request.put('/api/recipe-relationships',{data:{sourceRecipeId:dishes[3].id,targetRecipeId:dishes[2].id,type:'variant_of'}});
    await use(dishes);
    for(const dish of dishes)await request.delete(`/api/recipes/${dish.id}`);
  }
});
const browse=page=>page.locator('#recipe-browser');
async function select(page,tab,filter){
  await browse(page).getByRole('group',{name:'Browse recipes by'}).getByRole('button',{name:tab,exact:true}).click();
  await browse(page).locator('.rb-options').getByRole('button',{name:new RegExp(`^${filter} `)}).click();
}

test('combine browse filters, preserve them through detail and reload, and follow variations in the graph',async({page,dishes,request})=>{
  const [tofu,paneer,rasam,pepper]=dishes;
  await page.goto('/app?view=recipes');
  await page.locator('#recipe-search').fill(String(rasam.title.split(' ').at(-1)));
  const goals=browse(page).getByRole('group',{name:'Browse recipes by'}).getByRole('button',{name:'Eating goals',exact:true});
  await goals.press('Enter');
  await expect(goals).toBeFocused();
  const protein=browse(page).locator('.rb-options').getByRole('button',{name:/^protein rich /});
  await protein.press('Enter');
  await expect(protein).toHaveAttribute('aria-pressed','true');
  await expect(protein).toBeFocused();
  await select(page,'Meal','dinner');
  await expect(browse(page).locator('.recipe-card')).toHaveCount(2);
  await expect(browse(page)).toContainText(tofu.title);await expect(browse(page)).toContainText(paneer.title);
  await select(page,'Diet','vegan');
  await expect(browse(page).locator('.recipe-card')).toHaveCount(1);
  await browse(page).getByRole('button',{name:`Open ${tofu.title}`,exact:true}).click();
  await expect(page.locator('.hero h2')).toHaveText(tofu.title);
  await page.getByRole('button',{name:'← All recipes',exact:true}).click();
  await expect(browse(page).locator('.recipe-card')).toHaveCount(1);
  await page.reload();
  await expect(browse(page).locator('.recipe-card')).toHaveCount(1);
  await expect(browse(page)).toContainText(tofu.title);
  await browse(page).getByRole('button',{name:'Remove vegan filter',exact:true}).click();
  await page.getByRole('combobox',{name:'Maximum cooking time'}).selectOption('20');
  await expect(browse(page).locator('.recipe-card')).toHaveCount(1);
  await browse(page).getByRole('button',{name:'Clear all',exact:true}).click();
  await page.locator('#recipe-search').fill(String(rasam.title.split(' ').at(-1)));
  await select(page,'Cuisine','south indian');
  await expect(browse(page).locator('.recipe-card')).toHaveCount(2);
  await expect(browse(page).locator('.recipe-card').filter({hasText:rasam.title}).filter({hasNotText:pepper.title})).toContainText('1 other way to make it');
  await browse(page).getByRole('button',{name:`Explore ${rasam.title}`,exact:true}).click();
  const graph=page.locator('#recipe-connections');
  await expect(graph.locator('.rg-node[aria-pressed="true"]')).toHaveAttribute('data-graph-node',`recipe:${rasam.id}`);
  await graph.getByRole('button',{name:`${pepper.title}, Recipe`,exact:true}).click();
  await expect(graph.locator('.rg-node[aria-pressed="true"]')).toHaveAttribute('data-graph-node',`recipe:${pepper.id}`);
  await graph.getByRole('button',{name:'Add detail',exact:true}).click();
  await graph.getByRole('combobox',{name:'Detail type',exact:true}).selectOption('goal');
  await graph.getByLabel('Eating goal',{exact:true}).fill('quick dinner');
  await graph.getByRole('button',{name:'Save detail',exact:true}).click();
  await expect(graph.getByRole('status')).toHaveText('Recipe detail saved.');
  await page.getByRole('button',{name:'Explore these results',exact:true}).click();
  await select(page,'Eating goals','quick dinner');
  await expect(browse(page).locator('.recipe-card')).toHaveCount(1);
  await expect(browse(page)).toContainText(pepper.title);
  const result=await(await request.get('/api/recipe-library?goal=quick%20dinner')).json();
  expect(result.items.map(r=>r.id)).toEqual([pepper.id]);
});

test('edit recipe categories, recover a failed filter request, and browse on a small screen',async({page,dishes,request})=>{
  await page.setViewportSize({width:390,height:844});
  const dish=dishes[0];
  await page.goto(`/app?view=recipes&recipe=${dish.id}`);
  await page.getByRole('button',{name:'Edit recipe',exact:true}).click();
  await page.locator('[name="meal_types"]').fill('breakfast');
  await page.locator('#dialog-save').click();
  await expect(page.locator('#editor-dialog')).not.toBeVisible();
  expect((await(await request.get(`/api/recipes/${dish.id}`)).json()).meal_types).toEqual(['breakfast']);
  await page.getByRole('button',{name:'← All recipes',exact:true}).click();
  await page.locator('#recipe-search').fill(dish.title);
  await expect(browse(page).locator('.recipe-card')).toHaveCount(1);
  await page.route('**/api/recipe-library?**',route=>route.fulfill({status:503,contentType:'application/json',body:JSON.stringify({detail:'Storage temporarily unavailable'})}),{times:1});
  await select(page,'Meal','breakfast');
  await expect(browse(page).getByRole('alert')).toContainText('temporarily unavailable');
  await expect(browse(page).locator('.rb-options [aria-pressed="true"]')).toContainText('breakfast');
  await browse(page).getByRole('button',{name:'Retry',exact:true}).click();
  await expect(browse(page).getByRole('status')).toHaveText(/1 recipe/);
  await expect(browse(page).getByRole('alert')).toBeEmpty();
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
  await browse(page).getByRole('button',{name:`Open ${dish.title}`,exact:true}).click();
  await expect(page.locator('.hero h2')).toHaveText(dish.title);
});

test('show more retrieves the remaining recipes without duplicates and search covers the whole library',async({page,request})=>{
  const prefix=`Pagination ${Date.now()}`,ids=[];
  try{
    for(let i=0;i<28;i++)ids.push((await(await request.put('/api/recipes',{data:{title:`${prefix} ${String(i).padStart(2,'0')}`,tags:[prefix.toLowerCase()]}})).json()).id);
    await page.goto(`/app?view=recipes&query=${encodeURIComponent(prefix)}`);
    await expect(browse(page).locator('.recipe-card')).toHaveCount(25);
    await browse(page).getByRole('button',{name:'Explore these results',exact:true}).click();
    await browse(page).getByRole('button',{name:'Show more recipes',exact:true}).click();
    await expect(browse(page).locator('.recipe-card')).toHaveCount(28);
    await browse(page).getByRole('button',{name:`Explore ${prefix} 27`,exact:true}).click();
    await expect(browse(page).locator('.rg-node[aria-pressed="true"]')).toHaveAttribute('data-graph-node',`recipe:${ids[27]}`);
    await browse(page).getByRole('button',{name:'Explore these results',exact:true}).click();
    const visible=await browse(page).locator('[data-rb-open]').evaluateAll(nodes=>nodes.map(n=>n.dataset.rbOpen));
    expect(new Set(visible).size).toBe(28);
    await page.locator('#recipe-search').fill(`${prefix} 27`);
    await expect(browse(page).locator('.recipe-card')).toHaveCount(1);
    await browse(page).getByRole('button',{name:`Open ${prefix} 27`,exact:true}).click();
    await expect(page.locator('.hero h2')).toHaveText(`${prefix} 27`);
  }finally{for(const id of ids)await request.delete(`/api/recipes/${id}`);}
});

test('explore stays inside filtered results, labels related recipes, refreshes with search, and recovers graph errors',async({page,dishes,request})=>{
  const [tofu,paneer,rasam,pepper]=dishes;
  await page.goto(`/app?view=recipes&query=${encodeURIComponent(rasam.title)}&meal=dinner&max_minutes=20`);
  const toggle=browse(page).getByRole('button',{name:'Explore these results',exact:true}),graph=browse(page).locator('#recipe-connections');
  await expect(browse(page).locator('.recipe-card')).toHaveCount(2);
  await toggle.click();
  await expect(toggle).toHaveAttribute('aria-expanded','true');
  await expect(browse(page).locator('.recipe-card')).toHaveCount(2);
  await expect(page.getByRole('searchbox',{name:'Search recipes',exact:true})).toHaveValue(rasam.title);
  await expect(graph.getByRole('combobox',{name:'Start from a recipe',exact:true})).toHaveCount(0);
  await page.getByRole('combobox',{name:'Maximum cooking time'}).selectOption('20');
  // A saved edit narrows the card results while retaining its direct variation as context.
  await request.put('/api/recipes',{data:{...pepper,totalMinutes:30}});
  await page.reload();
  await expect(browse(page).locator('.recipe-card')).toHaveCount(1);
  await expect(toggle).toHaveAttribute('aria-expanded','false');
  await toggle.click();
  await expect(graph.getByRole('button',{name:`${pepper.title}, Related recipe`,exact:true})).toBeVisible();
  await expect(graph.getByRole('button',{name:`${rasam.title}, Recipe`,exact:true})).toBeVisible();
  await graph.getByRole('button',{name:'Add detail',exact:true}).click();
  await graph.getByRole('combobox',{name:'To recipe',exact:true}).selectOption(tofu.id);
  await graph.getByRole('button',{name:'Save detail',exact:true}).click();
  await expect(graph.getByRole('button',{name:`${tofu.title}, Related recipe`,exact:true})).toBeVisible();
  await expect(browse(page).locator('.recipe-card')).toHaveCount(1);
  await graph.getByRole('button',{name:'Open recipe',exact:true}).click();
  await page.getByRole('button',{name:'← All recipes',exact:true}).click();
  await expect(toggle).toHaveAttribute('aria-expanded','true');
  await expect(browse(page).locator('.recipe-card')).toHaveCount(1);
  await page.route('**/api/recipe-graph?**',route=>route.fulfill({status:503,contentType:'application/json',body:JSON.stringify({detail:'Graph temporarily unavailable'})}),{times:1});
  await page.locator('#recipe-search').fill(paneer.title);
  await expect(browse(page).locator('.recipe-card')).toHaveCount(0); // 35 minutes is over the time limit
  await expect(toggle).not.toBeVisible();
  await page.getByRole('combobox',{name:'Maximum cooking time'}).selectOption('');
  await expect(browse(page).locator('.recipe-card')).toHaveCount(1);
  await expect(graph.getByRole('alert')).toContainText('Graph temporarily unavailable');
  await expect(page.locator('#recipe-search')).toHaveValue(paneer.title);
  await graph.getByRole('button',{name:'Retry connections',exact:true}).click();
  await expect(graph.locator('.rg-node[aria-pressed="true"]')).toHaveAttribute('data-graph-node',`recipe:${paneer.id}`);
  await expect(browse(page).locator('.recipe-card')).toHaveCount(1);
  await toggle.click();
  await expect(browse(page).getByRole('region',{name:'Explore search results',exact:true})).not.toBeVisible();
  await page.reload();
  await expect(toggle).toHaveAttribute('aria-expanded','false');
});

test('signed-in recipe links retain filters and start Explore collapsed on first load and reload',async({page,dishes})=>{
  const tofu=dishes[0],graphRequests=[];
  page.on('request',request=>{if(new URL(request.url()).pathname==='/api/recipe-graph')graphRequests.push(request.url());});
  await page.route('**/api/auth/config',route=>route.fulfill({json:{supabaseUrl:'https://example.supabase.co',supabaseAnonKey:'public-test-key',authRequired:true}}));
  await page.route('**/static/vendor/supabase.js',route=>route.fulfill({contentType:'application/javascript',body:`window.supabase={createClient:()=>({auth:{getSession:async()=>({data:{session:{access_token:'test-token',user:{email:'cook@example.com'}}},error:null})}})};`}));
  await page.route('**/api/app/bootstrap**',async route=>{
    const data=await(await route.fetch()).json();
    await route.fulfill({json:{...data,access:{role:'owner',members:[],invitations:[]},memberships:{households:[{id:'home-1',name:'Home',role:'owner'}],activeHouseholdId:'home-1'}}});
  });
  await page.goto(`/app?view=recipes&mode=explore&query=${encodeURIComponent(tofu.title)}&goal=protein+rich&meal=dinner&max_minutes=20`);
  for(let load=0;load<2;load++){
    await expect(page.locator('#account-label')).toHaveText('cook@example.com');
    await expect(browse(page).locator('.recipe-card')).toHaveCount(1);
    await expect(page.locator('#recipe-search')).toHaveValue(tofu.title);
    const toggle=browse(page).getByRole('button',{name:'Explore these results',exact:true});
    await expect(toggle).toHaveAttribute('aria-expanded','false');
    await expect(browse(page).getByRole('region',{name:'Explore search results',exact:true})).not.toBeVisible();
    expect(new URL(page.url()).searchParams.has('mode')).toBe(false);
    expect(graphRequests).toHaveLength(load);
    await toggle.click();
    await expect(browse(page).locator('.rg-node[aria-pressed="true"]')).toHaveAttribute('data-graph-node',`recipe:${tofu.id}`);
    await expect(toggle).toHaveAttribute('aria-expanded','true');
    await expect(browse(page).getByRole('button',{name:'Remove protein rich filter',exact:true})).toBeVisible();
    if(!load)await page.reload();
  }
});
