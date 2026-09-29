const content = document.querySelector('#app-content');
const dialog = document.querySelector('#editor-dialog');
const form = document.querySelector('#editor-form');
const fields = document.querySelector('#dialog-fields');
const errorBox = document.querySelector('#dialog-error');
const toastBox = document.querySelector('#toast');

const DAYS = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'];
const SLOTS = ['breakfast', 'lunch', 'snack', 'dinner', 'prep'];
const FOCUS = ['breakfasts', 'lunches', 'snacks', 'dinners', 'weekend-prep', 'pantry', 'shopping'];
const CARD_IDS = ['food-rules', 'planning-defaults', 'stores', 'schedule', 'meal-plan', 'shopping-list', 'pantry', 'recipes', 'retro', 'feedback', 'memories'];
const CARD_NAMES = {
  'food-rules': 'Food rules', 'planning-defaults': 'Planning defaults', stores: 'Preferred stores',
  schedule: 'Weekly rhythm', 'meal-plan': 'Meal plan', 'shopping-list': 'Shopping list',
  pantry: 'Pantry', recipes: 'Recipes', retro: 'Weekly review', feedback: 'Meal feedback', memories: 'Household memory',
};
const TITLES = { overview: 'Overview', plan: 'Weekly plan', recipes: 'Recipes', pantry: 'Pantry', shopping: 'Shopping', reviews: 'Reviews', settings: 'Settings' };
const state = { view: 'overview', snapshot: null, plan: null, schedule: null, weekStart: null, recipe: null, recipeResults: null, search: '', client: null, session: null, config: null, editor: null };
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
      location.assign('/login?next=%2F');
      throw new Error('Sign in to continue.');
    }
    headers.Authorization = `Bearer ${data.session.access_token}`;
  }
  const response = await fetch(path, { ...options, headers });
  if (response.status === 401) {
    location.assign('/login?next=%2F');
    throw new Error('Your session has expired.');
  }
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.detail || `Request failed (${response.status})`);
  return data;
}

async function save(path, method, value) {
  return api(path, { method, body: JSON.stringify(value) });
}

async function refresh(message) {
  const snapshot = await api('/api/app/snapshot');
  state.snapshot = snapshot;
  state.plan = section('mealPlan');
  state.schedule = section('schedule');
  if (!state.weekStart) state.weekStart = state.plan?.weekStart || state.schedule?.week_start || monday();
  render();
  if (message) showToast(message);
}

async function loadWeek(weekStart) {
  state.weekStart = monday(`${weekStart}T12:00:00`);
  const [plan, schedule] = await Promise.all([
    api(`/api/meal-plan?week_start=${encodeURIComponent(state.weekStart)}`),
    api(`/api/schedule?week_start=${encodeURIComponent(state.weekStart)}`),
  ]);
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
function row(title, subtitle, trailing = '') {
  return `<div class="row"><div class="row-copy"><strong>${esc(title)}</strong><small>${esc(subtitle)}</small></div>${trailing}</div>`;
}
function action(text, action, data = '', css = 'ghost') {
  return `<button class="button ${css} small" data-action="${esc(action)}" data-id="${esc(data)}">${esc(text)}</button>`;
}

function renderOverview() {
  const h = household();
  const prefs = h.planningPreferences || {};
  const recipes = arr(section('recipes'));
  const pantry = arr(section('pantry'));
  const plan = section('mealPlan');
  const shopping = section('shoppingList');
  const pending = arr(shopping?.items).filter((item) => !item.purchased).length;
  const incomplete = h.onboardingComplete === false;
  const displayName = h.householdName || 'Your household';
  let html = `<section class="hero"><div class="hero-copy"><p class="eyebrow">A calmer food week starts here</p><h2>${incomplete ? 'Let’s set up your kitchen.' : `Welcome to ${esc(displayName)}.`}</h2><p>${incomplete ? 'Add your household’s food rules and weekly preferences to get started.' : 'Your recipes, food on hand, weekly plan, and groceries live together here.'}</p><div style="margin-top:22px">${action(incomplete ? 'Set up household' : 'Open weekly plan', incomplete ? 'settings' : 'plan', '', 'secondary')}</div></div><div class="hero-stat"><strong>${esc(arr(plan?.entries).length)}</strong><span>meals and prep tasks in the latest plan</span></div></section>`;
  html += `<div class="section-head"><div><h2>At a glance</h2><p>The latest saved information from your household.</p></div></div>`;
  html += `<div class="card-grid">`;
  html += card('Weekly plan', '▦', `<div class="metric">${arr(plan?.entries).length}</div><p class="muted tiny">planned meals and prep tasks</p>`, `<div style="margin-top:20px">${action('View plan', 'plan')}</div>`);
  html += card('Shopping', '✓', `<div class="metric">${pending}</div><p class="muted tiny">items left to pick up</p>`, `<div style="margin-top:20px">${action('Open list', 'shopping')}</div>`);
  html += card('Pantry', '□', `<div class="metric">${pantry.length}</div><p class="muted tiny">${pantry.length === 1 ? 'item' : 'items'} on hand</p>`, `<div style="margin-top:20px">${action('View pantry', 'pantry')}</div>`);
  html += `</div>`;
  html += `<div class="section-head"><div><h2>Your kitchen</h2><p>What this household is planning around.</p></div>${action('Edit preferences', 'settings')}</div>`;
  html += `<div class="card-grid">`;
  html += card('Food rules', '♡', h.dietaryRestrictions === null || h.dietaryRestrictions === undefined ? '<p class="muted tiny">No food rules recorded yet.</p>' : arr(h.dietaryRestrictions).length ? tags(h.dietaryRestrictions, 'orange') : '<p class="muted tiny">No dietary restrictions recorded.</p>');
  html += card('Planning defaults', '⌁', `<div class="stack">${row('Household size', h.householdSize ? `${h.householdSize} people` : 'Not set')}${row('Weeknight cooking', prefs.weeknightMaxMinutes ? `${prefs.weeknightMaxMinutes} minutes maximum` : 'Not set')}${row('Lunch leftovers', prefs.leftoversForLunch === undefined ? 'Not set' : prefs.leftoversForLunch ? 'Yes' : 'No')}</div>`);
  html += card('Preferred stores', '◇', arr(h.storePriority).length ? `<div class="stack">${arr(h.storePriority).sort((a, b) => a.priority - b.priority).map((store) => row(store.store, `Priority ${store.priority}`)).join('')}</div>` : '<p class="muted tiny">No stores recorded yet.</p>');
  html += `</div>`;
  html += `<div class="section-head"><div><h2>Quick access</h2><p>Pick up where you left off.</p></div></div><div class="card-grid">`;
  html += card('Recent recipes', '◇', recipes.length ? `<div class="stack">${recipes.slice(0, 3).map((recipe) => row(recipe.title, `${recipe.total_minutes || '—'} min · ${recipe.servings || '—'} servings`)).join('')}</div>` : '<p class="muted tiny">No recipes saved yet.</p>', `<div style="margin-top:20px">${action('Browse recipes', 'recipes')}</div>`);
  html += card('Meal feedback', '♡', arr(section('feedback')).length ? `<div class="stack">${arr(section('feedback')).slice(0, 2).map((item) => row(item.occurrence?.title || 'Meal', item.note)).join('')}</div>` : '<p class="muted tiny">No meal feedback yet.</p>', `<div style="margin-top:20px">${action('View reviews', 'reviews')}</div>`);
  html += card('Weekly rhythm', '◷', state.schedule ? `<div class="stack">${arr(state.schedule.days).slice(0, 3).map((day) => row(day.day, label(day.mode || 'Flexible'))).join('')}</div>` : '<p class="muted tiny">No weekly schedule saved.</p>', `<div style="margin-top:20px">${action('Open plan', 'plan')}</div>`);
  html += `</div>`;
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
    return `<div class="day-card"><b>${day}</b><span class="mode">${esc(date)} · ${esc(rhythm?.mode || 'Flexible')}</span>${entries.length ? entries.map((entry) => `<div class="meal"><small>${esc(label(entry.slot || 'dinner'))}</small><strong>${esc(entry.meal || entry.title)}</strong><div style="margin-top:7px">${action('Edit', 'edit-meal', entry.id || `${day}:${entry.slot}`)} ${action('Remove', 'remove-meal', entry.id || `${day}:${entry.slot}`)}</div></div>`).join('') : '<p class="muted tiny">Nothing planned</p>'}</div>`;
  }).join('')}</div>`;
  html += `<div class="section-head"><div><h2>Plan details</h2><p>Manual changes save to the same household plan used in MCP.</p></div></div>`;
  html += `<div class="card-grid">${card('Status', '▦', `<p class="metric">${esc(label(plan?.status || 'Draft'))}</p><p class="muted tiny">${plan ? `Week of ${esc(plan.weekStart)}` : 'No plan saved for this week'}</p>`)}${card('Meals and prep', '◇', `<p class="metric">${arr(plan?.entries).length}</p><p class="muted tiny">Entries in this week</p>`)}${card('Weekly rhythm', '◷', `<p class="metric">${arr(schedule?.days).length}/7</p><p class="muted tiny">Days with saved context</p>`)}</div>`;
  return html;
}

function renderRecipes() {
  const recipes = state.recipeResults || arr(section('recipes'));
  const query = state.search.toLowerCase();
  const matches = recipes.filter((recipe) => [recipe.title, recipe.description, ...arr(recipe.tags)].some((value) => String(value || '').toLowerCase().includes(query)));
  if (state.recipe) {
    const recipe = state.recipe;
    const ingredients = arr(recipe.ingredients);
    const instructions = arr(recipe.instructions);
    return `<div class="toolbar">${action('← All recipes', 'close-recipe')}<div style="display:flex;gap:8px">${action('Edit recipe', 'edit-recipe', recipe.id)}${action('Archive', 'archive-recipe', recipe.id, 'danger')}</div></div><section class="hero" style="min-height:220px"><div class="hero-copy"><p class="eyebrow">Saved recipe</p><h2>${esc(recipe.title)}</h2><p>${esc(recipe.description || 'Your household recipe.')}</p></div><div class="hero-stat"><strong>${esc(recipe.total_minutes || '—')}</strong><span>minutes total · ${esc(recipe.servings || '—')} servings</span></div></section><div class="section-head"><h2>Recipe details</h2></div><div class="card-grid">${card('Ingredients', '□', ingredients.length ? `<div class="stack">${ingredients.map((item) => row(typeof item === 'string' ? item : item.name, typeof item === 'string' ? '' : `${item.quantity ?? ''} ${item.unit || ''}`)).join('')}</div>` : '<p class="muted tiny">No ingredients saved.</p>')}${card('Method', '▦', instructions.length ? `<ol style="padding-left:18px;font-size:.75rem;line-height:1.6">${instructions.map((step) => `<li>${esc(typeof step === 'string' ? step : step.text || step.instruction)}</li>`).join('')}</ol>` : '<p class="muted tiny">No steps saved.</p>')}${card('What you learned', '♡', arr(recipe.feedback).length ? `<div class="stack">${arr(recipe.feedback).slice(0, 5).map((item) => row(item.note, item.next_time || '')).join('')}</div>` : '<p class="muted tiny">No feedback yet.</p>', `<div style="margin-top:20px">${action('Add feedback', 'add-feedback', recipe.id)}</div>`)}</div>`;
  }
  let html = `<div class="toolbar"><input class="search" id="recipe-search" type="search" placeholder="Search recipes" value="${esc(state.search)}" aria-label="Search recipes" />${action('Add recipe', 'add-recipe', '', 'primary')}</div>`;
  if (sectionStatus('recipes') === 'unavailable') return html + empty('Recipes unavailable', 'Try refreshing this page.');
  if (!matches.length) return html + empty(query ? 'No matches' : 'No recipes yet', query ? 'Try another search.' : 'Add the first recipe to your household library.');
  html += `<div class="recipe-grid">${matches.map((recipe) => `<article class="card recipe-card clickable"><div class="recipe-art" aria-hidden="true">${esc(recipe.title?.slice(0, 1) || 'M')}</div><div class="recipe-body"><h3>${esc(recipe.title)}</h3><p>${esc(recipe.description || 'Saved household recipe')}</p><div class="recipe-meta"><span>${esc(recipe.total_minutes || '—')} min</span><span>${esc(recipe.servings || '—')} servings</span></div><div style="margin-top:16px">${action('View recipe', 'open-recipe', recipe.id)}</div></div></article>`).join('')}</div>`;
  return html;
}

function renderPantry() {
  const items = arr(section('pantry'));
  let html = `<div class="toolbar"><p class="muted tiny">Track what is actually on hand. Dates are entered by you.</p>${action('Add pantry item', 'add-pantry', '', 'primary')}</div>`;
  if (sectionStatus('pantry') === 'unavailable') return html + empty('Pantry unavailable', 'Try refreshing this page.');
  if (!items.length) return html + empty('Your pantry is empty', 'Add food you want to keep track of.');
  html += `<div class="card table-card"><div class="table-row header"><span>Item</span><span>Quantity</span><span>Location</span><span>Use by</span><span></span></div>${items.map((item) => `<div class="table-row"><strong>${esc(item.name)}</strong><span class="tiny">${esc(item.quantity ?? '—')} ${esc(item.unit || '')}</span><span class="tiny">${esc(label(pick(item, 'storage_location', 'storageLocation') || 'pantry'))}</span><span class="tiny">${esc(pick(item, 'use_by_date', 'useByDate') || '—')}</span>${action('Edit', 'edit-pantry', item.id)}</div>`).join('')}</div>`;
  return html;
}

function renderShopping() {
  const list = section('shoppingList');
  const items = arr(list?.items);
  let html = `<div class="toolbar"><div><p class="muted tiny">${esc(list?.name || 'Your household grocery list')}</p><p class="muted tiny">Checking an item records progress; it does not place an order.</p></div>${action('Add item', 'add-shopping', '', 'primary')}</div>`;
  if (sectionStatus('shoppingList') === 'unavailable') return html + empty('Shopping list unavailable', 'Try refreshing this page.');
  if (!items.length) return html + empty('No grocery items yet', 'Add an item to start a list.');
  const stores = [...new Set(items.map((item) => item.store || 'Other'))];
  html += `<div class="store-groups">${stores.map((store) => `<article class="card"><div class="card-head"><h3>${esc(store)}</h3><span class="pill">${items.filter((item) => (item.store || 'Other') === store).length} items</span></div>${items.filter((item) => (item.store || 'Other') === store).map((item) => `<div class="check-row ${item.purchased ? 'done' : ''}"><input type="checkbox" data-purchase-id="${esc(item.id)}" aria-label="Mark ${esc(item.name)} purchased" ${item.purchased ? 'checked' : ''} /><span class="row-copy"><strong>${esc(item.name)}</strong><small>${esc(item.quantity ?? '')} ${esc(item.unit || '')}</small></span><div style="display:flex;gap:4px">${action('Edit', 'edit-shopping', item.id)}${action('Remove', 'remove-shopping', item.id)}</div></div>`).join('')}</article>`).join('')}</div>`;
  return html;
}

function renderReviews() {
  const retro = section('retro');
  const feedback = arr(section('feedback'));
  const memories = arr(section('memories'));
  let html = `<div class="toolbar"><p class="muted tiny">Keep weekly reflections, meal experiences, and lasting household preferences distinct.</p><div style="display:flex;gap:8px">${action('Add meal feedback', 'add-feedback')}${action('Edit weekly review', 'edit-retro', '', 'primary')}</div></div>`;
  html += `<div class="review-grid"><div class="stack">`;
  html += card('Latest weekly review', '◷', retro ? `<p class="muted tiny">Week of ${esc(retro.week_start || retro.weekStart)}</p><p style="margin:12px 0;font-size:.8rem;line-height:1.5">${esc(retro.note || 'No overall note.')}</p><div class="stack">${row('What worked', joinNames(retro.worked_well || retro.workedWell) || 'No notes')}${row('Stressors', joinNames(retro.stressors) || 'No notes')}</div>` : '<p class="muted tiny">No weekly review saved yet.</p>');
  html += card('Meal feedback', '♡', feedback.length ? feedback.map((item) => `<div class="feedback"><div class="feedback-head"><strong>${esc(item.occurrence?.title || item.meal_title || 'Meal experience')}</strong><span class="pill">${esc(label(item.feedback_type || item.feedbackType || 'feedback'))}</span></div><p>${esc(item.note)}</p>${item.next_time ? `<p class="next">Next time: ${esc(item.next_time)}</p>` : ''}</div>`).join('') : '<p class="muted tiny">No meal feedback saved yet.</p>');
  html += `</div><div class="stack">`;
  html += card('Household memory', '✦', memories.length ? `<div class="stack">${memories.map((item) => `<div class="row"><div class="row-copy"><strong>${esc(item.content)}</strong><small>${esc(label(item.status))} · ${esc(label(item.scope || 'persistent'))}</small></div><div style="display:flex;gap:4px">${item.status === 'suggested' ? action('Confirm', 'confirm-memory', item.id) : ''}${action('Edit', 'edit-memory', item.id)}</div></div>`).join('')}</div>` : '<p class="muted tiny">No saved memories.</p>', `<div style="margin-top:16px">${action('Add memory', 'add-memory')}</div>`);
  html += `<div class="callout"><b>How memory works</b>Meal feedback is evidence from one experience. A household memory becomes a planning default only after you confirm it.</div></div></div>`;
  return html;
}

function renderSettings() {
  const h = household();
  const prefs = h.planningPreferences || {};
  const focus = arr(prefs.focusAreas);
  const layout = prefs.dashboard || {};
  const hidden = arr(layout.hiddenCards);
  const order = [...new Set(arr(layout.cardOrder).filter((id) => CARD_IDS.includes(id)))];
  CARD_IDS.forEach((id) => { if (!order.includes(id)) order.push(id); });
  const restrictions = h.dietaryRestrictions === null || h.dietaryRestrictions === undefined
    ? '' : arr(h.dietaryRestrictions).length ? h.dietaryRestrictions.join(', ') : 'none';
  const stores = arr(h.storePriority).sort((a, b) => a.priority - b.priority).map((item) => item.store).join(', ');
  const focusChoices = FOCUS.map((area) => `<label class="tag"><input type="checkbox" name="focusAreas" value="${area}" ${focus.includes(area) ? 'checked' : ''} /> ${esc(label(area))}</label>`).join('');
  const cardRows = order.map((id, index) => `<div class="card-order-row"><label class="toggle-field"><span>${esc(CARD_NAMES[id])}</span><input type="checkbox" name="visibleCard" value="${id}" ${hidden.includes(id) ? '' : 'checked'} /></label><div class="card-order-buttons"><button class="icon-button" type="button" data-action="card-up" data-id="${id}" aria-label="Move ${esc(CARD_NAMES[id])} up" ${index === 0 ? 'disabled' : ''}>↑</button><button class="icon-button" type="button" data-action="card-down" data-id="${id}" aria-label="Move ${esc(CARD_NAMES[id])} down" ${index === order.length - 1 ? 'disabled' : ''}>↓</button></div></div>`).join('');
  return `<div class="settings-grid"><div class="stack">
    <article class="card"><div class="card-head"><h3>Household preferences</h3><span class="card-icon">⚙</span></div>
      <form id="settings-form" class="form-grid">
        ${field('householdSize', 'People in household', h.householdSize ?? '', { type: 'number', min: 1, max: 30, required: true })}
        ${field('weeknightMaxMinutes', 'Maximum weeknight cooking minutes', prefs.weeknightMaxMinutes ?? '', { type: 'number', min: 1, max: 240, required: true })}
        ${field('dietaryRestrictions', 'Dietary restrictions — enter none if there are none', restrictions, { required: true, wide: true })}
        ${field('stores', 'Preferred stores, in order', stores, { required: true, wide: true, placeholder: 'Costco, Safeway' })}
        <div class="field wide"><span>Planning areas</span><div class="tag-list">${focusChoices}</div></div>
        <label class="field wide toggle-field"><span>Plan dinner leftovers for lunch</span><input name="leftoversForLunch" type="checkbox" ${prefs.leftoversForLunch ? 'checked' : ''} /></label>
        <div class="field wide"><button class="button primary" type="submit">Save household setup</button></div>
      </form>
    </article>
    <article class="card"><div class="card-head"><h3>Dashboard cards</h3><span class="card-icon">▦</span></div>
      <p class="muted tiny" style="margin-bottom:14px">Show, hide, and reorder cards in the MCP household dashboard.</p>
      <form id="dashboard-form" class="stack">${cardRows}<button class="button ghost" type="submit">Save visible cards</button></form>
    </article>
  </div><div class="stack">
    <div class="callout"><b>One account across surfaces</b>Sign in with the same approved email on the website and through the MCP connection. Your household data is shared; each client keeps its own session.</div>
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

function view(name) {
  state.view = name;
  state.recipe = null;
  render();
  window.scrollTo({ top: 0, behavior: 'smooth' });
}

function field(name, title, value = '', options = {}) {
  const input = options.type === 'textarea'
    ? `<textarea name="${esc(name)}" ${options.required ? 'required' : ''} placeholder="${esc(options.placeholder || '')}">${esc(value)}</textarea>`
    : options.choices
      ? `<select name="${esc(name)}">${options.choices.map((choice) => { const optionValue = typeof choice === 'string' ? choice : choice.value; const optionLabel = typeof choice === 'string' ? label(choice) : choice.label; return `<option value="${esc(optionValue)}" ${optionValue === value ? 'selected' : ''}>${esc(optionLabel)}</option>`; }).join('')}</select>`
      : `<input name="${esc(name)}" type="${esc(options.type || 'text')}" value="${esc(value)}" ${options.required ? 'required' : ''} ${options.min !== undefined ? `min="${options.min}"` : ''} ${options.max !== undefined ? `max="${options.max}"` : ''} placeholder="${esc(options.placeholder || '')}" />`;
  return `<label class="field ${options.wide ? 'wide' : ''}">${esc(title)}${input}</label>`;
}

function openEditor(kind, item = null) {
  state.editor = { kind, item };
  errorBox.hidden = true;
  let title, markup;
  if (kind === 'recipe') {
    title = item ? 'Edit recipe' : 'Add recipe';
    markup = field('title', 'Recipe name', item?.title, { required: true, wide: true }) + field('description', 'Description', item?.description, { type: 'textarea', wide: true }) + field('servings', 'Servings', item?.servings || 4, { type: 'number', min: 1 }) + field('totalMinutes', 'Total minutes', item?.total_minutes ?? item?.totalMinutes, { type: 'number', min: 1 }) + field('activeMinutes', 'Active minutes', item?.active_minutes ?? item?.activeMinutes, { type: 'number', min: 1 }) + field('tags', 'Tags, separated by commas', joinNames(item?.tags), { wide: true }) + field('ingredients', 'Ingredients — one per line: name | quantity | unit', arr(item?.ingredients).map((entry) => typeof entry === 'string' ? entry : `${entry.name || ''} | ${entry.quantity ?? ''} | ${entry.unit || ''}`).join('\n'), { type: 'textarea', wide: true }) + field('instructions', 'Instructions — one step per line', arr(item?.instructions).map((entry) => typeof entry === 'string' ? entry : entry.text || entry.instruction || '').join('\n'), { type: 'textarea', wide: true }) + field('sourceUrl', 'Source URL', item?.source_url || item?.sourceUrl, { type: 'url', wide: true });
  } else if (kind === 'pantry') {
    title = item ? 'Edit pantry item' : 'Add pantry item';
    markup = field('name', 'Item name', item?.name, { required: true, wide: true }) + field('quantity', 'Quantity', item?.quantity, { type: 'number', min: 0 }) + field('unit', 'Unit', item?.unit) + field('storageLocation', 'Storage location', pick(item, 'storage_location', 'storageLocation') || 'pantry', { choices: ['pantry', 'fridge', 'freezer', 'other'] }) + field('quantityConfidence', 'Quantity confidence', pick(item, 'quantity_confidence', 'quantityConfidence') || 'estimated', { choices: ['exact', 'estimated', 'unknown'] }) + field('useByDate', 'Use by date (only if known)', pick(item, 'use_by_date', 'useByDate'), { type: 'date' });
  } else if (kind === 'meal') {
    title = item ? 'Edit planned meal' : 'Add meal or prep task';
    const date = item?.date || state.weekStart;
    markup = field('date', 'Date', date, { type: 'date', required: true }) + field('slot', 'Meal slot', item?.slot || 'dinner', { choices: SLOTS }) + field('meal', 'Meal or task', item?.meal || item?.title, { required: true, wide: true }) + field('servings', 'Servings', item?.servings, { type: 'number', min: 1 }) + field('recipeId', 'Saved recipe', item?.recipeId || '', { choices: [{ value: '', label: 'No linked recipe' }, ...arr(section('recipes')).map((recipe) => ({ value: recipe.id, label: recipe.title }))] }) + field('notes', 'Notes', item?.notes, { type: 'textarea', wide: true });
  } else if (kind === 'shopping') {
    title = item ? 'Edit grocery item' : 'Add grocery item';
    markup = field('name', 'Item name', item?.name, { required: true, wide: true }) + field('quantity', 'Quantity', item?.quantity, { type: 'number', min: 0 }) + field('unit', 'Unit', item?.unit) + field('store', 'Store', item?.store || arr(household().storePriority)[0]?.store || '', { required: true }) + field('listName', 'List name', section('shoppingList')?.name || 'Weekly groceries', { wide: true });
  } else if (kind === 'schedule') {
    title = 'Weekly rhythm';
    markup = field('weekStart', 'Week of', state.weekStart, { type: 'date', required: true, wide: true }) + DAYS.map((day) => field(day, day, arr(state.schedule?.days).find((item) => item.day === day)?.mode || 'flexible', { choices: ['flexible', 'quick', 'cook', 'leftovers', 'takeout', 'busy', 'prep'] })).join('');
  } else if (kind === 'retro') {
    title = 'Weekly review';
    const retro = section('retro');
    markup = field('weekStart', 'Week of', retro?.week_start || retro?.weekStart || state.weekStart, { type: 'date', required: true }) + field('workedWell', 'What worked — one per line', arr(retro?.worked_well || retro?.workedWell).join('\n'), { type: 'textarea', wide: true }) + field('stressors', 'What was hard — one per line', arr(retro?.stressors).join('\n'), { type: 'textarea', wide: true }) + field('note', 'Overall note', retro?.note, { type: 'textarea', wide: true });
  } else if (kind === 'feedback') {
    title = 'Add meal feedback';
    markup = field('recipeId', 'Saved recipe', item?.id || '', { choices: [{ value: '', label: 'Week only' }, ...arr(section('recipes')).map((recipe) => ({ value: recipe.id, label: recipe.title }))] }) + field('weekStart', 'Week of', state.weekStart, { type: 'date' }) + field('feedbackType', 'Feedback type', 'worked_well', { choices: ['worked_well', 'change_next_time', 'problem', 'preference'] }) + field('rating', 'Rating (1–5, optional)', '', { type: 'number', min: 1, max: 5 }) + field('note', 'What happened', '', { type: 'textarea', required: true, wide: true }) + field('nextTime', 'Change for next time', '', { type: 'textarea', wide: true }) + field('tags', 'Reusable tags, separated by commas', '', { wide: true }) + field('variantName', 'Preparation variant (optional)', '', { wide: true }) + field('adaptations', 'What changed — one per line', '', { type: 'textarea', wide: true });
  } else if (kind === 'memory') {
    title = item ? 'Review memory' : 'Add household memory';
    markup = field('content', 'What should be remembered?', item?.content, { type: 'textarea', required: true, wide: true }) + field('scope', 'Scope', item?.scope || 'persistent', { choices: ['persistent', 'this_week'] }) + (item ? field('action', 'Action', 'update', { choices: ['update', 'forget'] }) : '<p class="muted tiny">New memories are saved as suggestions until confirmed.</p>');
  }
  document.querySelector('#dialog-title').textContent = title;
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
    state.recipe = saved;
    state.view = 'recipes';
  } else if (kind === 'pantry') {
    await save('/api/pantry', 'PUT', { id: item?.id, name: value('name'), quantity: numberOrNull(value('quantity')), unit: value('unit') || null, storageLocation: value('storageLocation'), quantityConfidence: value('quantityConfidence'), useByDate: value('useByDate') || null });
  } else if (kind === 'meal') {
    if (monday(`${value('date')}T12:00:00`) !== state.weekStart) throw new Error('Choose a date in the selected week.');
    const existing = arr(state.plan?.entries);
    const key = item?.id || `${item?.day}:${item?.slot}`;
    const entries = item ? existing.filter((entry) => (entry.id || `${entry.day}:${entry.slot}`) !== key) : [...existing];
    entries.push({ date: value('date'), day: DAYS[(new Date(`${value('date')}T12:00:00`).getDay() + 6) % 7], slot: value('slot'), meal: value('meal'), servings: numberOrNull(value('servings')), recipeId: value('recipeId') || null, notes: value('notes') });
    await save('/api/meal-plan', 'PUT', { id: state.plan?.id, weekStart: state.weekStart, status: state.plan?.status || 'draft', entries });
  } else if (kind === 'shopping') {
    const list = section('shoppingList');
    const items = arr(list?.items).filter((entry) => entry.id !== item?.id);
    items.push({ ...item, id: item?.id || crypto.randomUUID(), name: value('name'), quantity: numberOrNull(value('quantity')), unit: value('unit') || null, store: value('store'), purchased: item?.purchased || false });
    await save('/api/shopping-list', 'PUT', { id: list?.id, name: value('listName') || 'Weekly groceries', status: list?.status || 'draft', mealPlanId: list?.mealPlanId, items });
  } else if (kind === 'schedule') {
    await save('/api/schedule', 'PUT', { weekStart: value('weekStart'), days: DAYS.map((day) => ({ day, mode: value(day) })), isNormalWeek: state.schedule?.is_normal_week ?? true, rememberRhythm: state.schedule?.remember_rhythm ?? true });
  } else if (kind === 'retro') {
    await save('/api/retros', 'PUT', { weekStart: value('weekStart'), workedWell: lines('workedWell'), stressors: lines('stressors'), outcomes: arr(section('retro')?.outcomes), note: value('note') });
  } else if (kind === 'feedback') {
    if (!value('recipeId') && !value('weekStart')) throw new Error('Choose a recipe or a week.');
    await save('/api/feedback', 'POST', { recipeId: value('recipeId') || null, weekStart: value('weekStart') || null, feedbackType: value('feedbackType'), note: value('note'), nextTime: value('nextTime'), tags: comma('tags'), rating: numberOrNull(value('rating')), variantName: value('variantName'), adaptations: lines('adaptations') });
  } else if (kind === 'memory') {
    if (item) await save(`/api/memories/${encodeURIComponent(item.id)}`, 'PATCH', { action: value('action'), content: value('content') });
    else await save('/api/memories', 'POST', { content: value('content'), scope: value('scope'), status: 'suggested' });
  }
  dialog.close();
  await refresh('Saved to your household.');
  if (kind === 'meal' || kind === 'schedule') await loadWeek(state.weekStart);
}

async function handleAction(actionName, id) {
  const recipes = arr(section('recipes'));
  const pantry = arr(section('pantry'));
  const shopping = arr(section('shoppingList')?.items);
  const plan = arr(state.plan?.entries);
  if (TITLES[actionName]) return view(actionName);
  if (actionName === 'add-recipe') return openEditor('recipe');
  if (actionName === 'edit-recipe') return openEditor('recipe', state.recipe || recipes.find((item) => item.id === id));
  if (actionName === 'open-recipe') {
    state.recipe = await api(`/api/recipes/${encodeURIComponent(id)}`);
    return render();
  }
  if (actionName === 'close-recipe') { state.recipe = null; return render(); }
  if (actionName === 'archive-recipe') {
    if (!confirm('Archive this recipe? It will leave the active recipe library.')) return;
    await api(`/api/recipes/${encodeURIComponent(id)}`, { method: 'DELETE' });
    state.recipe = null;
    return refresh('Recipe archived.');
  }
  if (actionName === 'add-pantry') return openEditor('pantry');
  if (actionName === 'edit-pantry') return openEditor('pantry', pantry.find((item) => item.id === id));
  if (actionName === 'add-meal') return openEditor('meal');
  if (actionName === 'edit-meal' || actionName === 'remove-meal') {
    const item = plan.find((entry) => (entry.id || `${entry.day}:${entry.slot}`) === id);
    if (!item) return;
    if (actionName === 'edit-meal') return openEditor('meal', item);
    if (!confirm(`Remove ${item.meal || item.title} from this plan?`)) return;
    await save('/api/meal-plan', 'PUT', { id: state.plan?.id, weekStart: state.weekStart, status: state.plan?.status || 'draft', entries: plan.filter((entry) => entry !== item) });
    await refresh('Meal removed.');
    return loadWeek(state.weekStart);
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
  if (actionName === 'edit-retro') return openEditor('retro');
  if (actionName === 'add-feedback') return openEditor('feedback', recipes.find((item) => item.id === id));
  if (actionName === 'add-memory') return openEditor('memory');
  if (actionName === 'edit-memory') return openEditor('memory', arr(section('memories')).find((item) => item.id === id));
  if (actionName === 'card-up' || actionName === 'card-down') {
    const saved = arr(household().planningPreferences?.dashboard?.cardOrder);
    const order = [...new Set(saved.filter((cardId) => CARD_IDS.includes(cardId)))];
    CARD_IDS.forEach((cardId) => { if (!order.includes(cardId)) order.push(cardId); });
    const index = order.indexOf(id);
    const other = index + (actionName === 'card-up' ? -1 : 1);
    if (index < 0 || other < 0 || other >= order.length) return;
    [order[index], order[other]] = [order[other], order[index]];
    await save('/api/dashboard-layout', 'PATCH', { cardOrder: order });
    return refresh('Dashboard order saved.');
  }
  if (actionName === 'confirm-memory') {
    await save(`/api/memories/${encodeURIComponent(id)}`, 'PATCH', { action: 'confirm' });
    return refresh('Memory confirmed.');
  }
  if (actionName === 'sign-out' && state.client) {
    await state.client.auth.signOut();
    location.assign('/login?next=%2F');
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
  finally { button.disabled = false; }
});

content.addEventListener('change', async (event) => {
  if (event.target.id === 'week-picker') {
    try { await loadWeek(event.target.value); }
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
  if (!search.trim()) return;
  state.searchTimer = setTimeout(async () => {
    try {
      const result = await api(`/api/recipes?query=${encodeURIComponent(search.trim())}&limit=25`);
      if (state.search !== search) return;
      state.recipeResults = result.items;
      render();
      const input = document.querySelector('#recipe-search');
      input?.focus();
      input?.setSelectionRange(start, start);
    } catch (error) { showToast(error.message); }
  }, 250);
});

content.addEventListener('submit', async (event) => {
  if (!['settings-form', 'dashboard-form'].includes(event.target.id)) return;
  event.preventDefault();
  const submit = event.target.querySelector('[type="submit"]');
  submit.disabled = true;
  try {
    const data = new FormData(event.target);
    if (event.target.id === 'settings-form') {
      const restrictionText = String(data.get('dietaryRestrictions') || '').trim();
      const stores = String(data.get('stores') || '').split(',').map((item) => item.trim()).filter(Boolean);
      if (!stores.length) throw new Error('Enter at least one preferred store.');
      const prefs = household().planningPreferences || {};
      await save('/api/household', 'PATCH', { householdSize: Number(data.get('householdSize')), dietaryRestrictions: /^(none|no restrictions)$/i.test(restrictionText) ? [] : restrictionText.split(',').map((item) => item.trim()).filter(Boolean), storePriority: stores.map((store, index) => ({ store, priority: index + 1 })), planningPreferences: { ...prefs, weeknightMaxMinutes: Number(data.get('weeknightMaxMinutes')), leftoversForLunch: data.has('leftoversForLunch'), focusAreas: data.getAll('focusAreas') }, completeOnboarding: true });
    } else {
      const visible = data.getAll('visibleCard');
      await save('/api/dashboard-layout', 'PATCH', { hiddenCards: CARD_IDS.filter((id) => !visible.includes(id)) });
    }
    await refresh('Settings saved.');
  } catch (error) { showToast(error.message); }
  finally { submit.disabled = false; }
});

form.addEventListener('submit', async (event) => {
  const submitter = event.submitter;
  if (submitter?.value === 'cancel') return;
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

async function start() {
  state.config = await fetch('/api/auth/config').then((response) => response.json());
  if (state.config.supabaseUrl && state.config.supabaseAnonKey) {
    if (!window.supabase?.createClient) throw new Error('Sign in is unavailable. Check your connection and reload.');
    state.client = window.supabase.createClient(state.config.supabaseUrl, state.config.supabaseAnonKey);
    const { data, error } = await state.client.auth.getSession();
    if (error || !data.session) { location.replace('/login?next=%2F'); return; }
    state.session = data.session;
    const email = data.session.user?.email || 'Account';
    document.querySelector('#account-label').textContent = email;
    document.querySelector('#account-avatar').textContent = email.slice(0, 2).toUpperCase();
  } else {
    document.querySelector('#mode-badge').hidden = false;
    document.querySelector('#account-label').textContent = 'Local demo';
  }
  await refresh();
  if (household().onboardingComplete === false) view('settings');
}

start().catch((error) => {
  content.innerHTML = empty('Could not open Meal Prep', error.message || 'Please reload and try again.');
});
