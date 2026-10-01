const content = document.querySelector('#app-content');
const dialog = document.querySelector('#editor-dialog');
const form = document.querySelector('#editor-form');
const fields = document.querySelector('#dialog-fields');
const errorBox = document.querySelector('#dialog-error');
const toastBox = document.querySelector('#toast');
const shell = document.querySelector('.shell');
const sidebarToggle = document.querySelector('#sidebar-toggle');
const householdPicker = document.querySelector('#household-picker');
const householdSelect = document.querySelector('#household-select');

function setSidebarCollapsed(collapsed) {
  shell.classList.toggle('sidebar-collapsed', collapsed);
  const label = collapsed ? 'Expand sidebar' : 'Collapse sidebar';
  sidebarToggle.setAttribute('aria-label', label);
  sidebarToggle.setAttribute('aria-expanded', String(!collapsed));
  sidebarToggle.title = label;
  sidebarToggle.querySelector('span').textContent = collapsed ? '→' : '←';
}

try { setSidebarCollapsed(localStorage.getItem('meal-prep-sidebar-collapsed') === 'true'); }
catch { setSidebarCollapsed(false); }
sidebarToggle.addEventListener('click', () => {
  const collapsed = !shell.classList.contains('sidebar-collapsed');
  setSidebarCollapsed(collapsed);
  try { localStorage.setItem('meal-prep-sidebar-collapsed', String(collapsed)); }
  catch { /* Keep the control usable when browser storage is disabled. */ }
});

const DAYS = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'];
const SLOTS = ['breakfast', 'lunch', 'snack', 'dinner', 'prep'];
const FOCUS = ['breakfasts', 'lunches', 'snacks', 'dinners', 'weekend-prep', 'pantry', 'shopping'];
const CARD_IDS = ['food-rules', 'planning-defaults', 'stores', 'schedule', 'meal-plan', 'shopping-list', 'pantry', 'recipes', 'feedback', 'memories'];
const CARD_NAMES = {
  'food-rules': 'Food rules', 'planning-defaults': 'Planning defaults', stores: 'Preferred stores',
  schedule: 'Weekly rhythm', 'meal-plan': 'Meal plan', 'shopping-list': 'Shopping list',
  pantry: 'Pantry', recipes: 'Recipes', feedback: 'Meal feedback', memories: 'Household memory',
};
const TITLES = { overview: 'Overview', plan: 'Weekly plan', recipes: 'Recipes', pantry: 'Pantry', shopping: 'Shopping', reviews: 'Reviews', settings: 'Settings' };
const state = { view: 'overview', snapshot: null, access: null, households: [], activeHouseholdId: null, pendingInvites: [], plan: null, schedule: null, weekStart: null, recipe: null, recipeResults: null, recipeShares: [], recipeSharesUnavailable: false, shareUrl: null, shareId: null, search: '', recipeTag: '', client: null, session: null, config: null, editor: null };
function routeFromUrl() {
  const params = new URLSearchParams(location.search);
  const requestedView = params.get('view');
  const view = Object.hasOwn(TITLES, requestedView) ? requestedView : 'overview';
  const week = params.get('week');
  const validWeek = week && /^\d{4}-\d{2}-\d{2}$/.test(week) && !Number.isNaN(Date.parse(`${week}T12:00:00`));
  return {
    view,
    weekStart: view === 'plan' && validWeek ? week : null,
    recipeId: view === 'recipes' ? params.get('recipe') : null,
  };
}

function writeRoute(mode = 'push') {
  const url = new URL(location.href);
  ['view', 'week', 'recipe'].forEach((key) => url.searchParams.delete(key));
  if (state.view !== 'overview') url.searchParams.set('view', state.view);
  if (state.view === 'plan' && state.weekStart) url.searchParams.set('week', state.weekStart);
  if (state.view === 'recipes' && state.recipe?.id) url.searchParams.set('recipe', state.recipe.id);
  history[mode === 'replace' ? 'replaceState' : 'pushState'](null, '', url);
}

function loginPath() {
  return `/login?next=${encodeURIComponent(location.pathname + location.search + location.hash)}`;
}
const esc = (value) => String(value ?? '').replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;').replaceAll('"', '&quot;').replaceAll("'", '&#39;');
const arr = (value) => Array.isArray(value) ? value : [];
const pick = (value, ...keys) => keys.map((key) => value?.[key]).find((item) => item !== undefined && item !== null);
const label = (value) => String(value || '').replaceAll('_', ' ').replaceAll('-', ' ').replace(/^./, (letter) => letter.toUpperCase());
const section = (name) => state.snapshot?.sections?.[name]?.value;
const sectionStatus = (name) => state.snapshot?.sections?.[name]?.status;
const household = () => state.snapshot?.household || {};
const monday = (value = new Date()) => {
  const day = new Date(value);
  day.setHours(12, 0, 0, 0);
  day.setDate(day.getDate() - (day.getDay() + 6) % 7);
  return `${day.getFullYear()}-${String(day.getMonth() + 1).padStart(2, '0')}-${String(day.getDate()).padStart(2, '0')}`;
};
const dateForDay = (weekStart, index) => {
  const date = new Date(`${weekStart}T12:00:00`);
  date.setDate(date.getDate() + index);
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`;
};
const numberOrNull = (value) => value === '' || value === null ? null : Number(value);
const joinNames = (values) => arr(values).map((item) => typeof item === 'string' ? item : item?.name || item?.store || '').filter(Boolean).join(', ');

function showToast(message) {
  toastBox.textContent = message;
  toastBox.classList.add('show');
  clearTimeout(showToast.timer);
  showToast.timer = setTimeout(() => toastBox.classList.remove('show'), 3500);
}

async function api(path, options = {}) {
  const headers = { Accept: 'application/json', ...options.headers };
  if (options.body !== undefined) headers['Content-Type'] = 'application/json';
  if (state.client) {
    const { data, error } = await state.client.auth.getSession();
    if (error || !data.session?.access_token) {
      location.assign(loginPath());
      throw new Error('Sign in to continue.');
    }
    headers.Authorization = `Bearer ${data.session.access_token}`;
  }
  const response = await fetch(path, { ...options, headers });
  if (response.status === 401) {
    location.assign(loginPath());
    throw new Error('Your session has expired.');
  }
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.detail || `Request failed (${response.status})`);
  return data;
}

async function save(path, method, value) {
  return api(path, { method, body: JSON.stringify(value) });
}

async function loadRecipe(id) {
  state.recipe = await api(`/api/recipes/${encodeURIComponent(id)}`);
  try { state.recipeShares = (await api('/api/recipe-shares')).items; state.recipeSharesUnavailable = false; }
  catch { state.recipeShares = []; state.recipeSharesUnavailable = true; }
  state.shareUrl = null;
  state.shareId = null;
}

async function searchRecipeLibrary() {
  const params = new URLSearchParams({ limit: '25' });
  if (state.search.trim()) params.set('query', state.search.trim());
  if (state.recipeTag) params.set('tag', state.recipeTag);
  const search = state.search;
  const tag = state.recipeTag;
  const result = await api(`/api/recipes?${params}`);
  if (state.search === search && state.recipeTag === tag) {
    state.recipeResults = result.items;
    render();
  }
}

async function refresh(message) {
  const data = await api('/api/app/bootstrap');
  state.pendingInvites = arr(data.pendingInvites);
  if (data.needsInvitationReview) {
    location.replace('/invite');
    return;
  }
  state.snapshot = data.snapshot;
  if (state.client) {
    state.access = data.access;
    state.households = arr(data.memberships?.households);
    state.activeHouseholdId = data.memberships?.activeHouseholdId || null;
    householdPicker.hidden = false;
    householdSelect.innerHTML = state.households.map((item) => `<option value="${esc(item.id)}">${esc(item.name)} · ${esc(label(item.role))}</option>`).join('');
    householdSelect.value = state.activeHouseholdId || '';
  }
  state.plan = section('mealPlan');
  state.schedule = section('schedule');
  if (!state.weekStart) state.weekStart = state.plan?.weekStart || state.schedule?.week_start || monday();
  if (state.view === 'plan' && household().onboardingComplete !== false) await loadWeek(state.weekStart);
  else render();
  if (message) showToast(message);
}

async function loadWeek(weekStart) {
  const selectedWeek = monday(`${weekStart}T12:00:00`);
  const [plan, schedule] = await Promise.all([
    api(`/api/meal-plan?week_start=${encodeURIComponent(selectedWeek)}`),
    api(`/api/schedule?week_start=${encodeURIComponent(selectedWeek)}`),
  ]);
  state.weekStart = selectedWeek;
  state.plan = plan.plan;
  state.schedule = schedule.schedule;
  render();
}

function empty(title, message) {
  return `<div class="empty"><div><b>${esc(title)}</b><p class="tiny">${esc(message)}</p></div></div>`;
}
function card(title, icon, body, extra = '') {
  return `<article class="card"><div class="card-head"><h3>${esc(title)}</h3><span class="card-icon" aria-hidden="true">${esc(icon)}</span></div>${body}${extra}</article>`;
}
function tags(values, type = '') {
  return `<div class="tag-list">${arr(values).map((value) => `<span class="tag ${type}">${esc(value)}</span>`).join('')}</div>`;
}
function recipeTags(values) {
  return arr(values).length ? `<div class="tag-list recipe-tags">${arr(values).map((value) => `<button type="button" class="tag recipe-tag-button" data-action="filter-recipe-tag" data-id="${esc(value)}" aria-label="Show recipes tagged ${esc(value)}">${esc(value)}</button>`).join('')}</div>` : '';
}
function row(title, subtitle, trailing = '') {
  return `<div class="row"><div class="row-copy"><strong>${esc(title)}</strong><small>${esc(subtitle)}</small></div>${trailing}</div>`;
}
function action(text, action, data = '', css = 'ghost') {
  return `<button class="button ${css} small" data-action="${esc(action)}" data-id="${esc(data)}">${esc(text)}</button>`;
}

function dashboardLayout() {
  const saved = household().planningPreferences?.dashboard || {};
  const order = [...new Set(arr(saved.cardOrder).filter((id) => CARD_IDS.includes(id)))];
  CARD_IDS.forEach((id) => { if (!order.includes(id)) order.push(id); });
  return { order, hidden: arr(saved.hiddenCards).filter((id) => CARD_IDS.includes(id)) };
}

function renderOverview() {
  const h = household();
  const prefs = h.planningPreferences || {};
  const recipes = arr(section('recipes'));
  const pantry = arr(section('pantry'));
  const plan = section('mealPlan');
  const shopping = section('shoppingList');
  const pending = arr(shopping?.items).filter((item) => !item.purchased).length;
  const memories = arr(section('memories'));
  const incomplete = h.onboardingComplete === false;
  const displayName = h.householdName && h.householdName !== 'My household' ? h.householdName : 'Your household';
  let html = `<section class="hero"><div class="hero-copy"><p class="eyebrow">${esc(incomplete ? 'Getting started' : displayName)}</p><h2>${incomplete ? 'Set up your kitchen.' : 'Your food week, in one place.'}</h2><p>${incomplete ? 'Add your household’s food rules and weekly preferences to get started.' : 'Review your plan, recipes, pantry, and shopping list from one workspace.'}</p><div style="margin-top:22px">${action(incomplete ? 'Set up household' : 'Open weekly plan', incomplete ? 'settings' : 'plan', '', 'secondary')}</div></div><div class="hero-stat"><strong>${esc(arr(plan?.entries).length)}</strong><span>meals and prep tasks in the latest plan</span></div></section>`;
  if (state.pendingInvites.length) html = `<div class="callout"><b>Household invitation waiting</b><p>You have an invitation to join ${esc(state.pendingInvites[0].householdName)}.</p>${action('Review invitation', 'review-invite')}</div>` + html;
  const cards = {
    'food-rules': card('Food rules', '♡', h.dietaryRestrictions === null || h.dietaryRestrictions === undefined ? '<p class="muted tiny">No food rules recorded yet.</p>' : arr(h.dietaryRestrictions).length ? tags(h.dietaryRestrictions, 'orange') : '<p class="muted tiny">No dietary restrictions recorded.</p>'),
    'planning-defaults': card('Planning defaults', '⌁', `<div class="stack">${row('Household size', h.householdSize ? `${h.householdSize} people` : 'Not set')}${row('Weeknight cooking', prefs.weeknightMaxMinutes ? `${prefs.weeknightMaxMinutes} minutes maximum` : 'Not set')}${row('Lunch leftovers', prefs.leftoversForLunch === undefined ? 'Not set' : prefs.leftoversForLunch ? 'Yes' : 'No')}</div>`),
    stores: card('Preferred stores', '◇', arr(h.storePriority).length ? `<div class="stack">${arr(h.storePriority).sort((a, b) => a.priority - b.priority).map((store) => row(store.store, `Priority ${store.priority}`)).join('')}</div>` : '<p class="muted tiny">No stores recorded yet.</p>'),
    schedule: card('Weekly rhythm', '◷', state.schedule ? `<div class="stack">${arr(state.schedule.days).slice(0, 3).map((day) => row(day.day, label(day.mode || 'Flexible'))).join('')}</div>` : '<p class="muted tiny">No weekly schedule saved.</p>', `<div style="margin-top:20px">${action('Open plan', 'plan')}</div>`),
    'meal-plan': card('Weekly plan', '▦', `<div class="metric">${arr(plan?.entries).length}</div><p class="muted tiny">planned meals and prep tasks</p>`, `<div style="margin-top:20px">${action('View plan', 'plan')}</div>`),
    'shopping-list': card('Shopping', '✓', `<div class="metric">${pending}</div><p class="muted tiny">items left to pick up</p>`, `<div style="margin-top:20px">${action('Open list', 'shopping')}</div>`),
    pantry: card('Pantry', '□', `<div class="metric">${pantry.length}</div><p class="muted tiny">${pantry.length === 1 ? 'item' : 'items'} on hand</p>`, `<div style="margin-top:20px">${action('View pantry', 'pantry')}</div>`),
    recipes: card('Recent recipes', '◇', recipes.length ? `<div class="stack">${recipes.slice(0, 3).map((recipe) => row(recipe.title, `${recipe.total_minutes || '—'} min · ${recipe.servings || '—'} servings`)).join('')}</div>` : '<p class="muted tiny">No recipes saved yet.</p>', `<div style="margin-top:20px">${action('Browse recipes', 'recipes')}</div>`),
    feedback: card('Meal feedback', '♡', sectionStatus('feedback') === 'unavailable' ? '<p class="muted tiny">Cooking notes are temporarily unavailable.</p>' : arr(section('feedback')).length ? `<div class="stack">${arr(section('feedback')).slice(0, 2).map((item) => row(item.occurrence?.title || 'Weekly note', item.note)).join('')}</div>` : '<p class="muted tiny">No meal feedback yet.</p>', `<div style="margin-top:20px">${action('View reviews', 'reviews')}</div>`),
    memories: card('Household memory', '✦', memories.length ? `<div class="stack">${memories.slice(0, 2).map((item) => row(item.content, label(item.status))).join('')}</div>` : '<p class="muted tiny">No saved memories yet.</p>', `<div style="margin-top:20px">${action('View memory', 'reviews')}</div>`),
  };
  const layout = dashboardLayout();
  const visible = layout.order.filter((id) => !layout.hidden.includes(id));
  html += `<div class="section-head"><div><h2>At a glance</h2><p>The latest saved information from your household.</p></div>${action('Customize dashboard', 'settings')}</div>`;
  html += visible.length ? `<div class="card-grid dashboard-grid">${visible.map((id) => `<div data-dashboard-card="${id}">${cards[id]}</div>`).join('')}</div>` : empty('No dashboard cards shown', 'Open Settings to choose which cards to show.');
  return html;
}

function renderPlan() {
  const plan = state.plan;
  const schedule = state.schedule;
  let html = `<div class="toolbar"><label class="field">Week of<input id="week-picker" type="date" value="${esc(state.weekStart)}" /></label><div style="display:flex;gap:8px;flex-wrap:wrap">${action('Edit weekly rhythm', 'edit-schedule')}${action('Add meal or prep', 'add-meal', '', 'primary')}</div></div>`;
  if (!plan && !schedule) html += empty('This week is open', 'Add a meal or set your weekly rhythm to begin.');
  html += `<div class="week-grid">${DAYS.map((day, index) => {
    const date = dateForDay(state.weekStart, index);
    const rhythm = arr(schedule?.days).find((entry) => entry.day === day);
    const entries = arr(plan?.entries).filter((entry) => entry.date === date || (!entry.date && entry.day === day));
    return `<div class="day-card"><b>${day}</b><span class="mode">${esc(date)} · ${esc(rhythm?.mode || 'Flexible')}</span>${entries.length ? entries.map((entry) => `<div class="meal"><small>${esc(label(entry.slot || 'dinner'))}</small><strong>${esc(entry.meal || entry.title)}</strong><div style="margin-top:7px">${action('Edit', 'edit-meal', entry.id || `${day}:${entry.slot}`)} ${action('Remove', 'remove-meal', entry.id || `${day}:${entry.slot}`)}</div></div>`).join('') : '<p class="muted tiny">Nothing planned</p>'}<button class="button ghost small day-add" data-action="add-meal" data-id="${esc(date)}" aria-label="Add meal to ${day}">+ Add meal</button></div>`;
  }).join('')}</div>`;
  html += `<div class="section-head"><div><h2>Plan details</h2><p>Manual changes save to the same household plan used in MCP.</p></div></div>`;
  html += `<div class="card-grid">${card('Status', '▦', `<p class="metric">${esc(label(plan?.status || 'Draft'))}</p><p class="muted tiny">${plan ? `Week of ${esc(plan.weekStart)}` : 'No plan saved for this week'}</p>`)}${card('Meals and prep', '◇', `<p class="metric">${arr(plan?.entries).length}</p><p class="muted tiny">Entries in this week</p>`)}${card('Weekly rhythm', '◷', `<p class="metric">${arr(schedule?.days).length}/7</p><p class="muted tiny">Days with saved context</p>`)}</div>`;
  return html;
}

function renderRecipes() {
  const recipes = state.recipeResults || arr(section('recipes'));
  const query = state.search.toLowerCase();
  const matches = recipes.filter((recipe) => (!state.recipeTag || arr(recipe.tags).some((tag) => tag.toLowerCase() === state.recipeTag.toLowerCase())) && [recipe.title, recipe.description, ...arr(recipe.tags)].some((value) => String(value || '').toLowerCase().includes(query)));
  if (state.recipe) {
    const recipe = state.recipe;
    const ingredients = arr(recipe.ingredients);
    const instructions = arr(recipe.instructions);
    const activeShares = arr(state.recipeShares).filter((item) => item.recipeId === recipe.id && !item.revokedAt && (!item.expiresAt || new Date(item.expiresAt) > new Date()));
    const shareBody = state.recipeSharesUnavailable
      ? '<p class="muted tiny">Recipe sharing is temporarily unavailable.</p>'
      : `<p class="muted tiny">Anyone with a link can view this recipe. Cooking notes and household details stay private.</p>${state.shareUrl ? `<div class="share-url"><input id="share-url" aria-label="New recipe share link" readonly value="${esc(state.shareUrl)}" />${action('Copy link', 'copy-share')}</div>` : ''}${activeShares.length ? `<div class="stack share-list">${activeShares.map((item) => row('Active link', `Created ${new Date(item.createdAt).toLocaleDateString()}`, action('Revoke', 'revoke-share', item.id, 'danger'))).join('')}</div>` : ''}`;
    const feedbackBody = recipe.feedbackUnavailable
      ? '<p class="muted tiny">Cooking notes are temporarily unavailable.</p>'
      : arr(recipe.feedback).length
        ? `<div class="stack">${arr(recipe.feedback).slice(0, 5).map((item) => row(item.note, item.next_time || '')).join('')}</div>`
        : '<p class="muted tiny">No feedback yet.</p>';
    const feedbackAction = recipe.feedbackUnavailable ? '' : `<div style="margin-top:20px">${action('Add feedback', 'add-feedback', recipe.id)}</div>`;
    return `<div class="toolbar">${action('← All recipes', 'close-recipe')}<div style="display:flex;gap:8px">${action('Edit recipe', 'edit-recipe', recipe.id)}${action('Archive', 'archive-recipe', recipe.id, 'danger')}</div></div><section class="hero" style="min-height:220px"><div class="hero-copy"><p class="eyebrow">Saved recipe</p><h2>${esc(recipe.title)}</h2><p>${esc(recipe.description || 'Your household recipe.')}</p>${recipeTags(recipe.tags)}</div><div class="hero-stat"><strong>${esc(recipe.total_minutes || '—')}</strong><span>minutes total · ${esc(recipe.servings || '—')} servings</span></div></section><div class="section-head"><h2>Recipe details</h2></div><div class="card-grid">${card('Ingredients', '□', ingredients.length ? `<div class="stack">${ingredients.map((item) => row(typeof item === 'string' ? item : item.name, typeof item === 'string' ? '' : `${item.quantity ?? ''} ${item.unit || ''}`)).join('')}</div>` : '<p class="muted tiny">No ingredients saved.</p>')}${card('Method', '▦', instructions.length ? `<ol style="padding-left:18px;font-size:.75rem;line-height:1.6">${instructions.map((step) => `<li>${esc(typeof step === 'string' ? step : step.text || step.instruction)}</li>`).join('')}</ol>` : '<p class="muted tiny">No steps saved.</p>')}${card('What you learned', '♡', feedbackBody, feedbackAction)}</div><div class="section-head"><h2>Share</h2></div>${card('Share this recipe', '↗', shareBody, state.recipeSharesUnavailable ? '' : `<div style="margin-top:20px">${action('Create share link', 'create-share', recipe.id, 'primary')}</div>`)}`;
  }
  let html = `<div class="toolbar"><input class="search" id="recipe-search" type="search" placeholder="Search recipes" value="${esc(state.search)}" aria-label="Search recipes" />${action('Add recipe', 'add-recipe', '', 'primary')}</div>`;
  if (state.recipeTag) html += `<div class="recipe-filter">Showing recipes tagged <strong>${esc(state.recipeTag)}</strong> ${action('Clear tag', 'clear-recipe-tag')}</div>`;
  if (sectionStatus('recipes') === 'unavailable') return html + empty('Recipes unavailable', 'Try refreshing this page.');
  if (!matches.length) return html + empty(query || state.recipeTag ? 'No matches' : 'No recipes yet', query || state.recipeTag ? 'Try another search or clear the tag.' : 'Add the first recipe to your household library.');
  html += `<div class="recipe-grid">${matches.map((recipe) => `<article class="card recipe-card clickable"><div class="recipe-art" aria-hidden="true">${esc(recipe.title?.slice(0, 1) || 'M')}</div><div class="recipe-body"><h3>${esc(recipe.title)}</h3><p>${esc(recipe.description || 'Saved household recipe')}</p><div class="recipe-meta"><span>${esc(recipe.total_minutes || '—')} min</span><span>${esc(recipe.servings || '—')} servings</span></div>${recipeTags(recipe.tags)}<div style="margin-top:16px">${action('View recipe', 'open-recipe', recipe.id)}</div></div></article>`).join('')}</div>`;
  return html;
}

function renderPantry() {
  const items = arr(section('pantry'));
  let html = `<div class="toolbar"><p class="muted tiny">Track what is actually on hand. Dates are entered by you.</p>${action('Add pantry item', 'add-pantry', '', 'primary')}</div>`;
  if (sectionStatus('pantry') === 'unavailable') return html + empty('Pantry unavailable', 'Try refreshing this page.');
  if (!items.length) return html + empty('Your pantry is empty', 'Add food you want to keep track of.');
  html += `<div class="card table-card"><div class="table-row header"><span>Item</span><span>Remaining</span><span>Location</span><span>Use by</span><span></span></div>${items.map((item) => {
    const quantity = item.quantity === null || item.quantity === undefined ? null : Number(item.quantity);
    const reference = Number(item.reference_quantity);
    const fraction = quantity !== null && reference > 0 ? Math.round(Math.max(0, Math.min(1, quantity / reference)) * 100) : null;
    const meter = fraction === null ? '' : `<div class="pantry-stock" role="meter" aria-label="${esc(item.name)} remaining compared with tracked amount" aria-valuenow="${fraction}" aria-valuemin="0" aria-valuemax="100"><span style="width:${fraction}%"></span></div>`;
    return `<div class="table-row"><strong>${esc(item.name)}</strong><div class="pantry-quantity"><span class="tiny">${quantity === null ? 'Amount unknown' : `${esc(quantity)} ${esc(item.unit || '')} left`}</span>${meter}</div><span class="tiny">${esc(label(pick(item, 'storage_location', 'storageLocation') || 'pantry'))}</span><span class="tiny">${esc(pick(item, 'use_by_date', 'useByDate') || '—')}</span><div class="pantry-actions">${quantity !== null && quantity > 0 ? action('Use', 'use-pantry', item.id, 'primary') : ''}${action('Edit', 'edit-pantry', item.id)}</div></div>`;
  }).join('')}</div>`;
  return html;
}

function renderShopping() {
  const list = section('shoppingList');
  const items = arr(list?.items);
  let html = `<div class="toolbar"><div><p class="muted tiny">${esc(list?.name || 'Your household grocery list')}</p><p class="muted tiny">Checking an item records progress; it does not place an order.</p></div>${action('Add item', 'add-shopping', '', 'primary')}</div>`;
  if (sectionStatus('shoppingList') === 'unavailable') return html + empty('Shopping list unavailable', 'Try refreshing this page.');
  if (!items.length) return html + empty('No grocery items yet', 'Add an item to start a list.');
  const stores = [...new Set(items.map((item) => item.store || 'No store selected'))];
  html += `<div class="store-groups">${stores.map((store) => `<article class="card"><div class="card-head"><h3>${esc(store)}</h3><span class="pill">${items.filter((item) => (item.store || 'No store selected') === store).length} items</span></div>${items.filter((item) => (item.store || 'No store selected') === store).map((item) => `<div class="check-row ${item.purchased ? 'done' : ''}"><input type="checkbox" data-purchase-id="${esc(item.id)}" aria-label="Mark ${esc(item.name)} purchased" ${item.purchased ? 'checked' : ''} /><span class="row-copy"><strong>${esc(item.name)}</strong><small>${esc(item.quantity ?? '')} ${esc(item.unit || '')}</small>${item.store ? `<span class="pill store-tag" aria-label="Generally buy at ${esc(item.store)}">Usually: ${esc(item.store)}</span>` : ''}</span><div style="display:flex;gap:4px">${action('Edit', 'edit-shopping', item.id)}${action('Remove', 'remove-shopping', item.id)}</div></div>`).join('')}</article>`).join('')}</div>`;
  return html;
}

function renderReviews() {
  const feedback = arr(section('feedback'));
  const memories = arr(section('memories'));
  const feedbackUnavailable = sectionStatus('feedback') === 'unavailable';
  let html = `<div class="toolbar review-toolbar"><p class="muted tiny">Capture what went well, what was difficult, and lessons for next time.</p>${feedbackUnavailable ? '' : `<div class="review-actions">${action('Review this week', 'review-week', '', 'primary')}${action('Review a meal', 'add-feedback')}</div>`}</div>`;
  html += `<div class="review-grid"><div class="stack">`;
  html += card('Meal and week reviews', '♡', feedbackUnavailable ? '<p class="muted tiny">Reviews are temporarily unavailable.</p>' : feedback.length ? feedback.map((item) => `<div class="feedback"><div class="feedback-head"><strong>${esc(item.occurrence?.title || item.meal_title || (item.week_start ? `Week of ${item.week_start}` : 'Weekly review'))}</strong><span class="pill">${esc(label(item.feedback_type || item.feedbackType || 'review'))}</span></div><p>${esc(item.note)}</p>${item.next_time ? `<p class="next">Lesson for next time: ${esc(item.next_time)}</p>` : ''}</div>`).join('') : '<p class="muted tiny">No reviews saved yet. Start with something that worked this week.</p>');
  html += `</div><div class="stack">`;
  html += card('Household memory', '✦', memories.length ? `<div class="stack">${memories.map((item) => `<div class="row"><div class="row-copy"><strong>${esc(item.content)}</strong><small>${esc(label(item.status))} · ${esc(label(item.scope || 'persistent'))}</small></div><div style="display:flex;gap:4px">${item.status === 'suggested' ? action('Confirm', 'confirm-memory', item.id) : ''}${action('Edit', 'edit-memory', item.id)}</div></div>`).join('')}</div>` : '<p class="muted tiny">No saved memories.</p>', `<div style="margin-top:16px">${action('Add memory', 'add-memory')}</div>`);
  html += `<div class="callout"><b>How memory works</b>Meal feedback is evidence from one experience. A household memory becomes a planning default only after you confirm it.</div></div></div>`;
  return html;
}

function renderSettings() {
  const h = household();
  const prefs = h.planningPreferences || {};
  const focus = arr(prefs.focusAreas);
  const { order, hidden } = dashboardLayout();
  const restrictions = h.dietaryRestrictions === null || h.dietaryRestrictions === undefined
    ? '' : arr(h.dietaryRestrictions).length ? h.dietaryRestrictions.join(', ') : 'none';
  const stores = arr(h.storePriority).sort((a, b) => a.priority - b.priority).map((item) => item.store).join(', ');
  const focusChoices = FOCUS.map((area) => `<label class="planning-choice"><input type="checkbox" name="focusAreas" value="${area}" ${focus.includes(area) ? 'checked' : ''} /><span>${esc(label(area))}</span></label>`).join('');
  const cardRows = order.map((id, index) => `<div class="card-order-row" data-card-id="${id}"><label class="toggle-field"><span>${esc(CARD_NAMES[id])}</span><input type="checkbox" name="visibleCard" value="${id}" ${hidden.includes(id) ? '' : 'checked'} /></label><div class="card-order-buttons"><button class="icon-button" type="button" data-action="card-up" data-id="${id}" aria-label="Move ${esc(CARD_NAMES[id])} up" ${index === 0 ? 'disabled' : ''}>↑</button><button class="icon-button" type="button" data-action="card-down" data-id="${id}" aria-label="Move ${esc(CARD_NAMES[id])} down" ${index === order.length - 1 ? 'disabled' : ''}>↓</button></div></div>`).join('');
  const members = arr(state.access?.members);
  const invitations = arr(state.access?.invitations);
  const owner = state.access?.role === 'owner';
  const memberRows = members.map((member) => row(member.email, label(member.role), owner && member.role !== 'owner' ? action('Remove', 'remove-member', member.userId, 'danger') : '')).join('');
  const inviteRows = invitations.filter((invite) => invite.status === 'pending').map((invite) => row(invite.email, `Invited · expires ${new Date(invite.expiresAt).toLocaleDateString()}`, owner ? action('Revoke', 'revoke-invite', invite.id, 'danger') : '')).join('');
  const accessCard = state.client ? `<article class="card"><div class="card-head"><h3>Household members</h3><span class="card-icon">♙</span></div>
    ${state.pendingInvites.length ? `<p class="muted tiny">You have an invitation to join ${esc(state.pendingInvites[0].householdName)}.</p><div style="margin:12px 0 20px">${action('Review invitation', 'review-invite')}</div>` : ''}
    <div class="stack">${memberRows || '<p class="muted tiny">No members yet.</p>'}</div>
    ${owner ? `<form id="invite-form" class="invite-form"><label for="invite-email">Share with an existing account</label><input id="invite-email" name="email" type="email" autocomplete="email" placeholder="name@example.com" required /><button class="button primary" type="submit">Create invitation</button></form>` : ''}
    ${inviteRows ? `<p class="muted tiny" style="margin:20px 0 10px">Pending invitations</p><div class="stack">${inviteRows}</div>` : ''}
  </article>` : '';
  const householdsCard = state.client ? `<article class="card"><div class="card-head"><h3>Your households</h3><span class="card-icon">⌂</span></div>
    <p class="muted tiny">Choose a household above to switch what you see here and in MCP.</p>
    <div class="stack" style="margin:16px 0">${state.households.map((item) => row(item.name, `${label(item.role)}${item.id === state.activeHouseholdId ? ' · Active' : ''}`)).join('')}</div>
    <form id="create-household-form" class="invite-form"><label for="new-household-name">Create another household</label><input id="new-household-name" name="name" maxlength="120" required placeholder="Household name" /><button class="button primary" type="submit">Create household</button></form>
    ${state.access?.role && state.access.role !== 'owner' ? `<div style="margin-top:16px">${action('Leave this household', 'leave-household', '', 'danger')}</div>` : ''}
  </article>` : '';
  return `<div class="settings-grid"><div class="stack">
    <article class="card"><div class="card-head"><h3>Household preferences</h3><span class="card-icon">⚙</span></div>
      <form id="settings-form" class="form-grid">
        ${field('householdSize', 'People in household', h.householdSize ?? '', { type: 'number', min: 1, max: 30, required: true })}
        ${field('weeknightMaxMinutes', 'Maximum weeknight cooking minutes', prefs.weeknightMaxMinutes ?? '', { type: 'number', min: 1, max: 240, required: true })}
        ${field('dietaryRestrictions', 'Dietary restrictions — enter none if there are none', restrictions, { required: true, wide: true })}
        ${field('stores', 'Preferred stores, in order', stores, { required: true, wide: true, placeholder: 'Costco, Safeway' })}
        <fieldset class="field wide planning-field"><legend>Planning areas</legend><div class="planning-areas">${focusChoices}</div></fieldset>
        <label class="field wide toggle-field"><span>Plan dinner leftovers for lunch</span><input name="leftoversForLunch" type="checkbox" ${prefs.leftoversForLunch ? 'checked' : ''} /></label>
        <div class="field wide"><button class="button primary" type="submit">Save household setup</button></div>
      </form>
    </article>
    <article class="card"><div class="card-head"><h3>Dashboard cards</h3><span class="card-icon">▦</span></div>
      <p class="muted tiny" style="margin-bottom:14px">Choose the cards and order shown on Overview and in the chat dashboard.</p>
      <form id="dashboard-form" class="stack">${cardRows}<button class="button ghost" type="submit">Save dashboard</button></form>
    </article>
  </div><div class="stack">
    ${householdsCard}
    ${accessCard}
    <article class="card"><div class="card-head"><h3>Your session</h3><span class="card-icon">○</span></div><p class="muted tiny" style="margin-bottom:15px">${esc(state.session?.user?.email || 'Local demo mode')}</p>${state.client ? action('Sign out', 'sign-out', '', 'danger') : '<p class="muted tiny">Demo data resets when the local server restarts.</p>'}</article>
  </div></div>`;
}

function render() {
  document.querySelector('#view-title').textContent = TITLES[state.view] || 'Overview';
  document.querySelector('#view-eyebrow').textContent = state.view === 'overview' ? 'Your household' : 'Meal Prep';
  document.querySelectorAll('[data-view]').forEach((button) => button.classList.toggle('active', button.dataset.view === state.view));
  const views = { overview: renderOverview, plan: renderPlan, recipes: renderRecipes, pantry: renderPantry, shopping: renderShopping, reviews: renderReviews, settings: renderSettings };
  content.innerHTML = views[state.view]?.() || renderOverview();
}

function view(name, historyMode = 'push') {
  state.view = name;
  state.recipe = null;
  state.shareUrl = null;
  state.shareId = null;
  writeRoute(historyMode);
  render();
  window.scrollTo({ top: 0, behavior: 'smooth' });
}

function field(name, title, value = '', options = {}) {
  if (options.choices) {
    const choices = options.choices.map((choice) => typeof choice === 'string' ? { value: choice, label: label(choice) } : choice);
    const selected = choices.find((choice) => choice.value === value) || choices[0];
    const fieldId = `choice-${name}`;
    return `<div class="field ${options.wide ? 'wide' : ''}"><span id="${esc(fieldId)}-label">${esc(title)}</span>
      <div class="choice-control" data-choice-control>
        <input type="hidden" name="${esc(name)}" value="${esc(selected.value)}" />
        <button class="choice-trigger" type="button" aria-haspopup="listbox" aria-expanded="false" aria-labelledby="${esc(fieldId)}-label ${esc(fieldId)}-value">
          <span id="${esc(fieldId)}-value" class="choice-value">${esc(selected.label)}</span><span class="choice-chevron" aria-hidden="true"></span>
        </button>
        <div class="choice-menu" role="listbox" aria-labelledby="${esc(fieldId)}-label" hidden>${choices.map((choice) => `<button class="choice-option" type="button" role="option" aria-selected="${choice.value === selected.value}" data-choice-value="${esc(choice.value)}"><span class="choice-option-label">${esc(choice.label)}</span><span class="choice-check" aria-hidden="true">✓</span></button>`).join('')}</div>
      </div></div>`;
  }
  const input = options.type === 'textarea'
    ? `<textarea name="${esc(name)}" ${options.required ? 'required' : ''} placeholder="${esc(options.placeholder || '')}">${esc(value)}</textarea>`
    : `<input name="${esc(name)}" type="${esc(options.type || 'text')}" value="${esc(value)}" ${options.required ? 'required' : ''} ${options.min !== undefined ? `min="${options.min}"` : ''} ${options.max !== undefined ? `max="${options.max}"` : ''} ${options.step !== undefined ? `step="${options.step}"` : ''} placeholder="${esc(options.placeholder || '')}" />`;
  return `<label class="field ${options.wide ? 'wide' : ''}">${esc(title)}${input}</label>`;
}

function closeChoice(control, focusTrigger = false) {
  control.querySelector('.choice-menu').hidden = true;
  control.querySelector('.choice-trigger').setAttribute('aria-expanded', 'false');
  control.classList.remove('open');
  if (focusTrigger) control.querySelector('.choice-trigger').focus();
}

function openChoice(control, focusSelected = false) {
  fields.querySelectorAll('[data-choice-control].open').forEach((other) => { if (other !== control) closeChoice(other); });
  control.querySelector('.choice-menu').hidden = false;
  control.querySelector('.choice-trigger').setAttribute('aria-expanded', 'true');
  control.classList.add('open');
  if (focusSelected) control.querySelector('[aria-selected="true"]')?.focus();
}

fields.addEventListener('click', (event) => {
  const option = event.target.closest('.choice-option');
  if (option) {
    const control = option.closest('[data-choice-control]');
    control.querySelector('input[type="hidden"]').value = option.dataset.choiceValue;
    control.querySelector('.choice-value').textContent = option.querySelector('.choice-option-label').textContent;
    control.querySelectorAll('.choice-option').forEach((candidate) => candidate.setAttribute('aria-selected', String(candidate === option)));
    closeChoice(control, true);
    return;
  }
  const trigger = event.target.closest('.choice-trigger');
  if (!trigger) return;
  const control = trigger.closest('[data-choice-control]');
  if (control.classList.contains('open')) closeChoice(control);
  else openChoice(control);
});

fields.addEventListener('keydown', (event) => {
  const control = event.target.closest('[data-choice-control]');
  if (!control) return;
  const options = [...control.querySelectorAll('.choice-option')];
  if (event.key === 'Escape' && control.classList.contains('open')) {
    event.preventDefault();
    event.stopPropagation();
    closeChoice(control, true);
  } else if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
    event.preventDefault();
    if (!control.classList.contains('open')) openChoice(control);
    const index = options.indexOf(document.activeElement);
    const selectedIndex = options.findIndex((option) => option.getAttribute('aria-selected') === 'true');
    const next = index < 0 ? selectedIndex : (index + (event.key === 'ArrowDown' ? 1 : -1) + options.length) % options.length;
    options[next]?.focus();
  } else if (event.key === 'Home' || event.key === 'End') {
    if (!control.classList.contains('open')) return;
    event.preventDefault();
    options[event.key === 'Home' ? 0 : options.length - 1]?.focus();
  }
});

document.addEventListener('click', (event) => {
  if (event.target.closest('[data-choice-control]')) return;
  fields.querySelectorAll('[data-choice-control].open').forEach((control) => closeChoice(control));
});

function openEditor(kind, item = null, selectedDate = null) {
  state.editor = { kind, item };
  errorBox.hidden = true;
  let title, markup;
  if (kind === 'recipe') {
    title = item ? 'Edit recipe' : 'Add recipe';
    markup = field('title', 'Recipe name', item?.title, { required: true, wide: true }) + field('description', 'Description', item?.description, { type: 'textarea', wide: true }) + field('servings', 'Servings', item?.servings || 4, { type: 'number', min: 1 }) + field('totalMinutes', 'Total minutes', item?.total_minutes ?? item?.totalMinutes, { type: 'number', min: 1 }) + field('activeMinutes', 'Active minutes', item?.active_minutes ?? item?.activeMinutes, { type: 'number', min: 1 }) + field('tags', 'Tags, separated by commas', joinNames(item?.tags), { wide: true }) + field('ingredients', 'Ingredients — one per line: name | quantity | unit', arr(item?.ingredients).map((entry) => typeof entry === 'string' ? entry : `${entry.name || ''} | ${entry.quantity ?? ''} | ${entry.unit || ''}`).join('\n'), { type: 'textarea', wide: true }) + field('instructions', 'Instructions — one step per line', arr(item?.instructions).map((entry) => typeof entry === 'string' ? entry : entry.text || entry.instruction || '').join('\n'), { type: 'textarea', wide: true }) + field('sourceUrl', 'Source URL', item?.source_url || item?.sourceUrl, { type: 'url', wide: true });
  } else if (kind === 'pantry') {
    title = item ? 'Edit pantry item' : 'Add pantry item';
    markup = field('name', 'Item name', item?.name, { required: true, wide: true }) + field('quantity', 'Quantity', item?.quantity, { type: 'number', min: 0 }) + field('unit', 'Unit', item?.unit) + field('storageLocation', 'Storage location', pick(item, 'storage_location', 'storageLocation') || 'pantry', { choices: ['pantry', 'fridge', 'freezer', 'other'] }) + field('quantityConfidence', 'Quantity confidence', pick(item, 'quantity_confidence', 'quantityConfidence') || 'estimated', { choices: ['exact', 'estimated', 'unknown'] }) + field('useByDate', 'Use by date (only if known)', pick(item, 'use_by_date', 'useByDate'), { type: 'date' });
  } else if (kind === 'pantry-use') {
    title = `Use ${item.name}`;
    markup = `<p class="muted tiny wide">${esc(item.quantity)} ${esc(item.unit || '')} remaining</p>` + field('quantity', `Amount used (${item.unit || 'units'})`, '', { type: 'number', min: 0.001, max: item.quantity, step: 0.001, required: true }) + field('recipeId', 'Saved recipe (optional)', '', { choices: [{ value: '', label: 'No recipe' }, ...arr(section('recipes')).map((recipe) => ({ value: recipe.id, label: recipe.title }))] }) + field('mealTitle', 'Meal (optional)', '', { placeholder: 'e.g. Tuesday dinner', wide: true });
  } else if (kind === 'meal') {
    title = item ? 'Edit planned meal' : 'Add meal or prep task';
    const date = item?.date || selectedDate || state.weekStart;
    markup = field('date', 'Date', date, { type: 'date', required: true }) + field('slot', 'Meal slot', item?.slot || 'dinner', { choices: SLOTS }) + field('meal', 'Meal or task', item?.meal || item?.title, { required: true, wide: true }) + field('servings', 'Servings', item?.servings, { type: 'number', min: 1 }) + field('recipeId', 'Saved recipe', item?.recipeId || '', { choices: [{ value: '', label: 'No linked recipe' }, ...arr(section('recipes')).map((recipe) => ({ value: recipe.id, label: recipe.title }))] }) + field('notes', 'Notes', item?.notes, { type: 'textarea', wide: true });
  } else if (kind === 'shopping') {
    title = item ? 'Edit grocery item' : 'Add grocery item';
    markup = field('name', 'Item name', item?.name, { required: true, wide: true }) + field('quantity', 'Quantity', item?.quantity, { type: 'number', min: 0.001, step: 'any' }) + field('unit', 'Unit', item?.unit) + field('store', 'Where do you generally buy this? (optional)', item?.store || '', { placeholder: 'Costco, Trader Joe’s…', wide: true }) + (item ? field('listName', 'List name', section('shoppingList')?.name || 'Weekly groceries', { wide: true }) : '');
  } else if (kind === 'schedule') {
    title = 'Weekly rhythm';
    markup = field('weekStart', 'Week of', state.weekStart, { type: 'date', required: true, wide: true }) + DAYS.map((day) => field(day, day, arr(state.schedule?.days).find((item) => item.day === day)?.mode || 'flexible', { choices: ['flexible', 'quick', 'cook', 'leftovers', 'takeout', 'busy', 'prep'] })).join('');
  } else if (kind === 'weekly-review') {
    title = 'Review this week';
    markup = field('weekStart', 'Week of', state.weekStart || monday(), { type: 'date', required: true }) + field('feedbackType', 'How did it go?', 'worked_well', { choices: [{ value: 'worked_well', label: 'Worked well' }, { value: 'problem', label: 'Did not work' }, { value: 'change_next_time', label: 'Change next time' }] }) + field('note', 'What happened?', '', { type: 'textarea', required: true, wide: true, placeholder: 'For example, prepping vegetables on Sunday saved time.' }) + field('nextTime', 'Lesson learned or change for next time (optional)', '', { type: 'textarea', wide: true });
  } else if (kind === 'feedback') {
    title = 'Add meal feedback';
    markup = field('recipeId', 'Saved recipe', item?.id || '', { choices: [{ value: '', label: 'No saved recipe' }, ...arr(section('recipes')).map((recipe) => ({ value: recipe.id, label: recipe.title }))] }) + field('weekStart', 'Week of', state.weekStart || monday(), { type: 'date' }) + field('feedbackType', 'How did it go?', 'worked_well', { choices: [{ value: 'worked_well', label: 'Worked well' }, { value: 'problem', label: 'Did not work' }, { value: 'change_next_time', label: 'Change next time' }, { value: 'preference_signal', label: 'Preference signal' }] }) + field('rating', 'Rating (1–5, optional)', '', { type: 'number', min: 1, max: 5 }) + field('note', 'What happened?', '', { type: 'textarea', required: true, wide: true }) + field('nextTime', 'Lesson learned or change for next time (optional)', '', { type: 'textarea', wide: true }) + field('tags', 'Reusable tags, separated by commas', '', { wide: true }) + field('variantName', 'Preparation variant (optional)', '', { wide: true }) + field('adaptations', 'What changed — one per line', '', { type: 'textarea', wide: true });
  } else if (kind === 'memory') {
    title = item ? 'Review memory' : 'Add household memory';
    markup = field('content', 'What should be remembered?', item?.content, { type: 'textarea', required: true, wide: true }) + field('scope', 'Scope', item?.scope || 'persistent', { choices: ['persistent', 'this_week'] }) + (item ? field('action', 'Action', 'update', { choices: ['update', 'forget'] }) : '<p class="muted tiny">New memories are saved as suggestions until confirmed.</p>');
  }
  document.querySelector('#dialog-title').textContent = title;
  document.querySelector('#dialog-save').textContent = kind === 'pantry-use' ? 'Record use' : 'Save';
  fields.innerHTML = markup;
  dialog.showModal();
  fields.querySelector('input,textarea,select')?.focus();
}

async function submitEditor(data) {
  const { kind, item } = state.editor;
  const value = (name) => String(data.get(name) || '').trim();
  const lines = (name) => value(name).split('\n').map((part) => part.trim()).filter(Boolean);
  const comma = (name) => value(name).split(',').map((part) => part.trim()).filter(Boolean);
  if (kind === 'recipe') {
    const recipe = { id: item?.id, title: value('title'), description: value('description'), servings: Number(value('servings')), totalMinutes: numberOrNull(value('totalMinutes')), activeMinutes: numberOrNull(value('activeMinutes')), tags: comma('tags'), ingredients: lines('ingredients').map((line) => { const [name, quantity, unit] = line.split('|').map((part) => part.trim()); return { name, quantity: numberOrNull(quantity), unit: unit || null }; }), instructions: lines('instructions'), sourceUrl: value('sourceUrl') || null };
    const saved = await save('/api/recipes', 'PUT', recipe);
    await loadRecipe(saved.id);
    state.view = 'recipes';
    writeRoute();
  } else if (kind === 'pantry') {
    await save('/api/pantry', 'PUT', { id: item?.id, name: value('name'), quantity: numberOrNull(value('quantity')), unit: value('unit') || null, storageLocation: value('storageLocation'), quantityConfidence: value('quantityConfidence'), useByDate: value('useByDate') || null });
  } else if (kind === 'pantry-use') {
    await save('/api/pantry/use', 'POST', { itemId: item.id, quantity: Number(value('quantity')), recipeId: value('recipeId') || null, mealTitle: value('mealTitle') || null });
  } else if (kind === 'meal') {
    if (monday(`${value('date')}T12:00:00`) !== state.weekStart) throw new Error('Choose a date in the selected week.');
    const existing = arr(state.plan?.entries);
    const key = item?.id || `${item?.day}:${item?.slot}`;
    const entries = item ? existing.filter((entry) => (entry.id || `${entry.day}:${entry.slot}`) !== key) : [...existing];
    entries.push({ id: item?.id || crypto.randomUUID(), date: value('date'), day: DAYS[(new Date(`${value('date')}T12:00:00`).getDay() + 6) % 7], slot: value('slot'), meal: value('meal'), servings: numberOrNull(value('servings')), recipeId: value('recipeId') || null, notes: value('notes') });
    await save('/api/meal-plan', 'PUT', { id: state.plan?.id, weekStart: state.weekStart, status: state.plan?.status || 'draft', entries });
  } else if (kind === 'shopping') {
    const list = section('shoppingList');
    const updated = { ...item, name: value('name'), quantity: numberOrNull(value('quantity')), unit: value('unit') || null, store: value('store') || null, purchased: item?.purchased || false };
    if (item) {
      const items = arr(list?.items).filter((entry) => entry.id !== item.id);
      items.push(updated);
      await save('/api/shopping-list', 'PUT', { id: list?.id, name: value('listName') || 'Weekly groceries', status: list?.status || 'draft', mealPlanId: list?.mealPlanId, items });
    } else {
      await save('/api/shopping-list/items', 'POST', { item: updated, listId: list?.id || null });
    }
  } else if (kind === 'schedule') {
    await save('/api/schedule', 'PUT', { weekStart: value('weekStart'), days: DAYS.map((day) => ({ day, mode: value(day) })), isNormalWeek: state.schedule?.is_normal_week ?? true, rememberRhythm: state.schedule?.remember_rhythm ?? true });
  } else if (kind === 'weekly-review') {
    await save('/api/feedback', 'POST', { weekStart: monday(`${value('weekStart')}T12:00:00`), feedbackType: value('feedbackType'), note: value('note'), nextTime: value('nextTime'), tags: ['weekly-check-in'] });
  } else if (kind === 'feedback') {
    if (!value('recipeId') && !value('weekStart')) throw new Error('Choose a recipe or a week.');
    await save('/api/feedback', 'POST', { recipeId: value('recipeId') || null, weekStart: value('weekStart') || null, feedbackType: value('feedbackType'), note: value('note'), nextTime: value('nextTime'), tags: comma('tags'), rating: numberOrNull(value('rating')), variantName: value('variantName'), adaptations: lines('adaptations') });
    if (state.recipe?.id) state.recipe = await api(`/api/recipes/${encodeURIComponent(state.recipe.id)}`);
  } else if (kind === 'memory') {
    if (item) await save(`/api/memories/${encodeURIComponent(item.id)}`, 'PATCH', { action: value('action'), content: value('content') });
    else await save('/api/memories', 'POST', { content: value('content'), scope: value('scope'), status: 'suggested' });
  }
  dialog.close();
  await refresh(kind === 'pantry-use' ? 'Pantry quantity updated.' : 'Saved to your household.');
}

async function handleAction(actionName, id) {
  const recipes = arr(section('recipes'));
  const pantry = arr(section('pantry'));
  const shopping = arr(section('shoppingList')?.items);
  const plan = arr(state.plan?.entries);
  if (actionName === 'review-invite') { location.assign('/invite'); return; }
  if (actionName === 'leave-household') {
    if (!confirm('Leave this household? You will lose access to its shared data.')) return;
    await api('/api/households/leave', { method: 'POST' });
    state.weekStart = null;
    state.recipe = null;
    return refresh('You left the household.');
  }
  if (actionName === 'revoke-invite') {
    if (!confirm('Revoke this invitation?')) return;
    await api(`/api/household/invitations/${encodeURIComponent(id)}`, { method: 'DELETE' });
    return refresh('Invitation revoked.');
  }
  if (actionName === 'remove-member') {
    if (!confirm('Remove this person from the household? They will lose access to shared data.')) return;
    await api(`/api/household/members/${encodeURIComponent(id)}`, { method: 'DELETE' });
    return refresh('Collaborator removed.');
  }
  if (TITLES[actionName]) return view(actionName);
  if (actionName === 'filter-recipe-tag') {
    state.recipeTag = id;
    state.recipe = null;
    state.recipeResults = null;
    writeRoute();
    render();
    return searchRecipeLibrary();
  }
  if (actionName === 'clear-recipe-tag') {
    state.recipeTag = '';
    state.recipeResults = null;
    render();
    if (state.search.trim()) return searchRecipeLibrary();
    return;
  }
  if (actionName === 'add-recipe') return openEditor('recipe');
  if (actionName === 'edit-recipe') return openEditor('recipe', state.recipe || recipes.find((item) => item.id === id));
  if (actionName === 'open-recipe') {
    await loadRecipe(id);
    writeRoute();
    return render();
  }
  if (actionName === 'close-recipe') { state.recipe = null; state.shareUrl = null; state.shareId = null; writeRoute(); return render(); }
  if (actionName === 'create-share') {
    const share = await api(`/api/recipes/${encodeURIComponent(id)}/shares`, { method: 'POST' });
    state.shareUrl = share.url;
    state.shareId = share.id;
    try { state.recipeShares = (await api('/api/recipe-shares')).items; }
    catch { state.recipeShares = []; }
    render();
    return showToast('Share link created.');
  }
  if (actionName === 'copy-share') {
    if (!state.shareUrl) return;
    try { await navigator.clipboard.writeText(state.shareUrl); showToast('Link copied.'); }
    catch { const input = document.querySelector('#share-url'); input?.focus(); input?.select(); showToast('Link selected. Copy it with your keyboard.'); }
    return;
  }
  if (actionName === 'revoke-share') {
    await api(`/api/recipe-shares/${encodeURIComponent(id)}`, { method: 'DELETE' });
    if (id === state.shareId) { state.shareUrl = null; state.shareId = null; }
    try { state.recipeShares = (await api('/api/recipe-shares')).items; }
    catch { state.recipeShares = []; }
    render();
    return showToast('Share link revoked.');
  }
  if (actionName === 'archive-recipe') {
    if (!confirm('Archive this recipe? It will leave the active recipe library.')) return;
    await api(`/api/recipes/${encodeURIComponent(id)}`, { method: 'DELETE' });
    state.recipe = null;
    writeRoute('replace');
    return refresh('Recipe archived.');
  }
  if (actionName === 'add-pantry') return openEditor('pantry');
  if (actionName === 'edit-pantry') return openEditor('pantry', pantry.find((item) => item.id === id));
  if (actionName === 'use-pantry') return openEditor('pantry-use', pantry.find((item) => item.id === id));
  if (actionName === 'add-meal') return openEditor('meal', null, id || state.weekStart);
  if (actionName === 'edit-meal' || actionName === 'remove-meal') {
    const item = plan.find((entry) => (entry.id || `${entry.day}:${entry.slot}`) === id);
    if (!item) return;
    if (actionName === 'edit-meal') return openEditor('meal', item);
    if (!confirm(`Remove ${item.meal || item.title} from this plan?`)) return;
    await save('/api/meal-plan', 'PUT', { id: state.plan?.id, weekStart: state.weekStart, status: state.plan?.status || 'draft', entries: plan.filter((entry) => entry !== item) });
    await refresh('Meal removed.');
    return;
  }
  if (actionName === 'add-shopping') return openEditor('shopping');
  if (actionName === 'edit-shopping') return openEditor('shopping', shopping.find((item) => item.id === id));
  if (actionName === 'remove-shopping') {
    const item = shopping.find((entry) => entry.id === id);
    if (!item || !confirm(`Remove ${item.name} from the shopping list?`)) return;
    const list = section('shoppingList');
    await save('/api/shopping-list', 'PUT', { id: list.id, name: list.name, status: list.status, mealPlanId: list.mealPlanId, items: shopping.filter((entry) => entry.id !== id) });
    return refresh('Grocery item removed.');
  }
  if (actionName === 'edit-schedule') return openEditor('schedule');
  if (actionName === 'review-week') return openEditor('weekly-review');
  if (actionName === 'add-feedback') return openEditor('feedback', recipes.find((item) => item.id === id));
  if (actionName === 'add-memory') return openEditor('memory');
  if (actionName === 'edit-memory') return openEditor('memory', arr(section('memories')).find((item) => item.id === id));
  if (actionName === 'card-up' || actionName === 'card-down') {
    const form = content.querySelector('#dashboard-form');
    const rows = [...form.querySelectorAll('[data-card-id]')];
    const index = rows.findIndex((row) => row.dataset.cardId === id);
    const other = index + (actionName === 'card-up' ? -1 : 1);
    if (index < 0 || other < 0 || other >= rows.length) return;
    if (actionName === 'card-up') rows[other].before(rows[index]);
    else rows[other].after(rows[index]);
    const updated = [...form.querySelectorAll('[data-card-id]')];
    updated.forEach((row, position) => {
      row.querySelector('[data-action="card-up"]').disabled = position === 0;
      row.querySelector('[data-action="card-down"]').disabled = position === updated.length - 1;
    });
    return;
  }
  if (actionName === 'confirm-memory') {
    await save(`/api/memories/${encodeURIComponent(id)}`, 'PATCH', { action: 'confirm' });
    return refresh('Memory confirmed.');
  }
  if (actionName === 'sign-out' && state.client) {
    await state.client.auth.signOut();
    location.assign(loginPath());
  }
}

document.addEventListener('click', async (event) => {
  const nav = event.target.closest('[data-view]');
  if (nav) return view(nav.dataset.view);
  const button = event.target.closest('[data-action]');
  if (!button) return;
  event.preventDefault();
  event.stopPropagation();
  button.disabled = true;
  try { await handleAction(button.dataset.action, button.dataset.id); }
  catch (error) { showToast(error.message || 'Something went wrong.'); }
  finally { if (button.dataset.action !== 'card-up' && button.dataset.action !== 'card-down') button.disabled = false; }
});

content.addEventListener('change', async (event) => {
  if (event.target.id === 'week-picker') {
    try { await loadWeek(event.target.value); writeRoute(); }
    catch (error) { showToast(error.message); }
  }
  const checkbox = event.target.closest('[data-purchase-id]');
  if (!checkbox) return;
  checkbox.disabled = true;
  try {
    await save(`/api/shopping-list/items/${encodeURIComponent(checkbox.dataset.purchaseId)}`, 'PATCH', { purchased: checkbox.checked });
    await refresh('Shopping progress saved.');
  } catch (error) {
    checkbox.checked = !checkbox.checked;
    showToast(error.message);
  } finally { checkbox.disabled = false; }
});

content.addEventListener('input', (event) => {
  if (event.target.id !== 'recipe-search') return;
  const start = event.target.selectionStart;
  state.search = event.target.value;
  if (!state.search.trim()) state.recipeResults = null;
  render();
  const next = document.querySelector('#recipe-search');
  next?.focus();
  next?.setSelectionRange(start, start);
  clearTimeout(state.searchTimer);
  const search = state.search;
  if (!search.trim() && !state.recipeTag) return;
  state.searchTimer = setTimeout(async () => {
    try {
      await searchRecipeLibrary();
      if (state.search !== search) return;
      const input = document.querySelector('#recipe-search');
      input?.focus();
      input?.setSelectionRange(start, start);
    } catch (error) { showToast(error.message); }
  }, 250);
});

content.addEventListener('submit', async (event) => {
  if (!['settings-form', 'dashboard-form', 'invite-form', 'create-household-form'].includes(event.target.id)) return;
  event.preventDefault();
  const submit = event.target.querySelector('[type="submit"]');
  submit.disabled = true;
  try {
    const data = new FormData(event.target);
    if (event.target.id === 'create-household-form') {
      await save('/api/households', 'POST', { name: String(data.get('name') || '').trim() });
      state.weekStart = null;
      state.recipe = null;
      await refresh('Household created and selected.');
      return;
    }
    if (event.target.id === 'invite-form') {
      await save('/api/household/invitations', 'POST', { email: String(data.get('email') || '').trim() });
      await refresh('Invitation created. Ask them to open Meal Prep.');
      return;
    }
    if (event.target.id === 'settings-form') {
      const restrictionText = String(data.get('dietaryRestrictions') || '').trim();
      const stores = String(data.get('stores') || '').split(',').map((item) => item.trim()).filter(Boolean);
      if (!stores.length) throw new Error('Enter at least one preferred store.');
      const prefs = household().planningPreferences || {};
      await save('/api/household', 'PATCH', { householdSize: Number(data.get('householdSize')), dietaryRestrictions: /^(none|no restrictions)$/i.test(restrictionText) ? [] : restrictionText.split(',').map((item) => item.trim()).filter(Boolean), storePriority: stores.map((store, index) => ({ store, priority: index + 1 })), planningPreferences: { ...prefs, weeknightMaxMinutes: Number(data.get('weeknightMaxMinutes')), leftoversForLunch: data.has('leftoversForLunch'), focusAreas: data.getAll('focusAreas') }, completeOnboarding: true });
    } else if (event.target.id === 'dashboard-form') {
      const visible = data.getAll('visibleCard');
      const cardOrder = [...event.target.querySelectorAll('[data-card-id]')].map((row) => row.dataset.cardId);
      const result = await save('/api/dashboard-layout', 'PATCH', {
        cardOrder, hiddenCards: CARD_IDS.filter((id) => !visible.includes(id)),
      });
      state.snapshot.household = result.household;
      render();
      showToast('Dashboard saved.');
      return;
    }
    await refresh('Settings saved.');
  } catch (error) { showToast(error.message); }
  finally { submit.disabled = false; }
});

form.addEventListener('submit', async (event) => {
  if (event.submitter?.value === 'cancel') return;
  event.preventDefault();
  errorBox.hidden = true;
  const button = document.querySelector('#dialog-save');
  button.disabled = true;
  try { await submitEditor(new FormData(form)); }
  catch (error) { errorBox.textContent = error.message || 'Could not save. Please try again.'; errorBox.hidden = false; }
  finally { button.disabled = false; }
});

document.querySelector('#refresh-button').addEventListener('click', () => refresh('Up to date.').catch((error) => showToast(error.message)));
document.querySelector('#account-button').addEventListener('click', () => view('settings'));
householdSelect.addEventListener('change', async () => {
  householdSelect.disabled = true;
  try {
    await api(`/api/households/${encodeURIComponent(householdSelect.value)}/activate`, { method: 'POST' });
    state.weekStart = null;
    state.recipe = null;
    state.recipeResults = null;
    state.shareUrl = null;
    state.shareId = null;
    writeRoute('replace');
    await refresh('Household switched.');
  } catch (error) {
    householdSelect.value = state.activeHouseholdId || '';
    showToast(error.message);
  } finally { householdSelect.disabled = false; }
});

async function start() {
  const route = routeFromUrl();
  state.view = route.view;
  state.weekStart = route.weekStart;
  state.config = await fetch('/api/auth/config').then((response) => response.json());
  if (state.config.supabaseUrl && state.config.supabaseAnonKey) {
    if (!window.supabase?.createClient) throw new Error('Sign in is unavailable. Check your connection and reload.');
    state.client = window.supabase.createClient(state.config.supabaseUrl, state.config.supabaseAnonKey);
    const { data, error } = await state.client.auth.getSession();
    if (error || !data.session) { location.replace(loginPath()); return; }
    state.session = data.session;
    const email = data.session.user?.email || 'Account';
    document.querySelector('#account-label').textContent = email;
    document.querySelector('#account-avatar').textContent = email.slice(0, 2).toUpperCase();
  } else {
    document.querySelector('#mode-badge').hidden = false;
    document.querySelector('#account-label').textContent = 'Local demo';
  }
  await refresh();
  if (household().onboardingComplete === false && !state.pendingInvites.length) {
    view('settings', 'replace');
    return;
  }
  if (route.recipeId) { await loadRecipe(route.recipeId); render(); }
}

window.addEventListener('popstate', async () => {
  const route = routeFromUrl();
  state.view = route.view;
  state.recipe = null;
  state.shareUrl = null;
  state.shareId = null;
  state.plan = section('mealPlan');
  state.schedule = section('schedule');
  state.weekStart = route.weekStart || state.plan?.weekStart || state.schedule?.week_start || monday();
  render();
  try {
    if (route.weekStart) await loadWeek(route.weekStart);
    if (route.recipeId) { await loadRecipe(route.recipeId); render(); }
  } catch (error) { showToast(error.message || 'Could not open this page.'); }
});

start().catch((error) => {
  content.innerHTML = empty('Could not open Meal Prep', error.message || 'Please reload and try again.');
});
