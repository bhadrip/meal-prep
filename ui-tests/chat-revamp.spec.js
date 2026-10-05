const {test,expect}=require('@playwright/test');
const {openConversationSettings}=require('./navigation');
async function room(page,name){const r=await page.request.post('/api/circles',{data:{name}});expect(r.ok()).toBe(true);return r.json();}
async function messageAction(post,name){await expect(post.locator('.circle-send-state')).toHaveCount(0);await post.getByLabel('Message actions',{exact:true}).click();await post.getByRole('button',{name,exact:true}).click();}
async function send(page,text){const field=page.locator('#circle-message');await field.fill(text);await field.press('Enter');await expect(field).toHaveValue('');await expect(page.locator('.circle-send-state')).toHaveCount(0);}

test('signed-in mobile household header never overlaps conversation controls',async({page},info)=>{
  await page.route('**/api/auth/config',route=>route.fulfill({json:{supabaseUrl:'https://example.supabase.co',supabaseAnonKey:'test-key',authRequired:true}}));
  await page.route('**/static/vendor/supabase.js',route=>route.fulfill({contentType:'application/javascript',body:`window.supabase={createClient:()=>({auth:{getSession:async()=>({data:{session:{access_token:'test-token',user:{id:'demo',email:'bh@example.test'}}}}),onAuthStateChange:()=>({data:{subscription:{unsubscribe(){}}}})}})};`}));
  await page.route('**/api/app/bootstrap?*',async route=>{
    const response=await route.fetch();const data=await response.json();
    data.memberships={activeHouseholdId:'mobile-home',households:[{id:'mobile-home',name:'My household with a long name',role:'owner'}]};data.access={role:'owner'};
    await route.fulfill({json:data});
  });
  const r=await room(page,'redmond');await page.setViewportSize({width:390,height:750});await page.goto(`/app?view=circles&circle=${r.id}`);
  const picker=page.locator('#household-picker .choice-trigger');await expect(picker).toContainText('My household');
  for(const size of [{width:390,height:750},{width:320,height:568},{width:390,height:360},{width:740,height:360}]){
    await page.setViewportSize(size);
    const top=await page.locator('.topbar').boundingBox(),head=await page.locator('.circle-pane-head').boundingBox(),choice=await picker.boundingBox();
    expect(choice.y+choice.height).toBeLessThanOrEqual(top.y+top.height+1);expect(top.y+top.height).toBeLessThanOrEqual(head.y+1);
    expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
    for(const target of [picker,page.getByRole('button',{name:'Notifications',exact:true}),page.getByRole('button',{name:'Refresh data',exact:true}),page.getByRole('button',{name:'Account settings',exact:true}),page.getByRole('button',{name:'Search messages',exact:true}),page.getByLabel('Conversation settings',{exact:true}),page.getByRole('button',{name:'Send message',exact:true})]){
      await expect(target).toBeInViewport();expect(await target.evaluate(el=>{const b=el.getBoundingClientRect(),hit=document.elementFromPoint(b.x+b.width/2,b.y+b.height/2);return el===hit||el.contains(hit);})).toBe(true);
    }
  }
  await page.setViewportSize({width:390,height:750});await picker.click();await expect(page.getByRole('listbox')).toBeVisible();await page.keyboard.press('Escape');
  await page.getByRole('button',{name:'Search messages',exact:true}).click();await expect(page.getByRole('searchbox',{name:'Search messages',exact:true})).toBeVisible();await page.getByRole('button',{name:'Search messages',exact:true}).click();
  await send(page,'Aligned mobile message');await page.reload();await expect(page.locator('.circle-message-body')).toContainText('Aligned mobile message');await page.screenshot({path:info.outputPath('signed-in-mobile-chat.png')});
});

test('quotes, reactions, editing, filtered server history and mute persist after reload',async({page},info)=>{
  const r=await room(page,'Revamped dinner');await page.goto(`/app?view=circles&circle=${r.id}`);
  await send(page,'Sunday dinner');const first=page.locator('.circle-post').first();
  await messageAction(first,'👍');await expect(first.getByRole('button',{name:'👍 reaction'})).toHaveText('👍 1');
  await first.getByRole('button',{name:'👍 reaction'}).click();await expect(first.getByRole('button',{name:'👍 reaction'})).toHaveCount(0);
  await messageAction(first,'Quote reply');await expect(page.locator('.chat-reply-chip')).toContainText('Sunday dinner');
  await send(page,'Count me in');await expect(page.locator('.circle-post').last().locator('.chat-quote')).toContainText('Sunday dinner');
  await messageAction(first,'Edit message');await page.getByLabel('Edit message',{exact:true}).fill('Monday lunch');await page.getByRole('button',{name:'Save message'}).click();
  await expect(first.locator('.circle-message-body')).toHaveText('Monday lunch');await expect(first).toContainText('Edited');
  await page.getByRole('button',{name:'Search messages',exact:true}).click();
  await page.getByRole('searchbox',{name:'Search messages',exact:true}).fill('Monday');await page.getByLabel('From',{exact:true}).selectOption('demo');await page.getByLabel('Type',{exact:true}).selectOption('message');
  await page.getByRole('button',{name:'Search history'}).click();await expect(page.locator('.circle-post')).toHaveCount(1);await expect(page.locator('.circle-post')).toContainText('Monday lunch');
  await page.getByRole('button',{name:'Clear search'}).click();await expect(page.locator('.circle-post')).toHaveCount(2);
  await page.getByLabel('Conversation settings',{exact:true}).click();await page.getByRole('button',{name:'Mute conversation',exact:true}).click();
  expect((await(await page.request.get('/api/chats')).json()).items.find(c=>c.id===r.id).muted).toBe(true);
  await page.reload();await expect(page.locator('.circle-post')).toHaveCount(2);
  await page.getByLabel('Conversation settings',{exact:true}).click();await expect(page.getByRole('button',{name:'Unmute conversation',exact:true})).toBeVisible();
  await page.getByRole('button',{name:'Unmute conversation',exact:true}).click();
  await expect(page.getByLabel('Conversation settings',{exact:true})).toBeVisible();await page.screenshot({path:info.outputPath('chat-revamp.png')});
});

test('failed edits and invitation lookups keep the draft and show errors beside the action',async({page})=>{
  const r=await room(page,'Recoverable forms');await page.goto(`/app?view=circles&circle=${r.id}`);await send(page,'Original');
  await messageAction(page.locator('.circle-post'),'Edit message');await page.getByLabel('Edit message',{exact:true}).fill('Keep my edit');
  await page.route('**/api/chat-messages/*',route=>route.fulfill({status:503,json:{detail:'Editing unavailable'}}),{times:1});
  await page.getByRole('button',{name:'Save message'}).click();await expect(page.locator('.chat-inline-error')).toContainText('Editing unavailable');await expect(page.getByLabel('Edit message',{exact:true})).toHaveValue('Keep my edit');
  await page.getByRole('button',{name:'Save message'}).click();await expect(page.locator('.circle-message-body')).toHaveText('Keep my edit');
  await openConversationSettings(page);await page.getByLabel('Invite an existing friend').fill('missing@example.test');
  await page.route('**/api/circles/*/invitations',route=>route.fulfill({status:422,json:{detail:'Existing friend account was not found'}}),{times:1});
  await page.getByRole('button',{name:'Invite friend',exact:true}).click();await expect(page.locator('.circle-manage [role="alert"]')).toContainText('Existing friend account');await expect(page.getByLabel('Invite an existing friend')).toHaveValue('missing@example.test');
  await page.getByRole('button',{name:'Invite friend',exact:true}).click();await expect(page.locator('.circle-member')).toContainText('missing@example.test');
});

test('food picker recovers a failed search and removing an attachment sends only the text',async({page})=>{
  const r=await room(page,'Food picker');const recipe=await(await page.request.put('/api/recipes',{data:{title:'Picker noodles',ingredients:[],instructions:['Cook']}})).json();
  await page.goto(`/app?view=circles&circle=${r.id}`);await page.getByRole('button',{name:'+ Share',exact:true}).click();
  await page.route('**/api/recipe-library?*',route=>route.fulfill({status:503,json:{detail:'Offline'}}),{times:1});
  await page.getByRole('button',{name:'Share a recipe',exact:true}).click();await expect(page.locator('.chat-food-results')).toContainText('Could not load food');await page.getByRole('button',{name:'Retry food search'}).click();
  await page.getByRole('searchbox',{name:'Search your food library'}).fill('Picker noodles');await page.getByRole('button',{name:'Picker noodles Recipe',exact:true}).click();
  await expect(page.locator('.circle-food-review')).toContainText('Picker noodles');await page.getByRole('button',{name:'Cancel',exact:true}).click();expect((await(await page.request.get(`/api/chats/${r.id}/history`)).json()).items).toEqual([]);
  await page.locator('#circle-message').pressSequentially('@recipePicker');await page.locator('.mention-item').filter({hasText:recipe.title}).click();await page.getByRole('button',{name:'Remove attachment'}).click();await expect(page.locator('.circle-attachment')).toBeHidden();await expect(page.locator('#circle-message')).toHaveValue('');
  await send(page,'Just a message');const history=(await(await page.request.get(`/api/chats/${r.id}/history`)).json()).items;expect(history.map(p=>p.kind)).toEqual(['message']);
});

test('cursor history keeps the visible position and incoming messages wait behind Jump to latest',async({page})=>{
  const r=await room(page,'Long conversation');
  const posts=[];for(let i=0;i<55;i++){const response=await page.request.post(`/api/circles/${r.id}/messages`,{data:{body:`History ${i}`}});expect(response.ok()).toBe(true);posts.push(await response.json());}
  await page.goto(`/app?view=circles&circle=${r.id}`);await expect(page.locator('.circle-post')).toHaveCount(50);
  await page.getByRole('button',{name:'Search messages',exact:true}).click();await page.getByRole('searchbox',{name:'Search messages',exact:true}).fill('History 0');await page.getByRole('button',{name:'Search history'}).click();await expect(page.locator('.circle-post')).toHaveCount(1);await messageAction(page.locator('.circle-post'),'Quote reply');await expect(page.locator('.chat-reply-chip')).toContainText('History 0');await page.getByRole('button',{name:'Remove quoted reply'}).click();await page.getByRole('button',{name:'Clear search'}).click();
  const log=page.locator('.circle-timeline');await log.evaluate(el=>{el.scrollTop=0;});
  const anchor=page.locator('.circle-post').first();const anchorId=await anchor.getAttribute('data-id');const before=await anchor.boundingBox();
  await page.getByRole('button',{name:'Show earlier activity'}).click();await expect(page.locator('.circle-post')).toHaveCount(55);
  const after=await page.locator(`.circle-post[data-id="${anchorId}"]`).boundingBox();expect(Math.abs(after.y-before.y)).toBeLessThan(3);
  const top=await log.evaluate(el=>el.scrollTop);await page.request.post(`/api/circles/${r.id}/messages`,{data:{body:'Arrived while reading'}});await expect(page.locator('.circle-post')).toHaveCount(56);
  expect(Math.abs(await log.evaluate(el=>el.scrollTop)-top)).toBeLessThan(3);
  await page.getByRole('button',{name:'Jump to latest ↓',exact:true}).click();await expect(page.locator('.circle-post').last()).toBeInViewport();await expect(page.getByRole('button',{name:'Jump to latest ↓',exact:true})).toBeHidden();
  expect((await page.request.delete(`/api/circle-shares/${posts[0].id}`)).ok()).toBe(true);await expect(page.locator(`.circle-post[data-id="${posts[0].id}"]`)).toHaveCount(0);await expect(page.locator('.circle-post')).toHaveCount(55);
});

test('direct shares stay in one conversation and support plain messages and food sharing',async({page})=>{
  const recipeId='11111111-1111-1111-1111-111111111111',email=`direct-${Date.now()}@example.test`;
  const first=await(await page.request.post('/api/direct-shares',{data:{email,kind:'recipe',recipeId}})).json();
  await page.request.post('/api/direct-shares',{data:{email,kind:'recipe',recipeId}});
  await page.goto(`/app?view=circles&circle=${first.circleId}`);await expect(page.locator('.circle-post')).toHaveCount(2);
  await send(page,'Thanks for sharing');await expect(page.locator('.circle-post')).toHaveCount(3);
  await page.getByRole('button',{name:'+ Share',exact:true}).click();await page.getByRole('button',{name:'Share a recipe',exact:true}).click();await page.getByRole('button',{name:'Paneer rice bowls Recipe',exact:true}).click();await page.getByRole('button',{name:'Confirm share',exact:true}).click();await expect(page.locator('.circle-post')).toHaveCount(4);
  expect((await(await page.request.get('/api/chats')).json()).items.filter(c=>c.id===first.circleId)).toHaveLength(1);
  await openConversationSettings(page);await expect(page.getByRole('button',{name:'Invite friend',exact:true})).toHaveCount(0);
});

test('mobile chat keeps header, composer and panel actions reachable at keyboard height',async({page},info)=>{
  await page.setViewportSize({width:390,height:844});const r=await room(page,'Mobile dinner');await page.goto(`/app?view=circles&circle=${r.id}`);
  await page.locator('#circle-message').fill('A phone draft');await page.setViewportSize({width:390,height:360});
  await expect(page.getByRole('heading',{name:'Mobile dinner',exact:true})).toBeInViewport();await expect(page.getByRole('button',{name:'Send message',exact:true})).toBeInViewport();
  await openConversationSettings(page);await expect(page.getByRole('button',{name:'Back to conversation'})).toBeInViewport();await page.getByRole('button',{name:'Back to conversation'}).click();await expect(page.locator('#circle-message')).toHaveValue('A phone draft');
  await send(page,'Sent from my phone');await expect(page.locator('.circle-post').last()).toBeInViewport();expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
  await page.screenshot({path:info.outputPath('mobile-chat-keyboard.png')});
  await page.setViewportSize({width:390,height:844});await page.getByRole('button',{name:'‹ Chats',exact:true}).click();await expect(page.locator('.circle-room').filter({hasText:'Mobile dinner'})).toBeVisible();await page.locator(`.circle-room[data-id="${r.id}"]`).click();await expect(page.locator('.circle-post')).toContainText('Sent from my phone');
});

test('profile, week navigation and pantry filter reset preserve server data',async({page})=>{
  const originalName=(await(await page.request.get('/api/chat-profile')).json()).name;
  await page.goto('/app?view=settings');await page.getByLabel('Display name',{exact:true}).fill('Kitchen Alex');await page.getByRole('button',{name:'Save display name'}).click();await page.reload();await expect(page.getByLabel('Display name',{exact:true})).toHaveValue('Kitchen Alex');await page.request.put('/api/chat-profile',{data:{name:originalName}});
  await page.goto('/app?view=plan&week=2030-02-04');const before=await(await page.request.get('/api/meal-plan?week_start=2030-02-04')).json();await page.getByRole('button',{name:'Next week',exact:true}).click();await expect(page.locator('#week-picker')).toHaveValue('2030-02-11');await page.getByRole('button',{name:'Previous week',exact:true}).click();await expect(page.locator('#week-picker')).toHaveValue('2030-02-04');expect(await(await page.request.get('/api/meal-plan?week_start=2030-02-04')).json()).toEqual(before);
  await page.goto('/app?view=pantry');await page.locator('#pantry-search').fill('Impossible food search');await expect(page.locator('.pantry-table .table-row:not(.header)')).toHaveCount(0);await page.getByRole('button',{name:'Clear pantry filters'}).click();await expect(page.locator('#pantry-search')).toHaveValue('');await expect(page.locator('.pantry-table .table-row:not(.header)').first()).toBeVisible();
});


test('a second browser tab delivers changes and reconnect catches up without losing a draft',async({page})=>{
  const r=await room(page,'Two tab delivery');await page.goto(`/app?view=circles&circle=${r.id}`);
  const field=page.locator('#circle-message');await field.fill('A draft kept through reconnect');await field.evaluate(el=>{window.keptField=el;el.setSelectionRange(2,8);});
  const other=await page.context().newPage();await other.goto(`/app?view=circles&circle=${r.id}`);await send(other,'Sent from the other tab');await expect(page.locator('.circle-post')).toContainText('Sent from the other tab');
  await other.close();await page.context().setOffline(true);await expect(page.locator('.chat-connection')).toHaveText('Offline');
  expect((await page.request.post(`/api/circles/${r.id}/messages`,{data:{body:'Arrived while disconnected'}})).ok()).toBe(true);
  await page.context().setOffline(false);await expect(page.locator('.circle-post').last()).toContainText('Arrived while disconnected');await expect(field).toHaveValue('A draft kept through reconnect');
  expect(await field.evaluate(el=>[el===window.keptField,el.selectionStart,el.selectionEnd])).toEqual([true,2,8]);
});


test('a delayed profile load and rejected save preserve the typed display name',async({page})=>{
  const originalName=(await(await page.request.get('/api/chat-profile')).json()).name;
  let release;const held=new Promise(resolve=>{release=resolve;});
  await page.route('**/api/chat-profile',async route=>{if(route.request().method()==='GET'){await held;await route.continue();}else await route.continue();});
  await page.goto('/app?view=settings');await page.getByLabel('Display name',{exact:true}).fill('My retained name');const loaded=page.waitForResponse(response=>response.url().endsWith('/api/chat-profile')&&response.request().method()==='GET');release();await loaded;
  await expect(page.getByLabel('Display name',{exact:true})).toHaveValue('My retained name');
  await page.route('**/api/chat-profile',route=>route.request().method()==='PUT'?route.fulfill({status:503,json:{detail:'Profile temporarily unavailable'}}):route.continue(),{times:1});
  await page.getByRole('button',{name:'Save display name'}).click();await expect(page.locator('#chat-profile-form [role="alert"]')).toHaveText('Profile temporarily unavailable');await expect(page.getByLabel('Display name',{exact:true})).toHaveValue('My retained name');
  await page.getByRole('button',{name:'Save display name'}).click();await page.reload();await expect(page.getByLabel('Display name',{exact:true})).toHaveValue('My retained name');await page.request.put('/api/chat-profile',{data:{name:originalName}});
});
