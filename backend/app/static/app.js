const content = document.querySelector('#app-content');
const dialog = document.querySelector('#editor-dialog');
const plannedMealDialog = document.querySelector('#planned-meal-dialog');
const form = document.querySelector('#editor-form');
const fields = document.querySelector('#dialog-fields');
const errorBox = document.querySelector('#dialog-error');
const toastBox = document.querySelector('#toast');
const shell = document.querySelector('.shell');
const sidebarToggle = document.querySelector('#sidebar-toggle');
const accountMenu = document.querySelector('#account-menu');
const mobileMenu = document.querySelector('#mobile-menu-dialog');
const mobileMore = document.querySelector('#mobile-more');

mobileMore.addEventListener('click', () => {
  mobileMenu.showModal();
  mobileMore.setAttribute('aria-expanded', 'true');
});
document.querySelector('#mobile-menu-close').addEventListener('click', () => mobileMenu.close());
mobileMenu.addEventListener('close', () => {
  mobileMore.setAttribute('aria-expanded', 'false');
  if (window.matchMedia('(max-width: 780px)').matches) mobileMore.focus({ preventScroll: true });
});
mobileMenu.addEventListener('click', (event) => {
  if (event.target !== mobileMenu) return;
  const bounds = mobileMenu.getBoundingClientRect();
  if (event.clientX < bounds.left || event.clientX > bounds.right || event.clientY < bounds.top || event.clientY > bounds.bottom) mobileMenu.close();
});
window.matchMedia('(min-width: 781px)').addEventListener('change', (event) => {
  if (event.matches && mobileMenu.open) mobileMenu.close();
});

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
function mealSlots() { return household().mealSlots || []; }
function slotName(entry) { return mealSlots().find((slot) => slot.id === entry.slot)?.name || entry.slotName || entry.slot; }
function slotOrder(entry) { const i = mealSlots().findIndex((slot) => slot.id === entry.slot); return i < 0 ? 99 : i; }
function planPayload(changes = {}) { return { ...state.plan, weekStart: state.weekStart, entries: arr(state.plan?.entries), tasks: arr(state.plan?.tasks), ...changes }; }

function componentSummary(entry, clickable = true) {
  return arr(entry.components).map((item) => `<li>${item.recipeId && clickable ? `<button type="button" class="text-button" data-action="open-recipe" data-id="${esc(item.recipeId)}">${esc(item.name)}</button>` : esc(item.name)}${item.quantity !== null && item.quantity !== undefined ? ` · ${esc(item.quantity)} ${esc(item.unit)}` : ''}${item.taskId ? ` · ${esc(arr(state.plan?.tasks).find((task) => task.id === item.taskId)?.title || 'Prepared task')}` : ''}</li>`).join('');
}

function plannedFoodsLabel(components) {
  const names = arr(components).map(part => part.name).filter(Boolean);
  const joined = names.join(' + ');
  return joined.length <= 180 ? joined : `${names[0].slice(0, 155)} + ${names.length - 1} more`;
}

function plannedMealHeading(entry) {
  const parts = arr(entry.components);
  return parts.length > 1 && entry.meal === plannedFoodsLabel(parts) ? `${parts.length} foods together` : entry.meal;
}

function mealMarkup(entry) {
  const linked = arr(entry.components).map(item => ({...item, recipeId: item.recipeId || arr(state.plan?.tasks || section('mealPlan')?.tasks).find(task => task.id === item.taskId)?.recipeId}));
  const recipes = [...new Set(linked.map(item => item.recipeId).filter(Boolean))];
  const recipeLink = (id, title) => `<a class="planned-recipe-link" href="/app?view=recipes&recipe=${encodeURIComponent(id)}" data-action="open-recipe" data-id="${esc(id)}">${esc(title)}</a>`;
  const heading = plannedMealHeading(entry);
  const savedSource = entry.sourceMeal && entry.meal === entry.sourceMeal.name;
  const title = !savedSource && recipes.length === 1 && linked.length === 1 ? recipeLink(recipes[0], linked[0].name) : `<span class="planned-meal-label">${esc(savedSource ? `Saved meal · ${entry.sourceMeal.name}` : heading)}</span>`;
  const parts = !savedSource && linked.length === 1 && recipes.length === 1 ? [] : linked;
  return `<div class="meal ${entry.completedAt ? 'completed' : ''}" data-meal-id="${esc(entry.id)}"><small>${esc(slotName(entry))}${entry.completedAt ? ' · Eaten' : ''}</small><strong>${title}</strong>${parts.length ? `<ul class="meal-components">${parts.map(item => `<li>${item.recipeId ? recipeLink(item.recipeId, item.name) : esc(item.name)}${item.quantity != null ? ` · ${esc(item.quantity)} ${esc(item.unit)}` : ''}</li>`).join('')}</ul>` : ''}${MealNutrition.renderDetails(entry.nutrition)}<div class="meal-actions">${action('Meal details', 'open-planned-meal', entry.id)}${entry.completedAt ? '' : action('Edit', 'edit-meal', entry.id)}</div></div>`;
}

function openPlannedMeal(entry) {
  const tasks = new Map(arr(state.plan?.tasks).map((task) => [task.id, task]));
  const components = arr(entry.components);
  const savedSource = entry.sourceMeal && entry.meal === entry.sourceMeal.name;
  const hasRecipe = components.some((part) => part.recipeId || tasks.get(part.taskId)?.recipeId);
  const rows = components.map((part) => {
    const task = tasks.get(part.taskId);
    const recipeId = part.recipeId || task?.recipeId;
    const snapshot = part.recipeSnapshot || task?.recipeSnapshot;
    const amount = part.quantity == null ? '' : ` · ${esc(part.quantity)} ${esc(part.unit || '')}`;
    return `<li><span>${esc(part.name)}${amount}</span>${recipeId ? `<button type="button" class="text-button" data-action="open-recipe" data-id="${esc(recipeId)}">Open ${esc(snapshot?.kind === 'ready_food' ? 'ready food' : 'recipe')}: ${esc(snapshot?.title || part.name)}</button>` : ''}</li>`;
  }).join('');
  const reuse = components.length > 1 ? savedSource
    ? `<p>This combination is already saved in your meal library as ${esc(entry.sourceMeal.name)}. This week uses its own copy.</p>`
    : action('Save as reusable meal', 'save-as-meal', entry.id) : '';
  document.querySelector('#planned-meal-title').textContent = plannedMealHeading(entry);
  document.querySelector('#planned-meal-body').innerHTML = `<p class="muted tiny">${esc(entry.date)} · ${esc(slotName(entry))}${entry.servings ? ` · ${esc(entry.servings)} servings` : ''}${entry.completedAt ? ' · Eaten' : ''}</p>${entry.notes ? `<p>${esc(entry.notes)}</p>` : ''}<section class="planned-meal-components"><h3>What’s in this meal</h3>${rows ? `<ul>${rows}</ul>` : '<p>No recipe or ready food is linked to this planned meal. Edit it to choose one.</p>'}${hasRecipe ? '' : `<p class="muted tiny">A meal name alone does not identify a recipe.</p>${action('Search recipes for this meal', 'search-planned-recipe', entry.id)}`}</section>${savedSource ? `<p class="muted tiny">Planned from saved meal: ${esc(entry.sourceMeal.name)}</p>` : ''}<div class="planned-meal-reuse">${reuse}${entry.completedAt ? '' : action('Edit planned meal', 'edit-meal', entry.id)}</div>`;
  plannedMealDialog.showModal();
  plannedMealDialog.querySelector('[aria-label="Close meal details"]').focus();
}

function taskMarkup(task) {
  return `<div class="plan-task ${task.completedAt ? 'completed' : ''}" data-task-id="${esc(task.id)}"><label class="check-row"><input type="checkbox" data-complete-task="${esc(task.id)}" aria-label="Complete ${esc(task.title)}" ${task.completedAt ? 'checked disabled' : ''} /><strong>${esc(task.title)}</strong></label>${task.notes ? `<p class="tiny">${esc(task.notes)}</p>` : ''}${task.mealIds?.length ? `<p class="tiny">For: ${task.mealIds.map((id) => esc(arr(state.plan?.entries).find((meal) => meal.id === id)?.meal || 'Meal')).join(', ')}</p>` : ''}${task.completedAt ? '<small>Completed</small>' : `<div class="meal-actions">${action('Edit task', 'edit-task', task.id)}${action('Remove task', 'remove-task', task.id)}${task.recipeId ? action('Record cooking', 'cook-task', task.id) : ''}</div>`}</div>`;
}
const FOCUS = ['breakfasts', 'lunches', 'snacks', 'dinners', 'weekend-prep', 'pantry', 'shopping'];
const PANTRY_CATEGORIES = [['all', 'All items'], ['fruits', 'Fruits'], ['vegetables', 'Vegetables'], ['snacks', 'Snacks'], ['frozen', 'Frozen'], ['dry_goods', 'Dry goods'], ['condiments', 'Condiments'], ['uncategorized', 'Uncategorized']];
const CARD_IDS = ['food-rules', 'planning-defaults', 'stores', 'schedule', 'meal-plan', 'shopping-list', 'pantry', 'recipes', 'feedback', 'memories'];
const CARD_NAMES = {
  'food-rules': 'Food rules', 'planning-defaults': 'Planning defaults', stores: 'Preferred stores',
  schedule: 'Weekly rhythm', 'meal-plan': 'Meal plan', 'shopping-list': 'Shopping list',
  pantry: 'Pantry', recipes: 'Recipes', feedback: 'Meal feedback', memories: 'Household memory',
};
const TITLES = { overview: 'Overview', plan: 'Weekly plan', recipes: 'Recipes', pantry: 'Pantry', shopping: 'Shopping', reviews: 'Reviews', circles: 'Chats', settings: 'Settings', notifications: 'Notifications' };
let recipeBrowser = null;
let circleMentionInstances = [];
const state = { browserUi: {}, view: 'overview', snapshot: null, access: null, households: [], activeHouseholdId: null, pendingInvites: [], notifications: [], notificationError: false, plan: null, schedule: null, mealPlanRules: null, ruleHistory: null, planTab: 'plan', ruleRevisionId: null, rulePreview: null, weekStart: null, recipe: null, recipeResults: null, recipeTags: null, tagSuggestionQuery: '', recipeShares: [], recipeSharesUnavailable: false, shareUrl: null, shareId: null, recipeShareReview: null, circles: [], circleId: null, circleFeed: [], circleNextOffset: null, circleDetail: null, circleComposer: null, circleReview: null, directShares: [], publicShares: [], circleHub: 'home', directReview: null, circleFoodReview: null, circleSearch: '', circleMentions: [], search: '', recipeTag: '', mealRecipes: [], pantrySearch: '', pantryCategory: 'all', pantryStock: 'on-hand', pantryReview: false, pantryQuantityId: null, pantrySection: 'items', pantryPhotos: [], pantryPhotosHasMore: false, pantryPhotosLoading: false, pantryPhotosError: null, pantryPhotosRequest: 0, client: null, session: null, config: null, editor: null };
const VIEW_SECTIONS = { overview: ['mealPlan', 'shoppingList', 'pantry'], plan: ['mealPlan', 'schedule'], recipes: ['recipes'], pantry: ['pantry'], shopping: ['shoppingList'], reviews: ['feedback', 'memories'], circles: [], settings: [], notifications: [] };
const SECTION_NAMES = { mealPlan: 'meals and prep', shoppingList: 'shopping list', pantry: 'pantry', schedule: 'weekly rhythm', mealPlanRules: 'meal preferences', recipes: 'recipes', meals: 'saved meals', feedback: 'reviews', memories: 'household memory' };
Object.assign(state, { dataGeneration: 0, sectionRequests: new Map(), sectionWeeks: {}, dashboardExpanded: false, todayMode: 'meals', notificationsLoading: true, notificationsArchived: false, archivedNotifications: [], circleLoadRequest: 0, circlePanel: null, circleFeeds: new Map(), circleDrafts: new Map(), circlePending: new Map(), circleFeedLoading: false, circleFoodSearches: new Map(), circleListRequest: 0, chatProfile: null, chatSearch: '', chatResults: null, chatReply: null, chatEdit: null, chatPicker: [], chatPickerStatus: 'idle', chatPickerQuery: '', chatPickerRequest: 0, chatInlineError: null });
function routeFromUrl() {
  const params = new URLSearchParams(location.search);
  const requestedView = params.get('view');
  const view = Object.hasOwn(TITLES, requestedView) ? requestedView : 'overview';
  const week = params.get('week');
  const validWeek = week && /^\d{4}-\d{2}-\d{2}$/.test(week) && !Number.isNaN(Date.parse(`${week}T12:00:00`));
  return {
    view,
    weekStart: (view === 'plan' || view === 'recipes') && validWeek ? week : null,
    planTab: view === 'plan' && ['rules', 'tasks'].includes(params.get('tab')) ? params.get('tab') : 'plan',
    ruleRevisionId: view === 'plan' && params.get('tab') === 'rules' ? params.get('revision') : null,
    recipeId: view === 'recipes' ? params.get('recipe') : null,
    circleId: view === 'circles' ? params.get('circle') : null,
    circleShareId: view === 'circles' ? params.get('share') : null,
    circleHub: view === 'circles' && ['world', 'activity'].includes(params.get('space')) ? params.get('space') : 'home',
    browserUi: {itemType: ['recipes','ready_food','meals'].includes(params.get('type')) ? params.get('type') : params.get('library') === 'meals' ? 'meals' : 'all', query: params.get('query') || '', filters: Object.fromEntries(['cuisine','goal','meal','diet','tag'].map(key => [key, params.getAll(key)]).filter(([,values]) => values.length)), maxMinutes: Number(params.get('max_minutes')) || null, exploreOpen: false},
    pantrySection: view === 'pantry' && params.get('section') === 'photos' ? 'photos' : 'items',
  };
}

function writeRoute(mode = 'push') {
  const url = new URL(location.href);
  ['view', 'week', 'recipe', 'circle', 'share', 'space', 'tab', 'revision', 'section', 'mode', 'library', 'type', 'query', 'cuisine', 'goal', 'meal', 'diet', 'tag', 'max_minutes'].forEach((key) => url.searchParams.delete(key));
  if (state.view !== 'overview') url.searchParams.set('view', state.view);
  if ((state.view === 'plan' || state.view === 'recipes') && state.weekStart) url.searchParams.set('week', state.weekStart);
  if (state.view === 'recipes') {
    if (state.browserUi.itemType && state.browserUi.itemType !== 'all') url.searchParams.set('type', state.browserUi.itemType);
    if (state.browserUi.query) url.searchParams.set('query', state.browserUi.query);
    for (const [kind, values] of Object.entries(state.browserUi.filters || {})) values.forEach(value => url.searchParams.append(kind, value));
    if (state.browserUi.maxMinutes) url.searchParams.set('max_minutes', state.browserUi.maxMinutes);
  }
  if (state.view === 'plan' && state.planTab !== 'plan') {
    url.searchParams.set('tab', state.planTab);
    if (state.ruleRevisionId) url.searchParams.set('revision', state.ruleRevisionId);
  }
  if (state.view === 'recipes' && state.recipe?.id) url.searchParams.set('recipe', state.recipe.id);
  if (state.view === 'circles') {
    if (state.circleId) url.searchParams.set('circle', state.circleId);
    if (state.circleShareId) url.searchParams.set('share', state.circleShareId);
    if (['world', 'activity'].includes(state.circleHub)) url.searchParams.set('space', state.circleHub);
  }
  if (state.view === 'pantry' && state.pantrySection === 'photos') url.searchParams.set('section', 'photos');
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
  const response = await fetch(path, { signal: AbortSignal.timeout(30000), ...options, headers });
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
  state.recipeShareReview = null;
  try { state.recipeShares = (await api('/api/recipe-shares')).items; state.recipeSharesUnavailable = false; }
  catch { state.recipeShares = []; state.recipeSharesUnavailable = true; }
  state.shareUrl = null;
  state.shareId = null;
}

async function refresh(message) {
  const generation = ++state.dataGeneration;
  state.sectionRequests.clear();
  state.circleFeeds.clear();
  state.circleFoodSearches.clear(); state.circleFoodRoomId = null; state.circlePeopleRequest = null;
  state.sectionWeeks = {};
  const previousHouseholdId = state.activeHouseholdId;
  // Notifications update independently and never hold the kitchen screen open.
  loadNotifications(generation);
  const data = await api('/api/app/bootstrap?include_sections=false');
  if (generation !== state.dataGeneration) return;
  state.pendingInvites = arr(data.pendingInvites);
  if (data.needsInvitationReview) {
    location.replace('/invite');
    return;
  }
  state.snapshot = data.snapshot;
  if (state.client) {
    state.access = data.access;
    state.households = arr(data.memberships?.households);
    const nextHouseholdId = data.memberships?.activeHouseholdId || null;
    if (state.activeHouseholdId && state.activeHouseholdId !== nextHouseholdId) {
      recipeBrowser?.destroy(); recipeBrowser = null;
      state.browserUi = {}; state.recipe = null;
    }
    state.activeHouseholdId = nextHouseholdId;
    const activeHousehold = state.households.find(item => item.id === state.activeHouseholdId);
    document.querySelector('#account-label').textContent = activeHousehold?.name || 'Account';
    document.querySelector('#account-button').dataset.household = 'true';
    document.querySelector('#account-button').title = `Account options · ${activeHousehold?.name || 'Choose household'}`;
  }
  if (previousHouseholdId !== state.activeHouseholdId) {
    state.mealRecipes = [];
    state.circleDrafts.clear(); state.circlePending.clear();
    state.circleFeed = []; state.circleDetail = null;
    state.pantryPhotosRequest += 1;
    state.pantryPhotos = [];
    state.pantryPhotosHasMore = false;
    state.pantryPhotosLoading = false;
    state.pantryPhotosError = null;
  }
  state.plan = section('mealPlan');
  state.schedule = section('schedule');
  state.mealPlanRules = section('mealPlanRules');
  state.ruleHistory = null;
  if (!state.weekStart) state.weekStart = monday();
  const profileRequest=state.chatProfileRequest=(state.chatProfileRequest||0)+1;
  api('/api/chat-profile').then(profile=>{if(profileRequest!==state.chatProfileRequest||generation!==state.dataGeneration)return;state.chatProfile=profile;const field=document.querySelector('#chat-profile-name');if(field&&!field.dataset.dirty)field.value=profile.name;}).catch(()=>{});
  if (household().onboardingComplete === false && !state.pendingInvites.length) {
    view('settings', 'replace');
    return;
  }
  render();
  await Promise.all([loadViewData(), ...(state.view === 'plan' && state.ruleRevisionId ? [loadRulePreview(state.ruleRevisionId)] : [])]);
  render();
  if (state.view === 'pantry' && state.pantrySection === 'photos') await loadPantryPhotos();
  if (message) showToast(message);
}

async function loadNotifications(generation) {
  state.notificationsLoading = true;
  try {
    const [data, archive] = await Promise.all([api('/api/notifications'), state.notificationsArchived ? api('/api/notifications?archived=true') : Promise.resolve(null)]);
    if (generation !== state.dataGeneration) return;
    state.notifications = arr(data.items);
    if (archive) state.archivedNotifications = arr(archive.items);
    state.notificationError = false;
  } catch {
    if (generation !== state.dataGeneration) return;
    state.notificationError = true;
  }
  if (generation !== state.dataGeneration) return;
  state.notificationsLoading = false;
  updateNotificationCount();
  if (state.view === 'notifications') render();
}

function viewSections() {
  const names = [...(VIEW_SECTIONS[state.view] || [])];
  if (state.view === 'plan' && !state.ruleRevisionId) names.push('mealPlanRules');
  if (state.view === 'overview' && state.dashboardExpanded) names.push('schedule', 'recipes', 'feedback', 'memories');
  return names;
}

async function loadSection(name, force = false) {
  if (!state.snapshot) return;
  const generation = state.dataGeneration;
  const week = ['mealPlan', 'schedule'].includes(name) ? (state.view === 'overview' ? monday() : state.weekStart || monday()) : null;
  const key = `${name}:${week || ''}`;
  if (state.sectionRequests.has(key)) {
    if (state.sectionWeeks[name] !== week) state.snapshot.sections[name] = { status: 'loading', value: null };
    state.sectionWeeks[name] = week;
    return state.sectionRequests.get(key);
  }
  if (!force && sectionStatus(name) && sectionStatus(name) !== 'loading' && state.sectionWeeks[name] === week) return;
  state.snapshot.sections[name] = { status: 'loading', value: null };
  state.sectionWeeks[name] = week;
  const params = new URLSearchParams({ sections: name });
  if (week) params.set('week_start', week);
  const request = (async () => {
    let result;
    try {
      const data = await api(`/api/app/snapshot?${params}`);
      // The active household can also change through MCP or another browser tab.
      if (data.household?.householdId !== household().householdId) throw new Error('Household changed. Refresh to continue.');
      result = data.sections[name];
      if (!result) throw new Error('Section missing from response.');
    } catch {
      result = { status: 'unavailable', value: null };
    }
    if (generation !== state.dataGeneration) return;
    state.sectionRequests.delete(key);
    if (state.sectionWeeks[name] !== week) return;
    state.snapshot.sections[name] = result;
    if (name === 'mealPlan') state.plan = result.value;
    if (name === 'schedule') state.schedule = result.value;
    if (name === 'mealPlanRules') state.mealPlanRules = result.value;
    if (viewSections().includes(name)) render();
  })();
  state.sectionRequests.set(key, request);
  return request;
}

async function loadViewData(force = false) {
  if (state.view === 'circles') {
    render();
    await loadCircleData();
    return;
  }
  const tasks = viewSections().map((name) => loadSection(name, force));
  render();
  await Promise.all(tasks);
}

function updateNotificationCount() {
  const count = state.notifications.filter((item) => !item.read_at && !item.archived_at).length;
  const badge = document.querySelector('#notification-count');
  badge.hidden = count === 0;
  badge.textContent = count > 99 ? '99+' : String(count);
  document.querySelector('#notifications-button').setAttribute('aria-label', count ? `Notifications, ${count} unread` : 'Notifications');
}

async function loadWeek(weekStart) {
  const selectedWeek = monday(`${weekStart}T12:00:00`);
  state.weekStart = selectedWeek;
  await loadViewData();
}

async function loadRulePreview(revisionId) {
  state.rulePreview = null;
  state.rulePreviewError = null;
  const householdId = state.activeHouseholdId;
  try {
    const result = await api(`/api/meal-plan-rules?revision_id=${encodeURIComponent(revisionId)}`);
    if (state.ruleRevisionId === revisionId && state.activeHouseholdId === householdId) state.rulePreview = result.rules;
  } catch (error) {
    if (state.ruleRevisionId === revisionId && state.activeHouseholdId === householdId) state.rulePreviewError = error.message;
  }
}

async function openPlanTab(tab, revisionId = null) {
  state.planTab = tab;
  state.ruleRevisionId = tab === 'rules' ? revisionId : null;
  state.rulePreview = null;
  state.rulePreviewError = null;
  writeRoute();
  render();
  content.querySelector(`#planning-tab-${tab}`)?.focus({ preventScroll: true });
  await Promise.all([loadViewData(), ...(state.ruleRevisionId ? [loadRulePreview(state.ruleRevisionId)] : [])]);
  render();
  content.querySelector(`#planning-tab-${state.planTab}`)?.focus({ preventScroll: true });
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

function sectionContent(name, body) {
  const status = sectionStatus(name);
  if (!status || status === 'loading') return `<div class="section-loading" role="status"><span class="loader"></span>Loading ${esc(SECTION_NAMES[name])}…</div>`;
  if (status === 'unavailable') return `<div class="section-error"><p>Could not load ${esc(SECTION_NAMES[name])}.</p>${action('Try again', 'retry-section', name)}</div>`;
  return body;
}

function renderToday() {
  const today = dateForDay(monday(), (new Date().getDay() + 6) % 7);
  const dayName = DAYS[(new Date().getDay() + 6) % 7];
  const plan = section('mealPlan');
  const meals = arr(plan?.entries).filter((entry) => entry.date === today || (!entry.date && entry.day === dayName))
    .sort((a, b) => slotOrder(a) - slotOrder(b));
  const todayTasks = arr(plan?.tasks).filter((task) => task.date === today);
  const groceries = arr(section('shoppingList')?.items).filter((item) => !item.purchased);
  const soonDate = dateForDay(today, 3);
  const useSoon = arr(section('pantry')).filter((item) => {
    const date = pick(item, 'use_by_date', 'useByDate');
    return ((date && date <= soonDate) || item.freshness?.status === 'review_age') && (item.quantity === null || item.quantity === undefined || Number(item.quantity) > 0);
  }).sort((a, b) => String(pick(a, 'use_by_date', 'useByDate')).localeCompare(String(pick(b, 'use_by_date', 'useByDate'))));
  const mealBody = `<div class="today-meals">${state.todayMode === 'tasks' ? todayTasks.map(taskMarkup).join('') || '<p class="muted">No tasks planned for today.</p>' : meals.length ? meals.map(mealMarkup).join('') : '<p class="muted">No meals planned for today.</p>'}</div>`;
  const mealReady = ['ready', 'empty'].includes(sectionStatus('mealPlan'));
  const todayTasksVisible = state.todayMode === 'tasks';
  const toggle = `<div class="nutrition-toggle" role="group" aria-label="Today’s view">${['meals','tasks'].map(mode => `<button type="button" data-action="today-mode" data-id="${mode}" aria-pressed="${mode === (todayTasksVisible ? 'tasks' : 'meals')}">${mode === 'meals' ? 'Meals' : 'Tasks'}</button>`).join('')}</div>`;
  const shoppingBody = groceries.length ? `<p class="muted tiny">${groceries.length} ${groceries.length === 1 ? 'item' : 'items'} left to pick up</p><div class="stack">${groceries.slice(0, 5).map((item) => `<label class="check-row"><input type="checkbox" data-purchase-id="${esc(item.id)}" aria-label="Mark ${esc(item.name)} purchased" /><span class="row-copy"><strong>${esc(item.name)}</strong><small>${esc(item.quantity ?? '')} ${esc(item.unit || '')}${item.store ? ` · ${esc(item.store)}` : ''}</small></span></label>`).join('')}</div>` : '<p class="muted">Nothing left on your shopping list.</p>';
  const pantryBody = useSoon.length ? `<p class="muted tiny">Recorded dates coming up, and produce purchased at least 7 days ago.</p><div class="stack">${useSoon.slice(0, 5).map((item) => {
    const date = pick(item, 'use_by_date', 'useByDate');
    return row(item.name, `${!date ? `Review first · purchased ${item.freshness.ageDays} days ago` : date < today ? 'Past recorded date' : date === today ? 'Use-by today' : `Use-by ${date}`} · ${item.quantity ?? 'Amount unknown'} ${item.unit || ''}`, action('Review', 'edit-pantry', item.id));
  }).join('')}</div>` : '<p class="muted">No recorded dates or produce ages need review today. Open Pantry to check missing dates.</p>';
  return `<section class="today-heading"><div><p class="eyebrow">${esc(household().householdName || 'Your kitchen')} · ${esc(new Date(`${today}T12:00:00`).toLocaleDateString(undefined, { weekday: 'long', month: 'short', day: 'numeric' }))}</p><h2>What’s on today?</h2></div>${action('Open weekly plan', 'plan', '', 'primary')}</section>
    <article class="card today-plan" data-home-section="mealPlan"><div class="card-head"><h3>${todayTasksVisible ? 'Today’s tasks' : 'Today’s meals'}</h3>${mealReady ? `<div>${toggle}${state.todayMode === 'tasks' ? action('Add a task for today', 'add-task', today) : action('Add a meal for today', 'add-meal', today)}</div>` : ''}</div>${sectionContent('mealPlan', mealBody)}</article>
    <div class="home-attention-grid"><article class="card" data-home-section="shoppingList"><div class="card-head"><h3>Still to shop</h3>${action('Open list', 'shopping')}</div>${sectionContent('shoppingList', shoppingBody)}</article><article class="card" data-home-section="pantry"><div class="card-head"><h3>Use soon</h3>${action('View pantry', 'pantry')}</div>${sectionContent('pantry', pantryBody)}</article></div>
    <div class="home-shortcuts">${action('Browse recipes', 'recipes')}${action('View reviews', 'reviews')}${action('Customize dashboard', 'settings')}</div>`;
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
  let html = incomplete ? `<div class="callout"><b>Set up your kitchen.</b><p>Add your household’s food rules and weekly preferences to get started.</p>${action('Set up household', 'settings')}</div>` : renderToday();
  if (state.pendingInvites.length) html = `<div class="callout"><b>Household invitation waiting</b><p>You have an invitation to join ${esc(state.pendingInvites[0].householdName)}.</p>${action('Review invitation', 'review-invite')}</div>` + html;
  html += `<details id="household-dashboard" class="household-dashboard" ${state.dashboardExpanded ? 'open' : ''}><summary>More from your household <span>Saved preferences, recipes & notes</span></summary>`;
  if (!state.dashboardExpanded) return html + '</details>';
  const cards = {
    'food-rules': card('Food rules', '♡', h.dietaryRestrictions === null || h.dietaryRestrictions === undefined ? '<p class="muted tiny">No food rules recorded yet.</p>' : arr(h.dietaryRestrictions).length ? tags(h.dietaryRestrictions, 'orange') : '<p class="muted tiny">No dietary restrictions recorded.</p>'),
    'planning-defaults': card('Planning defaults', '⌁', `<div class="stack">${row('Household size', h.householdSize ? `${h.householdSize} people` : 'Not set')}${row('Weeknight cooking', prefs.weeknightMaxMinutes ? `${prefs.weeknightMaxMinutes} minutes maximum` : 'Not set')}${row('Lunch leftovers', prefs.leftoversForLunch === undefined ? 'Not set' : prefs.leftoversForLunch ? 'Yes' : 'No')}</div>`),
    stores: card('Preferred stores', '◇', arr(h.storePriority).length ? `<div class="stack">${arr(h.storePriority).sort((a, b) => a.priority - b.priority).map((store) => row(store.store, `Priority ${store.priority}`)).join('')}</div>` : '<p class="muted tiny">No stores recorded yet.</p>'),
    schedule: card('Weekly rhythm', '◷', state.schedule ? `<div class="stack">${arr(state.schedule.days).slice(0, 3).map((day) => row(day.day, label(day.mode || 'Flexible'))).join('')}</div>` : '<p class="muted tiny">No weekly schedule saved.</p>', `<div style="margin-top:20px">${action('Open plan', 'plan')}</div>`),
    'meal-plan': card('Weekly plan', '▦', `<div class="metric">${arr(plan?.entries).length}</div><p class="muted tiny">meals · ${arr(plan?.tasks).length} tasks</p>`, `<div style="margin-top:20px">${action('View plan', 'plan')}</div>`),
    'shopping-list': card('Shopping', '✓', `<div class="metric">${pending}</div><p class="muted tiny">items left to pick up</p>`, `<div style="margin-top:20px">${action('Open list', 'shopping')}</div>`),
    pantry: card('Pantry', '□', `<div class="metric">${pantry.length}</div><p class="muted tiny">${pantry.length === 1 ? 'item' : 'items'} on hand</p>`, `<div style="margin-top:20px">${action('View pantry', 'pantry')}</div>`),
    recipes: card('Recent recipes', '◇', recipes.length ? `<div class="stack">${recipes.slice(0, 3).map((recipe) => row(recipe.title, `${recipe.total_minutes || '—'} min · ${recipe.servings || '—'} servings`)).join('')}</div>` : '<p class="muted tiny">No recipes saved yet.</p>', `<div style="margin-top:20px">${action('Browse recipes', 'recipes')}</div>`),
    feedback: card('Meal feedback', '♡', sectionStatus('feedback') === 'unavailable' ? '<p class="muted tiny">Cooking notes are temporarily unavailable.</p>' : arr(section('feedback')).length ? `<div class="stack">${arr(section('feedback')).slice(0, 2).map((item) => row(item.occurrence?.title || 'Weekly note', item.note)).join('')}</div>` : '<p class="muted tiny">No meal feedback yet.</p>', `<div style="margin-top:20px">${action('View reviews', 'reviews')}</div>`),
    memories: card('Household memory', '✦', memories.length ? `<div class="stack">${memories.slice(0, 2).map((item) => row(item.content, label(item.status))).join('')}</div>` : '<p class="muted tiny">No saved memories yet.</p>', `<div style="margin-top:20px">${action('View memory', 'reviews')}</div>`),
  };
  const layout = dashboardLayout();
  const visible = layout.order.filter((id) => !layout.hidden.includes(id));
  const cardSections = { schedule: 'schedule', 'meal-plan': 'mealPlan', 'shopping-list': 'shoppingList', pantry: 'pantry', recipes: 'recipes', feedback: 'feedback', memories: 'memories' };
  html += visible.length ? `<div class="card-grid dashboard-grid">${visible.map((id) => {
    const name = cardSections[id];
    const body = name && (!sectionStatus(name) || ['loading', 'unavailable'].includes(sectionStatus(name))) ? card(CARD_NAMES[id], '·', sectionContent(name, '')) : cards[id];
    return `<div data-dashboard-card="${id}">${body}</div>`;
  }).join('')}</div>` : empty('No dashboard cards shown', 'Open Settings to choose which cards to show.');
  return html + '</details>';
}

function renderNotifications() {
  if (state.notificationsLoading) return '<div class="section-loading" role="status">Loading notifications…</div>';
  if (state.notificationError) return empty('Notifications unavailable', 'Refresh the page to try again.');
  const items = state.notificationsArchived ? state.archivedNotifications : state.notifications;
  return `<section class="page-heading"><div><p class="eyebrow">Household and circle activity</p><h2>Your notifications</h2></div></section>
    <div class="actions" style="margin-bottom:16px">${action(state.notificationsArchived ? 'Back to inbox' : 'View archive', 'toggle-notification-archive')}</div>
    ${!items.length ? empty(state.notificationsArchived ? 'Archive is empty' : 'All caught up', 'Household and circle activity will appear here.') : `<div class="stack">${items.map((item) => `<article class="card notification-item ${item.read_at ? '' : 'unread'}">
      <div class="card-head"><h3>${esc(item.title)}</h3><span class="notification-new">${item.read_at ? 'Read' : 'Unread'}</span></div>
      <p class="muted tiny">${esc(new Date(item.created_at).toLocaleString())}</p>
      <div class="actions" style="margin-top:14px">${action('Open', 'open-notification', item.id)}${action(item.read_at ? 'Mark unread' : 'Mark read', 'toggle-notification-read', item.id)}${action(state.notificationsArchived ? 'Restore to inbox' : 'Archive', 'archive-notification', item.id)}</div>
    </article>`).join('')}</div>`}`;
}

function cacheCircleFeed(circleId, feed) {
  state.circleFeeds.delete(circleId);
  state.circleFeeds.set(circleId, feed);
  while (state.circleFeeds.size > 10) state.circleFeeds.delete(state.circleFeeds.keys().next().value);
}

async function loadCircleComposerData(roomId, force = false) {
  if (!force && state.circleFoodRoomId === roomId) return state.circlePeopleRequest?.catch(() => {});
  const generation = state.dataGeneration;
  state.circleFoodRoomId = roomId;
  state.circleMentions = [];
  const request = api(`/api/circles/${encodeURIComponent(roomId)}/mention-candidates`);
  state.circlePeopleRequest = request;
  try {
    const mentions = await request;
    if (generation === state.dataGeneration && state.circleFoodRoomId === roomId && state.circlePeopleRequest === request) state.circleMentions = arr(mentions.items);
  } catch {
    if (state.circlePeopleRequest === request) {state.circleFoodRoomId = null;state.chatInlineError='People suggestions could not load. Try again.';render();}
  }
}

async function searchCircleFood(kind, query) {
  const generation = state.dataGeneration;
  const key = `${kind}:${query}`;
  if (!state.circleFoodSearches.has(key)) {
    const path = kind === 'recipe' ? '/api/recipes' : '/api/meals';
    const request = api(`${path}?query=${encodeURIComponent(query)}&limit=20`);
    state.circleFoodSearches.set(key, request);
    if (state.circleFoodSearches.size > 40) state.circleFoodSearches.delete(state.circleFoodSearches.keys().next().value);
  }
  try {
    const result = await state.circleFoodSearches.get(key);
    if (generation !== state.dataGeneration) return [];
    return arr(result.items).map(item => ({id: `${kind}:${item.id}`,
      name: `${kind} ${kind === 'recipe' ? item.title : item.name}`, details: `Share ${kind}`}));
  } catch(error) {
    state.circleFoodSearches.delete(key);
    state.chatInlineError='Food suggestions could not load. Use + Share to retry.';render();
    return [];
  }
}

async function loadCircleData(quiet = false) {
  const request = ++state.circleLoadRequest;
  if (!quiet) state.circleForegroundRequest = request;
  const generation = state.dataGeneration;
  const roomId = state.circleId;
  const shareId = state.circleShareId;
  const historySize=roomId?Math.max(50,state.circleFeed.length):50;
  const historyLimit=Math.min(100,historySize);
  const historyBoundary=roomId?state.circleFeed.at(-1):null;
  const valid = () => request === state.circleLoadRequest && generation === state.dataGeneration
    && state.view === 'circles' && (roomId === state.circleId
      || (!roomId && shareId && state.circleDetail?.circleId === state.circleId)) && shareId === state.circleShareId;
  try {
    // The conversation does not wait for public links, other rooms, or food pickers.
    const [circles, detail, feed] = await Promise.all([
      api('/api/chats').then(async chats => ({items: [...chats.items, ...arr((await api('/api/circles')).items).filter(c => c.myStatus === 'pending')]})),
      shareId ? api(`/api/circle-shares/${encodeURIComponent(shareId)}`) : null,
      roomId ? api(`/api/chats/${encodeURIComponent(roomId)}/history?limit=${historyLimit}`) : null,
    ]);
    if (!valid()) return;
    if (circles) {
      state.circles = arr(circles.items);
      const acceptedIds = new Set(state.circles.filter(circle => circle.myStatus === 'accepted').map(circle => circle.id));
      for (const id of state.circleFeeds.keys()) if (!acceptedIds.has(id)) {
        state.circleFeeds.delete(id); state.circleDrafts.delete(id);
      }
      if (roomId && !acceptedIds.has(roomId)) {
        state.circleId = null; state.circleShareId = null; state.circlePanel = null;
        state.circleFeed = []; state.circleDetail = null; render(); return;
      }
    }
    if (detail) {
      state.circleDetail = detail;
      if (!roomId) {
        state.circleId = detail.conversationId || detail.circleId;
        const result = await api(`/api/chats/${encodeURIComponent(detail.circleId)}/history`);
        if (request !== state.circleLoadRequest || generation !== state.dataGeneration || shareId !== state.circleShareId || state.view !== 'circles') return;
        state.circleFeed = arr(result.items); state.circleNextOffset = result.nextCursor;
        cacheCircleFeed(state.circleId, result);
      }
    }
    if (feed) {
      // Revalidate every loaded page so old edits/revocations are reflected too.
      while(feed.nextCursor && historyBoundary && feed.items.length && (feed.items.at(-1).createdAt>historyBoundary.createdAt || (feed.items.at(-1).createdAt===historyBoundary.createdAt && feed.items.at(-1).id>historyBoundary.id))){
        const olderPage=await api(`/api/chats/${encodeURIComponent(roomId)}/history?limit=50&cursor=${encodeURIComponent(feed.nextCursor)}`);
        if(!valid())return;feed.items.push(...olderPage.items);feed.nextCursor=olderPage.nextCursor;
      }
      // Only retain history returned by the current authorized reads.
      state.circleFeed=arr(feed.items);state.circleNextOffset=feed.nextCursor;
      cacheCircleFeed(roomId, {items: state.circleFeed, nextCursor: state.circleNextOffset});
      const latest = feed.items[0];
      if (latest) state.circleRecent = [latest, ...arr(state.circleRecent).filter(post => post.circleId !== roomId)];
    }
    state.circleFeedLoading = false; state.circleError = null;
    render();
    ChatLive.start();
    const mentionRoomId = state.circleId || detail?.circleId;
    if (mentionRoomId) loadCircleComposerData(mentionRoomId, !quiet);
    if (!quiet) {
      const listsRequest = ++state.circleListRequest;
      api('/api/public-shares').then(published => {
          if (listsRequest !== state.circleListRequest || generation !== state.dataGeneration || state.view !== 'circles') return;
          state.publicShares = arr(published.items);
          render();
        }).catch(() => { if (valid()) showToast('Some sharing lists could not refresh.'); });
    }
  } catch (error) {
    if (!valid()) return;
    state.circleFeedLoading = false;
    if (!quiet) {
      if (state.circleFeeds.has(roomId)) showToast('Conversation could not refresh. Try again when connected.');
      else state.circleError = error.message || 'Chats unavailable';
      state.chatInlineError=error.message || 'Conversation could not refresh.';
      render();
    }
  } finally {
    if (state.circleForegroundRequest === request) state.circleForegroundRequest = null;
  }
}

function circleRecipeCard(recipe, share) {
  const savedId = share.savedRecipeIds?.[recipe.id];
  return `<article class="card circle-recipe"><p class="eyebrow">${recipe.kind === 'ready_food' ? 'Ready food' : 'Recipe'}</p><h3>${esc(recipe.title)}</h3>
    ${recipe.description ? `<p class="tiny">${esc(recipe.description)}</p>` : ''}
    ${arr(recipe.ingredients).length ? `<h4>Ingredients</h4><ul>${recipe.ingredients.map((item) => `<li>${esc(item.name || item)}${item.quantity ? ` · ${esc(item.quantity)} ${esc(item.unit || '')}` : ''}</li>`).join('')}</ul>` : ''}
    ${arr(recipe.instructions).length ? `<h4>Method</h4><ol>${recipe.instructions.map((step) => `<li>${esc(typeof step === 'string' ? step : step.text || step.instruction)}</li>`).join('')}</ol>` : ''}
    <div class="circle-actions">${savedId ? action('Open saved recipe', 'circle-open-saved', savedId) : action('Save recipe', 'circle-save-recipe', `${share.id}:${recipe.id}`)}</div>
  </article>`;
}

function renderCircleDetail(share, {panel = false} = {}) {
  const snap = share.snapshot;
  const viewerId = state.session?.user?.id || state.chatProfile?.userId || 'demo';
  const ownerId = state.circles.find((circle) => circle.id === share.circleId)?.ownerId;
  const recipes = ['week', 'meal'].includes(share.kind) ? arr(snap.recipes) : share.kind === 'recipe' ? [snap.recipe] : [];
  const commentTargetName = (comment) => comment.targetType === 'meal'
    ? arr(snap.entries).find((meal) => meal.id === comment.targetId)?.meal || 'Meal'
    : comment.targetType === 'recipe'
      ? recipes.find((recipe) => recipe?.id === comment.targetId)?.title || 'Recipe'
      : share.kind === 'message' ? 'Message' : 'Whole share';
  const title = share.kind === 'week' ? `Week of ${snap.weekStart}` : share.kind === 'recipe' ? snap.recipe.title : share.kind === 'meal' ? snap.meal.name : 'Message';
  const targetOptions = [`<option value="post">${share.kind === 'message' ? 'Message' : 'Whole share'}</option>`,
    ...arr(snap.entries).map((entry) => `<option value="meal:${esc(entry.id)}">Meal: ${esc(entry.meal)}</option>`),
    ...recipes.filter(Boolean).map((recipe) => `<option value="recipe:${esc(recipe.id)}">Recipe: ${esc(recipe.title)}</option>`)].join('');
  const targetPicker = ['week', 'meal'].includes(share.kind) ? `<details class="circle-reply-target"><summary>Reply about a specific ${share.kind === 'week' ? 'meal or recipe' : 'recipe'}</summary><label class="sr-only" for="circle-target">Reply about</label><select id="circle-target" name="target">${targetOptions}</select></details>` : '';
  const meals = share.kind === 'meal' ? `<section class="circle-meals"><h3>Saved meal</h3><article class="circle-meal"><h4>${esc(snap.meal.name)}</h4>${snap.meal.notes ? `<p>${esc(snap.meal.notes)}</p>` : ''}<ul>${arr(snap.meal.components).map((part) => `<li>${esc(part.name)}</li>`).join('')}</ul></article></section>` : share.kind === 'week' ? `<section class="circle-meals"><h3>Every meal in the week</h3>${arr(snap.entries).map((entry) =>
    `<article class="circle-meal"><p class="eyebrow">${esc(entry.date)} · ${esc(entry.slotName || label(entry.slot))}</p><h4>${esc(entry.meal)}</h4>${entry.notes ? `<p>${esc(entry.notes)}</p>` : ''}${arr(entry.components).length ? `<ul>${entry.components.map((part) => `<li>${esc(part.name)}</li>`).join('')}</ul>` : ''}</article>`).join('')}</section>` : '';
  return `<div class="circle-detail"><div class="toolbar">${panel ? '' : action('Close thread', 'circle-back')}${share.createdBy === state.session?.user?.id || !state.client ? action(share.kind === 'message' ? 'Remove message' : 'Remove share', 'circle-revoke', share.id, 'danger') : ''}</div>
    <header class="circle-detail-head"><p class="eyebrow">${esc(share.createdByName || 'Friend')} ${share.kind === 'message' ? 'wrote' : 'shared'} ${share.roomType === 'direct' ? 'directly with you' : `in ${esc(share.circleName)}`}</p><h2>${esc(title)}</h2>${share.kind === 'message' ? `<p class="circle-message-body">${esc(snap.text)}</p>` : `<p class="muted tiny">${share.kind === 'week' ? 'The whole week as it was shared. Later edits to the original plan are not shown.' : 'A snapshot as it was shared.'}</p>${snap.caption ? `<p class="circle-message-body">${esc(snap.caption)}</p>` : ''}`}</header>
    ${meals}${recipes.length ? `<section class="circle-recipes"><h3>${share.kind === 'week' ? 'Recipes in this week' : 'Shared recipe'}</h3><div class="circle-recipe-grid">${recipes.filter(Boolean).map((recipe) => circleRecipeCard(recipe, share)).join('')}</div></section>` : ''}
    <section class="circle-discussion"><h3>Thread</h3>${arr(share.comments).length ? share.comments.map((comment) => `<div class="circle-comment" data-key="comment:${esc(comment.id)}"><small>${esc(comment.authorName || 'Friend')} · ${esc(commentTargetName(comment))}</small><p>${esc(comment.body)}</p>${!state.client || viewerId === comment.authorId || viewerId === share.createdBy || viewerId === ownerId ? action('Remove comment', 'circle-delete-comment', comment.id, 'danger') : ''}</div>`).join('') : '<p class="muted tiny">Start a conversation here.</p>'}
      <form id="circle-comment-form" data-live-form data-key="reply:${esc(share.id)}" class="circle-chat-composer">${targetPicker}<label class="sr-only" for="circle-comment">Reply</label><textarea id="circle-comment" name="body" data-mention="thread" maxlength="2000" required placeholder="Reply… type @ to mention someone"></textarea><div class="circle-composer-footer"><small>Enter to send · Shift+Enter for a new line</small><button class="button primary" type="submit">Send reply</button></div></form>
    </section></div>`;
}

function foodReviewMarkup(place) {
  const review = state.circleFoodReview;
  if (!review || review.place !== place) return '';
  const recipient = review.place === 'public' ? 'Anyone with the link' : review.place === 'direct'
    ? review.email : review.audienceNames.join(', ');
  const detail = review.kind === 'recipe'
    ? `${arr(review.source.ingredients).length} ingredients · ${arr(review.source.instructions).length} steps`
    : `${arr(review.source.components).length} foods · ${review.source.servings || '—'} servings`;
  const source = review.source;
  const details = review.kind === 'recipe'
    ? `${source.description ? `<p>${esc(source.description)}</p>` : ''}<ul>${arr(source.ingredients).map((item) => `<li>${esc(item.name || item)}${item.quantity ? ` · ${esc(item.quantity)} ${esc(item.unit || '')}` : ''}</li>`).join('')}</ul><ol>${arr(source.instructions).map((step) => `<li>${esc(typeof step === 'string' ? step : step.text || step.instruction || '')}</li>`).join('')}</ol>${source.source_url || source.sourceUrl ? `<p>Source: ${esc(source.source_url || source.sourceUrl)}</p>` : ''}`
    : `${source.notes ? `<p>Notes: ${esc(source.notes)}</p>` : ''}<ul>${arr(source.components).map((part) => `<li>${esc(part.name)}${part.quantity ? ` · ${esc(part.quantity)} ${esc(part.unit || '')}` : ''}</li>`).join('')}</ul>${arr(source.components).some((part) => part.recipeId) ? '<p>Linked recipes and their ingredients and instructions are included.</p>' : ''}`;
  return `<section class="circle-review circle-food-review" aria-label="Review food share"><p class="eyebrow">Check before sharing</p><h3>${esc(review.title)}</h3><p>${esc(detail)}</p><div class="circle-review-recipient"><strong>Who can see this</strong><span>${esc(recipient)}</span></div><div class="circle-food-review-details"><strong>Food details included</strong>${details}</div><p class="muted tiny">${review.place === 'public' ? 'This link can be opened by anyone who receives it. It has no comments.' : 'A frozen copy of this food and its linked recipes will be shared.'}</p><div class="circle-actions">${action(review.place === 'public' ? 'Create public link' : 'Confirm share', 'circle-confirm-food', '', 'primary')}${action('Cancel', 'circle-cancel-food')}</div></section>`;
}

function weekReviewRows(plan) {
  return arr(plan?.entries).map((meal) => `<li><strong>${esc(meal.date)} · ${esc(meal.slotName || label(meal.slot))}: ${esc(meal.meal)}</strong>${meal.notes ? `<span>Note: ${esc(meal.notes)}</span>` : ''}${arr(meal.components).length ? `<span>Included food: ${esc(meal.components.map((part) => part.name).join(', '))}</span>` : ''}</li>`).join('');
}

function circlePostTitle(post) {
  return post.kind === 'message' ? post.snapshot.text : post.kind === 'week' ? `Week of ${post.snapshot.weekStart}`
    : post.kind === 'meal' ? post.snapshot.meal?.name || 'Saved meal' : post.snapshot.recipe?.title || 'Recipe';
}

let chatReturnFocus = null;
function renderCirclePost(post, grouped = false, dateLabel = '', unread = false) {
  const pending = post.pending, failed = post.failed;
  const mine = post.createdBy === state.session?.user?.id || (!state.client && post.createdBy === (state.chatProfile?.userId || 'demo'));
  const body = post.snapshot.text || post.snapshot.caption;
  const reactions = arr(post.reactions).map(r => `<button type="button" class="chat-reaction" aria-label="${esc(r.emoji)} reaction" aria-pressed="${r.mine}" data-action="chat-react" data-id="${esc(post.id)}:${esc(r.emoji)}">${esc(r.emoji)} ${r.count}</button>`).join('');
  const editing = state.chatEdit?.id === post.id;
  return `${dateLabel ? `<div class="chat-date" data-key="date:${esc(post.id)}">${esc(dateLabel)}</div>` : ''}${unread ? '<div class="chat-unread" data-key="unread">New messages</div>' : ''}<article data-key="post:${esc(post.id)}" data-id="${esc(post.id)}" class="circle-post ${mine ? 'mine' : ''} ${grouped ? 'grouped' : ''} ${failed ? 'failed' : ''} ${post.id === state.circleShareId ? 'thread-open' : ''}">
    <div class="circle-message-meta"><strong>${esc(mine ? 'You' : post.createdByName || 'Friend')}</strong><time datetime="${esc(post.createdAt)}">${pending ? 'Sending…' : esc(new Date(post.createdAt).toLocaleTimeString(undefined, {hour:'numeric', minute:'2-digit'}))}</time>${post.editedAt ? '<small>Edited</small>' : ''}</div>
    ${post.snapshot.replyTo ? `<blockquote class="chat-quote"><strong>${esc(post.snapshot.replyTo.name)}</strong><p>${esc(post.snapshot.replyTo.text)}</p></blockquote>` : ''}
    ${editing ? `<form id="chat-edit-form" data-live-form data-key="edit:${esc(post.id)}" data-id="${esc(post.id)}"><label for="chat-edit-body">Edit message</label><textarea id="chat-edit-body" name="body" maxlength="2000" required>${esc(post.snapshot.text)}</textarea><button class="button primary" type="submit">Save message</button>${action('Cancel edit','chat-cancel-edit')}</form>` : body ? `<p class="circle-message-body">${esc(body)}</p>` : ''}
    ${post.kind === 'message' ? '' : `<button type="button" class="circle-share-preview" data-action="circle-open-share" data-id="${esc(post.id)}" aria-label="Open ${post.kind === 'week' ? 'weekly plan' : post.kind === 'meal' ? 'meal' : 'recipe'} snapshot: ${esc(circlePostTitle(post))}"><small>${post.kind === 'week' ? 'Weekly plan' : post.kind === 'meal' ? 'Saved meal' : 'Recipe'}</small><h3>${esc(circlePostTitle(post))}</h3><p>${post.kind === 'week' ? `${arr(post.snapshot.entries).length} meals` : 'View food and discussion'} →</p></button>`}
    ${pending ? '<small class="circle-send-state" role="status">Sending…</small>' : failed ? `<div class="chat-send-error" role="alert">${esc(post.error || 'Message was not sent')}${action('Retry message','chat-retry',post.id)}${action('Edit failed message','chat-edit-failed',post.id)}</div>` : `<div class="circle-actions">${reactions}${post.commentCount ? action(`${post.commentCount} ${post.commentCount === 1 ? 'reply' : 'replies'}`, 'circle-open-share', post.id) : ''}<details class="chat-message-menu" data-key="menu:${esc(post.id)}"><summary aria-label="Message actions">•••</summary><div>${action('Reply in thread','circle-open-share',post.id)}${action('Quote reply','chat-quote',post.id)}${['👍','❤️','😋','🎉'].map(emoji => action(emoji,'chat-react',`${post.id}:${emoji}`)).join('')}${mine && post.kind === 'message' ? action('Edit message','chat-edit',post.id) : ''}</div></details>${mine && post.seenBy ? `<small class="chat-seen">Seen by ${post.seenBy}</small>` : ''}</div>`}
  </article>`;
}

function renderCircleConversation(circle) {
  const pending = [...state.circlePending.values()].filter(post => post.circleId === circle.id);
  const posts = [...state.circleFeed].reverse().concat(pending);
  const draft = state.circleDrafts.get(circle.id) || '';
  const search = state.chatSearchOpen;
  const filtered = state.chatResults === null ? posts : [...state.chatResults].reverse();
  const searchForm = search ? `<form id="chat-search-form" data-live-form data-key="history-search:${circle.id}" class="chat-history-search"><label class="sr-only" for="chat-history-query">Search messages</label><input id="chat-history-query" name="query" type="search" maxlength="120" placeholder="Search messages and shared food" value="${esc(state.chatSearch)}" /><label>From<select name="sender" aria-label="From"><option value="">Anyone</option>${arr(circle.members).filter(m=>m.status==='accepted').map(m=>`<option value="${esc(m.userId)}">${esc(m.name || m.email)}</option>`).join('')}</select></label><label>Since<input name="date" type="date" /></label><label>Type<select name="kind" aria-label="Type"><option value="">Everything</option><option value="message">Messages</option><option value="recipe">Recipes</option><option value="meal">Meals</option><option value="week">Weeks</option></select></label><button type="submit" class="button">Search history</button>${action('Clear search','chat-clear-search')}</form>` : '';
  return `<section class="circle-feed" ${state.circlePanel && state.circlePanel !== 'thread' || state.circleReview || state.circleFoodReview?.place === 'group' ? 'inert' : ''} data-key="feed:${esc(circle.id)}" aria-label="Circle conversation">
    <header class="circle-pane-head circle-card"><div>${action('‹ Chats','circle-home','','circle-mobile-back')}<h2>${esc(circle.name)}</h2><p>${circle.roomType === 'direct' ? 'Direct conversation' : `${circle.memberCount || 1} members`} <span class="chat-connection" role="status">${esc(ChatLive.status())}</span></p></div><div class="chat-header-actions"><button class="icon-button chat-search-toggle" type="button" data-action="chat-search-toggle" aria-label="Search messages" title="Search messages"><svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true"><circle cx="10.5" cy="10.5" r="6.5"/><path d="m16 16 5 5"/></svg></button><details class="chat-room-menu"><summary aria-label="Conversation settings">•••</summary><div>${action('Members and circle settings','circle-members',circle.id)}${action(circle.muted ? 'Unmute conversation' : 'Mute conversation','chat-mute',circle.id)}</div></details></div></header>
    ${searchForm}${state.chatInlineError ? `<p class="chat-inline-error" role="alert">${esc(state.chatInlineError)}${action('Try again','circle-retry')}</p>` : ''}
    <div class="circle-timeline" data-key="timeline:${esc(circle.id)}" role="log" aria-label="Messages" aria-live="polite" aria-relevant="additions text">${state.circleNextOffset !== null && state.chatResults === null ? action('Show earlier activity','circle-load-more') : ''}${state.chatResults!==null&&state.chatSearchCursor? action('More search results','chat-search-more'):''}${filtered.map((post,i) => {const previous=filtered[i-1]; const day=post.createdAt.slice(0,10); return renderCirclePost(post, previous?.createdBy===post.createdBy && previous.createdAt.slice(0,10)===day && Date.parse(post.createdAt)-Date.parse(previous.createdAt)<300000, previous?.createdAt.slice(0,10)!==day ? new Date(post.createdAt).toLocaleDateString(undefined,{weekday:'short',month:'short',day:'numeric'}) : '', Boolean(circle.lastReadAt && post.createdAt>circle.lastReadAt && (!previous || previous.createdAt<=circle.lastReadAt) && post.createdBy!==(state.chatProfile?.userId || state.session?.user?.id)));}).join('') || `<p class="chat-empty" role="status">${state.chatResults !== null ? 'No messages match. Clear search to return to the conversation.' : state.circleFeedLoading ? 'Loading conversation…' : 'Say hello, or share something delicious.'}</p>`}</div>
    <button class="button chat-jump" type="button" data-action="chat-jump" hidden>Jump to latest ↓</button>
    <form id="circle-message-form" data-live-form data-key="composer:${esc(circle.id)}" class="circle-chat-composer circle-message-form" data-circle-id="${esc(circle.id)}"><div class="chat-reply-chip" ${state.chatReply?.circleId === circle.id ? '' : 'hidden'}>${state.chatReply?.circleId === circle.id ? `Replying to ${esc(state.chatReply.name)}: ${esc(state.chatReply.text)} ${action('Remove quoted reply','chat-unquote')}` : ''}</div><label class="sr-only" for="circle-message">Message ${esc(circle.name)}</label><textarea id="circle-message" name="body" data-mention="group" maxlength="2000" rows="1" placeholder="Message ${esc(circle.name)}…">${esc(draft)}</textarea><div class="circle-attachment" hidden></div><div class="circle-composer-footer">${action('+ Share','circle-share-menu',circle.id)}<small>Enter to send · Shift+Enter for a new line</small><button class="button primary" type="submit">Send message</button></div></form>
  </section>`;
}

function renderCircleMembers(circle) {
  const owner = circle.ownerId === state.session?.user?.id || !state.client;
  const friends = arr(circle.members).filter(member => member.userId !== circle.ownerId);
  return `<section class="circle-manage" data-circle-id="${esc(circle.id)}">${state.chatFormError ? `<p class="chat-inline-error" role="alert">${esc(state.chatFormError)}</p>` : ''}${owner && circle.roomType !== 'direct' ? `<form class="circle-form circle-invite-form" data-live-form data-key="invite:${esc(circle.id)}" data-circle-id="${esc(circle.id)}"><label>Invite an existing friend<input name="email" type="email" required placeholder="friend@example.com" /><small>Use a verified Meal Prep account. Invitations appear in their app.</small></label><button class="button ghost" type="submit">Invite friend</button></form>${friends.length ? `<div class="circle-members"><h4>Friends</h4>${friends.map(member => `<div class="circle-member" data-key="member:${esc(member.userId)}"><span>${esc(member.email)} · ${esc(member.status)}</span>${action(member.status === 'pending' ? 'Cancel invite' : 'Remove friend', 'circle-remove-friend', `${circle.id}:${member.userId}`, 'danger')}</div>`).join('')}</div>` : ''}` : `<p class="muted tiny">${circle.memberCount || 1} members in this private circle.</p><div class="circle-actions">${action('Leave circle', 'circle-leave', circle.id, 'danger')}</div>`}</section>`;
}

function renderCirclePanel(circle) {
  const review = state.circleReview?.circleId === circle.id ? state.circleReview : null;
  const foodReview = state.circleFoodReview?.place === 'group';
  const mode = review || foodReview ? 'review' : state.circlePanel || (state.circleShareId ? 'thread' : null);
  if (!mode) return '';
  let body, title;
  if (mode === 'members') { title = 'Members and circle settings'; body = renderCircleMembers(circle); }
  else if (mode === 'food') { title = 'Choose food to share'; body = chatPickerMarkup(); }
  else if (mode === 'share') { title = 'Share with your circle'; body = `<div class="circle-share-options">${action('Share a recipe', 'circle-compose-recipe', circle.id)}${action('Share this week', 'circle-share-week', circle.id)}</div>`; }
  else if (mode === 'review') {
    title = 'Review before sharing';
    body = foodReview ? foodReviewMarkup('group') : `<section class="circle-review"><h3>Review before sharing</h3><p>Week of ${esc(review.weekStart)} · ${arr(review.plan.entries).length} meals</p><p>Visible to ${esc(arr(circle.memberNames).join(', ') || 'you')} (${esc(circle.memberCount || 1)} accepted members). Future members cannot see this share.</p><ul>${weekReviewRows(review.plan)}</ul><p class="muted tiny">All meal notes and linked recipes or ready foods become a snapshot. Friends can save recipes as independent copies. Pantry stock, prep tasks, and shopping stay private.</p><div class="circle-actions">${action('Publish week', 'circle-publish-week', circle.id, 'primary')}${action('Cancel', 'circle-cancel-review')}</div></section>`;
  } else { title = 'Thread'; body = state.circleDetail ? renderCircleDetail(state.circleDetail, {panel: true}) : '<div class="section-loading" role="status">Loading thread…</div>'; }
  return `<div class="circle-panel-layer" data-key="panel-layer"><aside class="circle-side-panel ${mode === 'thread' ? 'circle-thread-panel' : ''}" data-key="panel:${mode}" aria-label="${esc(title)}"><header class="circle-panel-head"><h3>${esc(title)}</h3>${action(mode === 'thread' ? 'Close thread' : 'Back to conversation', mode === 'thread' ? 'circle-back' : 'circle-close-panel')}</header>${body}</aside></div>`;
}

function renderCircles() {
  if (state.circleError && !state.circles.length) return empty('Chats unavailable', state.circleError) + action('Try again','circle-retry');
  const accepted = state.circles.filter((circle) => circle.myStatus === 'accepted');
  const pending = state.circles.filter((circle) => circle.myStatus === 'pending');
  const selected = accepted.find((circle) => circle.id === state.circleId);
  const directDetail = state.circleDetail?.roomType === 'direct';
  const world = state.circleHub === 'world';
  const latest = (id) => accepted.find(c=>c.id===id)?.latest;
  const postTitle = circlePostTitle;
  const searchTerm = state.circleSearch.trim().toLowerCase();
  const visibleCircles = accepted.filter((circle) => !searchTerm || `${circle.name} ${latest(circle.id) ? postTitle(latest(circle.id)) : ''}`.toLowerCase().includes(searchTerm));
  const timeLabel = (value) => value ? new Date(value).toLocaleTimeString(undefined, {hour: 'numeric', minute: '2-digit'}) : '';
  const room = (circle) => `<button data-key="room:${esc(circle.id)}" class="circle-room ${circle.roomType==='direct'?'direct-room':''} ${selected?.id === circle.id ? 'active' : ''}" data-action="circle-open" data-id="${esc(circle.id)}" aria-current="${selected?.id === circle.id ? 'page' : 'false'}"><span class="circle-room-avatar" aria-hidden="true">${esc(circle.name.slice(0, 1).toUpperCase())}</span><span class="circle-room-copy"><span class="circle-room-title"><strong>${esc(circle.name)}</strong><time>${esc(timeLabel(latest(circle.id)?.createdAt))}</time></span><small>${esc(latest(circle.id) ? postTitle(latest(circle.id)) : `${circle.memberCount || 1} members`)}</small>${circle.unreadCount ? `<span class="chat-unread-count">${circle.unreadCount}</span>` : ''}${circle.muted ? '<small>Muted</small>' : ''}</span></button>`;
  const sidebar = `<aside data-key="rail" class="circle-rail" aria-label="Sharing conversations"><div class="circle-rail-head"><strong>Chats</strong>${action('Create circle', 'circle-compose-create')}</div><label class="sr-only" for="circle-search">Search conversations</label><input id="circle-search" class="circle-search" type="search" value="${esc(state.circleSearch)}" placeholder="Search conversations" autocomplete="off" />
    <button class="circle-rail-link ${!selected && !directDetail && !world ? 'active' : ''}" data-action="circle-activity">⌂ <span>All activity</span></button>
    <div class="circle-rail-section"><div class="circle-rail-label">Your circles <span>${accepted.filter(c=>c.roomType!=='direct').length}</span></div><nav class="circle-room-list" aria-label="Circle conversations">${visibleCircles.filter(c=>c.roomType!=='direct').map(room).join('')}</nav></div>
    <div class="circle-rail-section"><div class="circle-rail-label">Friends <span>${accepted.filter(c=>c.roomType==='direct').length}</span></div><nav class="circle-room-list" aria-label="Direct shares">${visibleCircles.filter(c=>c.roomType==='direct').map(room).join('')}</nav><div class="circle-rail-actions">${action('Share with a friend', 'direct-compose-recipe')}${action('Share a week', 'direct-compose-week', '', 'ghost circle-mobile-week')}</div></div>
    <div class="circle-rail-section"><div class="circle-rail-label">Links</div><button class="circle-rail-link ${world ? 'active' : ''}" data-action="circle-world">◉ <span>Public links</span></button></div></aside>`;
  const create = state.circleComposer === 'create' ? `<form id="circle-create-form" data-live-form class="circle-form circle-compose"><label for="circle-name">Circle name</label><input id="circle-name" name="name" maxlength="80" required placeholder="Dinner friends" /><button class="button primary" type="submit">Create</button></form>` : '';
  const pendingInvites = pending.map((circle) => `<article class="circle-activity"><strong>${esc(circle.name)}</strong><span>Invitation to join</span><div class="circle-actions">${action('Join circle', 'circle-accept', circle.id, 'primary')}${action('Decline', 'circle-decline', circle.id)}</div></article>`).join('');
  const directForm = state.circleComposer?.startsWith('direct-') && !state.circleFoodReview ? `<form id="direct-share-form" data-live-form data-key="direct-form:${state.circleComposer}" class="circle-form circle-compose" data-kind="${state.circleComposer.slice(7)}"><h3>Share ${state.circleComposer === 'direct-week' ? 'a week' : 'food'} with one friend</h3><p class="muted tiny">Only this friend can open and reply to the snapshot. No circle membership is needed.</p><label for="direct-email">Friend’s account email</label><input id="direct-email" name="email" type="email" maxlength="320" required placeholder="friend@example.com" />${state.circleComposer === 'direct-week' ? `<label for="direct-week">Week starting Monday</label><input id="direct-week" name="weekStart" type="date" value="${esc(state.weekStart || monday())}" required />` : `<label for="direct-food-search">Food to share</label><textarea id="direct-food-search" name="foodSearch" data-mention="food" placeholder="Type @recipe or @meal to search your library"></textarea><div class="circle-attachment" hidden></div>`}<div class="circle-actions"><button class="button primary" type="submit">${state.circleComposer === 'direct-week' ? 'Review week' : 'Review share'}</button>${action('Cancel', 'circle-cancel-compose')}</div></form>` : '';
  const directReview = state.directReview ? `<section class="circle-review"><h3>Review direct share</h3><p>Week of ${esc(state.directReview.weekStart)} · ${arr(state.directReview.plan.entries).length} meals · To ${esc(state.directReview.email)}</p><ul>${weekReviewRows(state.directReview.plan)}</ul><p class="muted tiny">This is a frozen snapshot. Pantry, prep tasks, and shopping stay private.</p><div class="circle-actions">${action('Publish to friend', 'direct-publish-week', '', 'primary')}${action('Cancel', 'circle-cancel-compose')}</div></section>` : '';
  const home = `<section class="circle-hub"><header class="circle-pane-head"><div>${action('‹ Chats', 'circle-home', '', 'circle-mobile-back')}<p class="eyebrow">Your food conversations</p><h2>All activity</h2></div><div class="circle-actions">${action('Share a recipe', 'direct-compose-recipe', '', 'primary')}${action('Share a week', 'direct-compose-week')}</div></header>${create}${directForm}${foodReviewMarkup('direct')}${directReview}${pendingInvites}${!state.circleComposer && !state.directReview && !state.circleFoodReview ? '<div class="chat-welcome"><span aria-hidden="true">↗</span><h3>Your table, together</h3><p>Choose a conversation to catch up, share food, or plan something together.</p></div>' : ''}</section>`;
  const group = selected ? renderCircleConversation(selected) : "";
  const activeLinks = state.publicShares.filter((item) => !item.revokedAt && (!item.expiresAt || new Date(item.expiresAt) > new Date()));
  const historyLinks = state.publicShares.filter((item) => !activeLinks.includes(item));
  const publicForm = state.circleComposer?.startsWith('public-') && !state.circleFoodReview ? `<form id="public-share-form" data-live-form data-key="public-form:${state.circleComposer}" class="circle-form circle-compose"><h3>Create a public food link</h3><p class="muted tiny">Anyone with the link can view the snapshot. Public links are read only and have no comments.</p><label for="public-food-search">Recipe or saved meal</label><textarea id="public-food-search" name="foodSearch" data-mention="food" placeholder="Type @recipe or @meal to search your library"></textarea><div class="circle-attachment" hidden></div><div class="circle-actions"><button class="button primary" type="submit">Create public link</button>${action('Cancel', 'circle-cancel-compose')}</div></form>` : '';
  const worldPane = `<section class="circle-hub circle-world"><header class="circle-pane-head"><div>${action('‹ Chats', 'circle-home', '', 'circle-mobile-back')}<p class="eyebrow">Public sharing</p><h2>Public links</h2><p>Anyone with a link can view. Public links do not have comments.</p></div><div class="circle-actions">${action('Share a recipe', 'public-compose-recipe', '', 'primary')}${action('Share a meal', 'public-compose-meal')}</div></header>${publicForm}${foodReviewMarkup('public')}<h3>Active links</h3>${activeLinks.length ? activeLinks.map((item) => `<article class="circle-public-row"><div><small>${esc(item.kind)}</small><strong>${esc(item.title)}</strong><span>Created ${esc(new Date(item.createdAt).toLocaleDateString())}</span></div><div class="circle-actions">${item.url ? `<input readonly aria-label="Public link for ${esc(item.title)}" value="${esc(item.url)}" />${action('Copy link', 'public-copy', item.id)}` : '<span class="muted tiny">Older link unavailable; create a new one to copy it.</span>'}${action('Revoke', 'public-revoke', item.id, 'danger')}</div></article>`).join('') : '<p class="muted tiny">No active public links yet.</p>'}${historyLinks.length ? `<h3>History</h3>${historyLinks.map((item) => `<article class="circle-public-row"><div><small>${esc(item.kind)}</small><strong>${esc(item.title)}</strong><span>${item.revokedAt ? 'Revoked' : 'Expired'}</span></div></article>`).join('')}` : ''}</section>`;
  return `<div class="circle-page">${state.chatFormError && !selected ? `<p class="chat-inline-error" role="alert">${esc(state.chatFormError)}</p>` : ''}<div class="circle-layout ${selected ? 'circle-mode-group' : directDetail ? 'circle-mode-direct' : world ? 'circle-mode-world' : state.circleHub === 'activity' ? 'circle-mode-activity' : 'circle-mode-home'} ${state.circleComposer || state.directReview || state.circleFoodReview || pending.length ? 'composing' : ''}">${sidebar}${world ? worldPane : selected ? group : directDetail ? `<section class="circle-hub circle-direct-detail"><header class="circle-pane-head"><div><p class="eyebrow">Direct share · ${esc(state.circleDetail.directPeerName || 'Friend')}</p><h2>${esc(postTitle(state.circleDetail))}</h2></div>${action('All activity', 'circle-home')}</header>${renderCircleDetail(state.circleDetail)}</section>` : selected ? group : home}</div>${selected ? renderCirclePanel(selected) : ""}</div>`;
}

function renderPlanningRules() {
  if (state.ruleRevisionId) {
    const revision = state.rulePreview;
    const usedForPlan = revision?.id === state.plan?.ruleRevisionId;
    return `<div class="planning-rules-page"><div class="section-head"><div><h2>Saved preference version</h2><p>${usedForPlan ? `Used for the week of ${esc(state.weekStart)}.` : 'Saved recurring instructions.'}</p></div>${action('View current preferences', 'plan-tab', 'rules')}</div>
      ${state.rulePreviewError ? empty('Could not load this version', state.rulePreviewError) : revision ? `<article class="card" id="planning-rule-preview"><div class="card-head"><h3>Meal preferences · version ${esc(revision.revision)}</h3><span class="muted tiny">Read only</span></div><p class="planning-text">${esc(revision.text || 'No recurring preferences in this version.')}</p></article>` : empty('Loading this version', 'Opening the saved preferences…')}</div>`;
  }
  if (!sectionStatus('mealPlanRules') || ['loading', 'unavailable'].includes(sectionStatus('mealPlanRules'))) return sectionContent('mealPlanRules', '');
  const rules = state.mealPlanRules;
  const ruleBody = rules
    ? `<p class="muted tiny rule-version">Current · Version ${esc(rules.revision)}</p><p class="planning-text">${esc(rules.text || 'No recurring preferences in this version.')}</p>`
    : '<p class="muted planning-text">Describe your usual week in English: favourite meals, weekend prep, and how you use leftovers.</p>';
  const history = state.ruleHistory === null ? '' : `<section id="planning-rule-history" aria-label="Preference history"><h3>Saved versions</h3>${state.ruleHistory.length ? state.ruleHistory.map((revision) => row(`Version ${revision.revision}${revision.id === rules?.id ? ' · Current' : ''}`, new Date(revision.createdAt).toLocaleString(), action(`View version ${revision.revision}`, 'view-rule-revision', revision.id))).join('') : '<p class="muted tiny">No versions saved yet.</p>'}</section>`;
  return `<div class="planning-rules-page"><div class="section-head"><div><h2>Your usual week</h2><p>Recurring instructions for any week. Add one-time changes in the Meals tab’s weekly notes.</p></div></div>
    ${card('Meal preferences', '▦', ruleBody, `<div class="rule-actions">${action('Edit meal preferences', 'edit-planning-rules', '', 'primary')}${action('View preference history', 'view-rule-history')}</div>`)}${history}</div>`;
}

function renderPlan() {
  const tabs = `<div class="planning-tabs" role="tablist" aria-label="Weekly plan sections">${[['plan', 'Meals'], ['tasks', 'Tasks'], ['rules', 'Preferences']].map(([id, name]) => `<button type="button" role="tab" id="planning-tab-${id}" aria-selected="${state.planTab === id}" aria-controls="planning-panel" tabindex="${state.planTab === id ? '0' : '-1'}" data-action="plan-tab" data-id="${id}">${name}</button>`).join('')}</div>`;
  if (state.planTab === 'rules') return `${tabs}<section id="planning-panel" role="tabpanel" aria-labelledby="planning-tab-rules">${renderPlanPreferences()}</section>`;
  const plan = state.plan;
  const schedule = state.schedule;
  const showTasks = state.planTab === 'tasks';
  const count = arr(plan?.entries).length;
  let html = `<div class="toolbar plan-toolbar"><div class="week-navigation">${action("Previous week","week-previous")}<label class="field">Week of<input id="week-picker" type="date" value="${esc(state.weekStart)}" /></label>${action("Next week","week-next")}${action("Today","week-today")}</div><div class="plan-actions">${action('Shopping needs', 'shopping-preview')}${showTasks ? action('Add task', 'add-task', '', 'primary') : `${action('Use saved meal', 'use-saved-meal')}${action('Add meal', 'add-meal', '', 'primary')}`}</div></div>
    <div class="plan-summary"><p>${esc(label(plan?.status || 'Draft'))} · ${showTasks ? `${arr(plan?.tasks).length} tasks` : `${count} meals`}</p>${plan?.ruleRevision ? `<button type="button" class="text-button" id="plan-rule-source" data-action="view-rule-revision" data-id="${esc(plan.ruleRevision.id)}">Preferences used: version ${esc(plan.ruleRevision.revision)}</button>` : ''}</div>
    <div class="week-notes-row"><details id="week-notes"><summary>Notes for this week${schedule?.notes ? '<span class="notes-indicator">Added</span>' : ''}</summary><p class="planning-text">${esc(schedule?.notes || 'Add guests, ingredients to use, or other changes for this week.')}</p></details>${action('Edit notes', 'edit-week-notes')}</div>`;
  if (!plan && !schedule) html += '<p class="muted tiny open-week">This week is open. Add a meal or update your planning preferences to begin.</p>';
  if (!showTasks) html += MealNutrition.renderWeek(plan?.nutritionSummary);
  html += `<div class="week-grid">${DAYS.map((day, index) => {
    const date = dateForDay(state.weekStart, index);
    const entries = arr(plan?.entries).filter((entry) => entry.date === date).sort((a, b) => slotOrder(a) - slotOrder(b));
    const tasks = arr(plan?.tasks).filter((task) => task.date === date);
    const displayDate = new Date(`${date}T12:00:00`).toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
    return `<div class="day-card"><b>${day}</b><span class="mode">${esc(displayDate)}</span>${showTasks ? `<div class="day-tasks">${tasks.map(taskMarkup).join('') || '<p class="muted tiny">No tasks planned</p>'}<button class="button ghost small" data-action="add-task" data-id="${esc(date)}" aria-label="Add task to ${day}">+ Add task</button></div>` : `${entries.length ? entries.map(mealMarkup).join('') : '<p class="muted tiny">No meals planned</p>'}<button class="button ghost small day-add" data-action="add-meal" data-id="${esc(date)}" aria-label="Add meal to ${day}">+ Add meal</button>`}</div>`;
  }).join('')}</div>`;
  const otherTasks = arr(plan?.tasks).filter((task) => !task.date || task.date < state.weekStart || task.date > dateForDay(state.weekStart, 6));
  if (showTasks && otherTasks.length) html += `<article class="card other-tasks"><h3>Other dates & unscheduled tasks</h3>${otherTasks.map((task) => `<p class="tiny">${esc(task.date || 'No date set')}</p>${taskMarkup(task)}`).join('')}</article>`;
  return `${tabs}<section id="planning-panel" role="tabpanel" aria-labelledby="planning-tab-${showTasks ? 'tasks' : 'plan'}">${html}</section>`;
}

function recipeCategories(recipe) {
  const names = {cuisine:'Cuisine',goal:'Eating goal',meal:'Meal',diet:'Diet'};
  const fields = {cuisine:'cuisines',goal:'eating_goals',meal:'meal_types',diet:'diets'};
  return `<div class="tag-list recipe-categories">${Object.entries(fields).flatMap(([kind,field]) => arr(recipe[field]).map(value => `<button type="button" class="tag recipe-tag-button" data-action="filter-recipe-category" data-id="${kind}:${esc(value)}" aria-label="Show recipes with ${names[kind].toLowerCase()} ${esc(value)}">${esc(value)}</button>`)).join('')}</div>`;
}

function recipePublicReviewMarkup() {
  const review = state.recipeShareReview;
  if (!review) return '';
  const recipe = review.source;
  return `<div class="circle-food-review" aria-label="Review public recipe"><strong>Check this recipe before making a public link</strong><p>Anyone with the link can view this fixed copy. There are no comments.</p><h4>${esc(recipe.title)}</h4>${recipe.description ? `<p>${esc(recipe.description)}</p>` : ''}<ul>${arr(recipe.ingredients).map((item) => `<li>${esc(item.name || item)}</li>`).join('')}</ul><ol>${arr(recipe.instructions).map((step) => `<li>${esc(typeof step === 'string' ? step : step.text || step.instruction || '')}</li>`).join('')}</ol><div class="circle-actions">${action('Confirm public link', 'recipe-confirm-share', recipe.id, 'primary')}${action('Cancel', 'recipe-cancel-share')}</div></div>`;
}

function renderRecipes() {
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
    return `<div class="toolbar">${action('← All recipes', 'close-recipe')}<div class="recipe-detail-actions">${action('Explore this recipe', 'explore-recipe', recipe.id)}${action('Edit recipe', 'edit-recipe', recipe.id)}${action('Archive', 'archive-recipe', recipe.id, 'danger')}</div></div><section class="hero" style="min-height:220px"><div class="hero-copy"><p class="eyebrow">${recipe.kind === 'ready_food' ? 'Ready food' : 'Saved recipe'}</p><h2>${esc(recipe.title)}</h2><p>${esc(recipe.description || 'Your household recipe.')}</p>${recipeCategories(recipe)}${recipeTags(recipe.tags)}</div><div class="hero-stat"><strong>${esc(recipe.total_minutes ?? recipe.totalMinutes ?? '—')}</strong><span>minutes total · ${esc(recipe.servings || '—')} servings</span></div></section>${MealNutrition.renderCard(recipe.nutrition)}<div class="section-head"><h2>Recipe details</h2></div><div class="card-grid">${card('Ingredients', '□', ingredients.length ? `<div class="stack">${ingredients.map((item) => row(typeof item === 'string' ? item : item.name, typeof item === 'string' ? '' : `${item.quantity ?? ''} ${item.unit || ''}`)).join('')}</div>` : '<p class="muted tiny">No ingredients saved.</p>')}${card('Method', '▦', instructions.length ? `<ol style="padding-left:18px;font-size:.75rem;line-height:1.6">${instructions.map((step) => `<li>${esc(typeof step === 'string' ? step : step.text || step.instruction)}</li>`).join('')}</ol>` : '<p class="muted tiny">No steps saved.</p>')}${card('What you learned', '♡', feedbackBody, feedbackAction)}</div><div class="section-head"><h2>Share</h2></div>${card('Share this recipe', '↗', shareBody + recipePublicReviewMarkup(), state.recipeSharesUnavailable || state.recipeShareReview ? '' : `<div style="margin-top:20px">${action('Create share link', 'create-share', recipe.id, 'primary')}</div>`)}`;
  }
  return `<div class="toolbar"><span></span><div class="recipe-detail-actions">${action('Create meal', 'create-library-meal')}${action('Add recipe', 'add-recipe', '', 'primary')}</div></div><div id="recipe-browser"></div>`;
}

function savedMealCard(meal) {
  return `<article class="card saved-meal" data-saved-meal="${esc(meal.id)}"><p class="tiny muted">Meal · ${esc(meal.servings)} default servings</p><h3>${esc(meal.name)}</h3><ul class="meal-components">${componentSummary(meal)}</ul>${meal.notes ? `<p class="tiny">${esc(meal.notes)}</p>` : ''}<div class="meal-actions">${action('Plan this meal', 'plan-library-meal', meal.id, 'primary')}${action('Edit', 'edit-library-meal', meal.id)}${action('Archive', 'archive-library-meal', meal.id, 'danger')}</div></article>`;
}

async function loadMealRecipes() {
  const generation = state.dataGeneration;
  const recipes = [];
  let offset = 0;
  while (true) {
    const page = await api(`/api/recipe-library?item_type=all&limit=50&offset=${offset}`);
    recipes.push(...page.items.filter(row => row.itemType !== 'meals')); offset += page.items.length;
    if (!page.items.length || offset >= page.count) break;
  }
  if (generation !== state.dataGeneration) throw new Error('Household changed. Try again.');
  state.mealRecipes = recipes;
}

async function prepareFoodReview(place, kind, id, extra = {}) {
  const source = await api(`/api/${kind === 'meal' ? 'meals' : 'recipes'}/${encodeURIComponent(id)}`);
  const circle = place === 'group' ? state.circles.find((item) => item.id === extra.circleId) : null;
  if (place === 'group' && !circle) throw new Error('Circle is no longer available.');
  state.circleFoodReview = {
    place, kind, id, source, title: kind === 'meal' ? source.name : source.title,
    householdId: state.activeHouseholdId,
    audienceKeys: arr(circle?.audience).map((member) => `${member.userId}:${member.membershipId}`).sort(),
    audienceNames: arr(circle?.audience).map((member) => member.name || 'Friend'),
    ...extra,
  };
  render();
}

function bindCircleMentions() {
  if (!window.MentionJS) return;
  for (const field of content.querySelectorAll('[data-mention]')) {
    if (circleMentionInstances.some(item => item.field === field)) continue;
    const composer = field.closest('form');
    const group = field.dataset.mention === 'group';
    const food = group || field.dataset.mention === 'food';
    const instance = new window.MentionJS(field, {
      trigger: '@', debounceDelay: 100, noResultsText: 'No matching people or food',
      searchFunction: async (query) => {
        const term = query.trim().toLowerCase();
        const kind = term.startsWith('recipe') ? 'recipe' : term.startsWith('meal') ? 'meal' : null;
        const needle = (kind ? term.slice(kind.length).replace(/^[:_-]/, '') : term).trim();
        const generation = state.dataGeneration;
        if (kind && food) return searchCircleFood(kind, needle);
        await state.circlePeopleRequest?.catch(() => {});
        if (!field.isConnected || generation !== state.dataGeneration) return [];
        return (field.dataset.mention === 'food' ? [] : state.circleMentions)
          .filter(item => field.dataset.mention !== 'thread' || arr(state.circleDetail?.recipientUserIds).includes(item.id))
          .filter(item => item.name.toLowerCase().includes(needle))
          .slice(0, 20).map(item => ({id: `user:${item.id}`, name: item.name, details: 'Person'}));
      },
      onMentionSelect: (item) => {
        const [kind, id] = String(item.id).split(':');
        if (!food || !['recipe', 'meal'].includes(kind)) return;
        composer.dataset.attachmentKind = kind;
        composer.dataset.attachmentId = id;
        const preview = composer.querySelector('.circle-attachment');
        preview.hidden = false;
        preview.textContent = `${kind === 'recipe' ? 'Recipe' : 'Meal'} attached: ${item.name.replace(/^(recipe|meal) /, '')}`;
        preview.insertAdjacentHTML('beforeend',action('Remove attachment','chat-remove-attachment'));
      },
    });
    circleMentionInstances.push({field, instance});
  }
}

function composerMentions(composer) {
  const item = circleMentionInstances.find(({field}) => field.form === composer);
  return item ? item.instance.getMentions() : [];
}

function resetCircleForm(form) {
  if (!form) return;
  form.reset();
  for (const field of form.querySelectorAll('textarea, input[type="email"]')) field.value = '';
  delete form.dataset.attachmentKind; delete form.dataset.attachmentId;
  const preview = form.querySelector('.circle-attachment');
  if (preview) { preview.hidden = true; preview.textContent = ''; }
  circleMentionInstances = circleMentionInstances.filter(item => {
    if (item.field.form !== form) return true;
    item.instance.destroy(); return false;
  });
  if (form.id === 'circle-message-form') state.circleDrafts.delete(form.dataset.circleId);
  bindCircleMentions();
}

async function sendCircleText(form, body, mentionIds, retry = null) {
  if (!body || body.length > 2000) throw new Error('Enter a message of 1 to 2000 characters');
  const circleId=form.dataset.circleId, generation=state.dataGeneration;
  const pendingId=retry?.id || `pending:${crypto.randomUUID()}`;
  const clientId=retry?.clientId || crypto.randomUUID();
  const replyTo=retry?.replyTo || (state.chatReply?.circleId===circleId ? state.chatReply.id : null);
  const post={id:pendingId,clientId,replyTo,mentionIds,circleId,kind:'message',createdBy:state.session?.user?.id || state.chatProfile?.userId || 'demo',createdByName:'You',createdAt:retry?.createdAt || new Date().toISOString(),snapshot:{text:body},pending:true};
  state.circlePending.set(pendingId,post);
  if(!retry || form.querySelector('textarea').value===body)resetCircleForm(form); state.chatReply=null; form.querySelector('[type="submit"]').disabled=false; render();
  try {
    const sent=await save(`/api/circles/${encodeURIComponent(circleId)}/messages`,'POST',{body,mentionIds,clientId,replyTo});
    if(generation!==state.dataGeneration)return;
    if(state.circleId===circleId)state.circleLoadRequest+=1;
    const cached=state.circleFeeds.get(circleId)||{items:[],nextCursor:null};
    cached.items=[sent,...cached.items.filter(p=>p.id!==sent.id)];cacheCircleFeed(circleId,cached);
    if(state.view==='circles'&&state.circleId===circleId)state.circleFeed=[sent,...state.circleFeed.filter(p=>p.id!==sent.id)];
    state.circlePending.delete(pendingId);
    const room=state.circles.find(c=>c.id===circleId);if(room)room.latest=sent;
  } catch(error) {
    if(generation!==state.dataGeneration)return;
    post.pending=false;post.failed=true;post.error=error.message;state.circlePending.set(pendingId,post);
    if(!form.querySelector('textarea').value){form.querySelector('textarea').value=body;state.circleDrafts.set(circleId,body);}
    showToast(error.message);
  } finally {if(state.view==='circles'&&generation===state.dataGeneration)render();}
}

function safePhotoUrl(value) {
  try {
    const url = new URL(value);
    return url.protocol === 'https:' ? url.href : '';
  } catch { return ''; }
}

function renderPantryPhotos() {
  const photos = state.pantryPhotos;
  let html = '<p class="muted tiny pantry-photo-intro">Compact copies of photos saved with ChatGPT pantry updates.</p>';
  if (photos.length) {
    html += `<div class="pantry-photo-list">${photos.map((photo) => {
      const imageUrl = safePhotoUrl(photo.image_url);
      const observations = arr(photo.observations);
      const date = new Date(photo.created_at);
      const dateLabel = Number.isNaN(date.getTime()) ? 'Date unavailable' : date.toLocaleString();
      const status = photo.status === 'applied' ? 'Added to pantry' : 'Saved for review';
      return `<article class="card pantry-photo-card"><div class="pantry-photo-preview">${imageUrl ? `<img src="${esc(imageUrl)}" alt="Pantry photo saved ${esc(dateLabel)}" loading="lazy" />` : '<span>Photo preview unavailable</span>'}</div><div class="pantry-photo-details"><div class="pantry-photo-heading"><h3>${esc(dateLabel)}</h3><span class="pill">${status}</span></div><p class="muted tiny">${esc(Math.round((Number(photo.image_bytes) || 0) / 1024))} KB saved</p>${photo.note ? `<p>${esc(photo.note)}</p>` : ''}<h4>Items recorded</h4><ul>${observations.map((item) => `<li>${esc(item.name)}${item.quantity != null ? ` — ${esc(item.quantity)} ${esc(item.unit || '')}` : ''}</li>`).join('') || '<li>No items recorded.</li>'}</ul></div></article>`;
    }).join('')}</div>`;
  } else if (state.pantryPhotosLoading) html += '<div class="loading pantry-photo-loading" role="status"><div class="loader"></div><span>Loading pantry photos…</span></div>';
  else if (!state.pantryPhotosError) html += '<p class="muted tiny pantry-photo-empty">No photos have been saved yet. Photos included with future ChatGPT pantry updates will appear here.</p>';
  if (state.pantryPhotosError) html += `<div class="callout" role="alert"><b>Could not load pantry photos</b><p>${esc(state.pantryPhotosError)}</p>${action('Try again', photos.length ? 'load-older-pantry-photos' : 'load-pantry-photos')}</div>`;
  if (photos.length && state.pantryPhotosHasMore && !state.pantryPhotosError) html += `<div class="pantry-photo-more">${state.pantryPhotosLoading ? '<p class="muted tiny" role="status">Loading older photos…</p>' : action('Load older photos', 'load-older-pantry-photos')}</div>`;
  return html;
}

async function loadPantryPhotos(append = false) {
  if (state.pantryPhotosLoading) return;
  const request = ++state.pantryPhotosRequest;
  const householdId = state.activeHouseholdId;
  const offset = append ? state.pantryPhotos.length : 0;
  state.pantryPhotosLoading = true;
  state.pantryPhotosError = null;
  if (!append) state.pantryPhotos = [];
  if (state.view === 'pantry' && state.pantrySection === 'photos') render();
  try {
    const data = await api(`/api/pantry/evidence?limit=30&offset=${offset}`);
    if (request !== state.pantryPhotosRequest || householdId !== state.activeHouseholdId) return;
    state.pantryPhotos = append ? [...state.pantryPhotos, ...arr(data.items)] : arr(data.items);
    state.pantryPhotosHasMore = !!data.hasMore;
  } catch (error) {
    if (request !== state.pantryPhotosRequest || householdId !== state.activeHouseholdId) return;
    state.pantryPhotosError = error.message || 'Please try again.';
  } finally {
    if (request === state.pantryPhotosRequest) {
      state.pantryPhotosLoading = false;
      if (state.view === 'pantry' && state.pantrySection === 'photos') render();
    }
  }
}

function renderFreshness(item) {
  const f = item.freshness || {};
  const age = f.ageDays === null || f.ageDays === undefined ? '' : `Purchased ${f.ageDays === 0 ? 'today' : `${f.ageDays} day${f.ageDays === 1 ? '' : 's'} ago`}`;
  let title = f.useByDate ? (f.daysUntilUseBy < 0 ? 'Past recorded date' : f.daysUntilUseBy === 0 ? 'Use-by today' : f.daysUntilUseBy <= 2 ? `Use in ${f.daysUntilUseBy} days` : 'Recorded use-by') : f.status === 'review_age' ? 'Review first · older produce' : f.isProduce ? (age ? 'No use-by recorded' : 'Purchase age unknown') : 'No date recorded';
  return `<div class="pantry-freshness ${['past_date', 'due_soon', 'review_age'].includes(f.status) ? 'needs-review' : ''}"><strong>${esc(title)}</strong><small>${esc([f.useByDate && f.useByDate, age].filter(Boolean).join(' · '))}</small>${f.isProduce && !age ? `<button type="button" class="pantry-date-link" data-action="edit-pantry" data-id="${esc(item.id)}">Add purchase date</button>` : ''}</div>`;
}

function renderPantry() {
  const items = arr(section('pantry'));
  const visibleItems = items.filter((item) => state.pantryStock === 'all' || (state.pantryStock === 'finished' ? item.quantity === 0 : item.quantity !== 0));
  const query = state.pantrySearch.trim().toLocaleLowerCase();
  const needsReview = (item) => ['past_date', 'due_soon', 'review_age', 'age_unknown'].includes(item.freshness?.status);
  const matches = visibleItems.filter((item) => (!state.pantryReview || needsReview(item)) && (state.pantryCategory === 'all' || (item.category || 'uncategorized') === state.pantryCategory) && item.name.toLocaleLowerCase().includes(query)).sort((a, b) => ({ past_date: 0, due_soon: 1, review_age: 2, age_unknown: 3 }[a.freshness?.status] ?? 4) - ({ past_date: 0, due_soon: 1, review_age: 2, age_unknown: 3 }[b.freshness?.status] ?? 4) || (b.freshness?.ageDays || 0) - (a.freshness?.ageDays || 0));
  let html = `<div class="toolbar pantry-toolbar"><div><p class="muted tiny">Track what is left. Produce age is a planning reminder, not an expiry estimate.</p><input class="search" id="pantry-search" type="search" placeholder="Search pantry items" value="${esc(state.pantrySearch)}" aria-label="Search pantry items" /></div><div class="pantry-toolbar-actions"><button type="button" class="pantry-photo-trigger" data-pantry-section="${state.pantrySection === 'photos' ? 'items' : 'photos'}" aria-expanded="${state.pantrySection === 'photos'}" aria-controls="pantry-photo-panel">${state.pantrySection === 'photos' ? 'Hide photo history' : 'Photo history'}</button>${action('Add pantry item', 'add-pantry', '', 'primary')}</div></div>`;
  if (state.pantrySection === 'photos') html += `<section id="pantry-photo-panel" class="pantry-photo-panel" aria-label="Photo history"><h2>Photo history</h2>${renderPantryPhotos()}</section>`;
  if (sectionStatus('pantry') === 'unavailable') return html + empty('Pantry unavailable', 'Try refreshing this page.');
  html += `<div class="pantry-filters" role="group" aria-label="Pantry stock"><button type="button" class="pantry-filter ${state.pantryStock === 'on-hand' ? 'active' : ''}" data-action="pantry-stock" data-id="on-hand" aria-pressed="${state.pantryStock === 'on-hand'}">On hand <span>${items.filter((item) => item.quantity !== 0).length}</span></button><button type="button" class="pantry-filter ${state.pantryStock === 'finished' ? 'active' : ''}" data-action="pantry-stock" data-id="finished" aria-pressed="${state.pantryStock === 'finished'}">Finished <span>${items.filter((item) => item.quantity === 0).length}</span></button><button type="button" class="pantry-filter ${state.pantryStock === 'all' ? 'active' : ''}" data-action="pantry-stock" data-id="all" aria-pressed="${state.pantryStock === 'all'}">All records</button></div>`;
  html += `<div class="pantry-filters" role="group" aria-label="Pantry categories">${PANTRY_CATEGORIES.filter(([value])=>value==='all'||value===state.pantryCategory||visibleItems.some(item=>(item.category||'uncategorized')===value)).map(([value, title]) => `<button type="button" class="pantry-filter ${state.pantryCategory === value ? 'active' : ''}" data-pantry-category="${value}" aria-pressed="${state.pantryCategory === value}">${title} <span>${value === 'all' ? visibleItems.length : visibleItems.filter((item) => (item.category || 'uncategorized') === value).length}</span></button>`).join('')}</div>`;
  html += `<button type="button" class="pantry-filter ${state.pantryReview ? 'active' : ''}" data-action="review-produce" aria-pressed="${state.pantryReview}">Review produce &amp; dates <span>${visibleItems.filter(needsReview).length}</span></button><details class="pantry-more-filters"><summary>How pantry tracking works</summary><p class="muted tiny">Food carries forward between weeks. Zero amounts move to Finished; restock them when you buy more. Review reminders start at 7 days for produce. Missing purchase dates are shown for follow-up.</p></details>${state.pantrySearch||state.pantryCategory!=='all'||state.pantryReview||state.pantryStock!=='on-hand' ? action('Clear pantry filters','pantry-clear-filters') : ''}`;
  html += `<p class="muted tiny pantry-result-count" role="status">Showing ${matches.length} of ${items.length} items</p>`;
  if (!matches.length) return html + empty(items.length ? 'No matching items' : 'Your pantry is empty', state.pantryStock === 'finished' ? 'Finished items appear here when their remaining amount reaches zero.' : items.length ? 'Try another search, category, or stock view.' : 'Add food you want to keep track of.');
  html += `<div class="card table-card pantry-table"><div class="table-row header"><span>Item</span><span>Remaining</span><span>Location</span><span>Freshness</span><span>Actions</span></div>${matches.map((item) => {
    const quantity = item.quantity === null || item.quantity === undefined ? null : Number(item.quantity);
    const reference = Number(item.reference_quantity);
    const fraction = quantity !== null && reference > 0 ? Math.round(Math.max(0, Math.min(1, quantity / reference)) * 100) : null;
    const meter = fraction === null ? '' : `<div class="pantry-stock" role="meter" aria-label="${esc(item.name)} remaining compared with tracked amount" aria-valuenow="${fraction}" aria-valuemin="0" aria-valuemax="100"><span style="width:${fraction}%"></span></div>`;
    const amountEditor = state.pantryQuantityId === item.id ? `<form class="pantry-inline-form" data-quantity-id="${esc(item.id)}"><label>Remaining<input name="quantity" type="number" min="0" step="0.001" required value="${quantity ?? ''}" aria-label="Remaining ${esc(item.name)}" /></label><label>Unit<input name="unit" value="${esc(item.unit || '')}" aria-label="Unit for ${esc(item.name)}" placeholder="e.g. lb, bag" /></label><div><button class="button primary" type="submit">Save amount</button>${action('Cancel', 'cancel-quantity', item.id)}</div></form>` : `<button type="button" class="pantry-amount-button" data-action="edit-quantity" data-id="${esc(item.id)}" aria-label="Update remaining ${esc(item.name)}">${quantity === null ? 'Set amount' : `${esc(quantity)} ${esc(item.unit || '')} left`} <span aria-hidden="true">✎</span></button>${meter}${quantity !== null && quantity > 0 ? `<div class="pantry-quick-actions">${action('Used half', 'half-pantry', item.id)}${action('Finished', 'finish-pantry', item.id)}</div>` : ''}`;
    return `<div class="table-row" data-pantry-id="${esc(item.id)}"><strong>${esc(item.name)}<small class="pantry-item-category">${esc(PANTRY_CATEGORIES.find(([value]) => value === (item.category || 'uncategorized'))?.[1] || 'Uncategorized')}</small></strong><div class="pantry-quantity">${amountEditor}</div><span class="tiny">${esc(label(pick(item, 'storage_location', 'storageLocation') || 'pantry'))}</span>${renderFreshness(item)}<div class="pantry-actions">${quantity !== null && quantity > 0 ? action('Use', 'use-pantry', item.id, 'primary') : quantity === 0 ? action('Restock', 'restock-pantry', item.id, 'primary') : ''}${action('Edit', 'edit-pantry', item.id)}</div></div>`;
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
  html += `<div class="store-groups">${stores.map((store) => `<article class="card shopping-store"><div class="card-head"><h3>${esc(store)}</h3><span class="pill">${items.filter((item) => (item.store || 'No store selected') === store).length} items</span></div>${items.filter((item) => (item.store || 'No store selected') === store).map((item) => `<div class="check-row ${item.purchased ? 'done' : ''}"><input type="checkbox" data-purchase-id="${esc(item.id)}" aria-label="Mark ${esc(item.name)} purchased" ${item.purchased ? 'checked' : ''} ${item.receivedPantryItemId ? 'disabled' : ''} /><span class="row-copy"><strong>${esc(item.name)}</strong><small>${esc(item.quantity ?? '')} ${esc(item.unit || '')}</small>${arr(item.source?.reasons).length ? `<small>For: ${item.source.reasons.map((reason) => esc(reason.title)).join(', ')}</small>` : ''}${!item.receivedPantryItemId && item.purchased ? '<span class="shopping-state">Purchased · not yet in pantry</span>' : ''}${item.store ? `<span class="pill store-tag" aria-label="Generally buy at ${esc(item.store)}">Usually: ${esc(item.store)}</span>` : ''}</span><div style="display:flex;gap:4px">${item.receivedPantryItemId ? '<span class="shopping-state">Added to pantry</span>' : action('Add to pantry', 'receive-shopping', item.id)}${item.receivedPantryItemId ? '' : action('Edit', 'edit-shopping', item.id) + action('Remove', 'remove-shopping', item.id)}</div></div>`).join('')}</article>`).join('')}</div>`;
  return html;
}

const SIGNAL_GOALS = [['time','Less cooking time'],['stress','Less stress'],['kids_enjoyment','Food the kids enjoy'],['waste','Less waste'],['cost','Lower cost'],['shared_work','Share the work'],['variety','More variety'],['other','Another goal']];
function signalFields() {
  const unknown = [{value:'',label:'Unknown / not reported'}];
  const choices = values => [...unknown,...values.map(([value,label])=>({value,label}))];
  return `<details class="wide signal-details"><summary>Add details, if useful</summary><p class="muted tiny">Only add what you know. Kitchen time includes preparation, cooking and cleanup; effort and stress run from 1 (low) to 5 (high).</p><div class="form-grid">`
    + field('signalGoal','What mattered for this experience?','',{choices:choices(SIGNAL_GOALS),wide:true})
    + field('goalNote','Your goal in your own words (optional)','',{wide:true})
    + field('occurredOn','When did it happen? (optional)','',{type:'date'})
    + field('actualMinutes','Actual kitchen time (minutes) — optional','',{type:'number',min:0,max:1440,step:1})
    + field('effort','Effort (1–5) — optional','',{type:'number',min:1,max:5,step:1})
    + field('stressBefore','Stress before (1–5) — optional','',{type:'number',min:1,max:5,step:1})
    + field('stressAfter','Stress after (1–5) — optional','',{type:'number',min:1,max:5,step:1})
    + field('planStatus','What happened to the plan?','',{choices:choices([['followed','Followed it'],['changed','Changed it'],['skipped','Skipped it'],['not_planned','There was no plan']])})
    + field('actualMeal','What was actually served? (optional)','',{wide:true})
    + field('whoCooked','Who did the kitchen work? (optional)','',{wide:true})
    + field('changeReason','What caused the change? (optional)','',{wide:true})
    + ['kids','adults'].map(audience=>field(audience+'Response',audience==='kids'?"Kids’ response":"Adults’ response",'',{choices:choices([['liked','Liked it'],['mixed','Mixed response'],['disliked','Did not like it'],['not_tried','Did not try it']])})).join('')
    + field('signalContext','Anything affecting this experience?','',{choices:choices([['guests','Guests'],['illness','Illness reported at home'],['late_schedule','Running late'],['travel','Travel'],['school_break','School break'],['missing_ingredient','Missing ingredient'],['equipment_problem','Equipment problem'],['other','Something else']])})
    + field('leftovers','What happened to leftovers?','',{choices:choices([['none','None'],['saved','Saved'],['discarded','Discarded']])})
    + field('wasteQuantity','Food discarded (amount) — optional','',{type:'number',min:0,max:100000,step:0.001})
    + field('wasteUnit','Unit for discarded food','',{choices:choices([['g','Grams'],['kg','Kilograms'],['ml','Milliliters'],['l','Liters'],['portion','Portions'],['item','Items']])})
    + field('actualCost','Actual cost (optional)','',{type:'number',min:0,max:100000,step:0.01})
    + field('currency','Currency for reported cost (e.g. USD)','',{})
    + '</div></details>';
}
function readSignals(data) {
  const s = {}, value = name=>String(data.get(name)||'').trim();
  for(const name of ['goalNote','planStatus','actualMeal','whoCooked','changeReason','leftovers','wasteUnit','currency']) if(value(name))s[name]=value(name);
  if(value('signalGoal'))s.goal=value('signalGoal');
  for(const name of ['actualMinutes','effort','stressBefore','stressAfter','wasteQuantity','actualCost']) if(value(name)!=='')s[name]=Number(value(name));
  if(value('signalContext'))s.context=[value('signalContext')];
  const responses=['kids','adults'].filter(audience=>value(audience+'Response')).map(audience=>({audience,response:value(audience+'Response')}));
  if(responses.length)s.responses=responses;
  return s;
}
function signalSummary(item) {
  const s=item.signals||{}, parts=[];
  if(s.goal)parts.push(SIGNAL_GOALS.find(([key])=>key===s.goal)?.[1]||s.goal);
  if(s.goalNote)parts.push(s.goalNote);
  if(item.occurred_on)parts.push(item.occurred_on);
  if(s.actualMinutes!==undefined)parts.push(`${s.actualMinutes} kitchen minutes reported`);
  if(s.effort!==undefined)parts.push(`Effort ${s.effort}/5`);
  if(s.stressBefore!==undefined)parts.push(`Stress before ${s.stressBefore}/5`);
  if(s.stressAfter!==undefined)parts.push(`Stress after ${s.stressAfter}/5`);
  if(s.planStatus)parts.push(`Plan: ${label(s.planStatus)}`);
  if(s.actualMeal)parts.push(`Served: ${s.actualMeal}`);
  if(s.whoCooked)parts.push(`Kitchen work: ${s.whoCooked}`);
  if(s.changeReason)parts.push(`Change: ${s.changeReason}`);
  for(const r of arr(s.responses))parts.push(`${r.audience}: ${label(r.response)}`);
  if(s.context?.length)parts.push(s.context.map(label).join(', '));
  if(s.leftovers)parts.push(`Leftovers: ${label(s.leftovers)}`);
  if(s.wasteQuantity!==undefined)parts.push(`Discarded: ${s.wasteQuantity} ${s.wasteUnit}`);
  if(s.actualCost!==undefined)parts.push(`Cost: ${s.actualCost} ${s.currency}`);
  return parts.length?`<p class="muted tiny reported-signals">${esc(parts.join(' · '))}</p>`:'';
}

function renderReviews() {
  const feedback = arr(section('feedback'));
  const memories = arr(section('memories'));
  const feedbackUnavailable = sectionStatus('feedback') === 'unavailable';
  let html = `<div class="toolbar review-toolbar"><p class="muted tiny">Capture what went well, what was difficult, and lessons for next time.</p>${feedbackUnavailable ? '' : `<div class="review-actions">${action('Review this week', 'review-week', '', 'primary')}${action('Review a meal', 'add-feedback')}${action('What’s changed at home?', 'add-context-update')}</div>`}</div>`;
  html += `<div class="review-grid"><div class="stack">`;
  html += card('Meal and week reviews', '♡', feedbackUnavailable ? '<p class="muted tiny">Reviews are temporarily unavailable.</p>' : feedback.length ? feedback.map((item) => `<div class="feedback"><div class="feedback-head"><strong>${esc(item.occurrence?.title || item.meal_title || (item.week_start ? `Week of ${item.week_start}` : 'Weekly review'))}</strong><span class="pill">${esc(label(item.feedback_type || item.feedbackType || 'review'))}</span></div><p>${esc(item.note)}</p>${signalSummary(item)}${item.next_time ? `<p class="next">Lesson for next time: ${esc(item.next_time)}</p>` : ''}</div>`).join('') : '<p class="muted tiny">No reviews saved yet. Start with something that worked this week.</p>');
  html += `</div><div class="stack">`;
  html += card('Household memory', '✦', memories.length ? `<div class="stack">${memories.map((item) => `<div class="row"><div class="row-copy"><strong>${esc(item.content)}</strong><small>${esc(label(item.status))} · ${esc(label(item.scope || 'persistent'))}</small></div><div style="display:flex;gap:4px">${item.status === 'suggested' ? action('Confirm', 'confirm-memory', item.id) : ''}${action('Edit', 'edit-memory', item.id)}</div></div>`).join('')}</div>` : '<p class="muted tiny">No saved memories.</p>', `<div style="margin-top:16px">${action('Add memory', 'add-memory')}</div>`);
  html += `<div class="callout"><b>How memory works</b>Meal feedback is evidence from one experience. A household memory becomes a planning default only after you confirm it.</div></div></div>`;
  return html;
}

function renderHouseholdPreferences() {
  const h = household();
  const prefs = h.planningPreferences || {};
  const focus = arr(prefs.focusAreas);
  const restrictions = h.dietaryRestrictions === null || h.dietaryRestrictions === undefined
    ? '' : arr(h.dietaryRestrictions).length ? h.dietaryRestrictions.join(', ') : 'none';
  const stores = arr(h.storePriority).sort((a, b) => a.priority - b.priority).map((item) => item.store).join(', ');
  const focusChoices = FOCUS.map((area) => `<label class="planning-choice"><input type="checkbox" name="focusAreas" value="${area}" ${focus.includes(area) ? 'checked' : ''} /><span>${esc(label(area))}</span></label>`).join('');
  return `    <article class="card"><div class="card-head"><h3>Household preferences</h3><span class="card-icon">⚙</span></div>
      <form id="settings-form" class="form-grid">
        ${field('householdSize', 'People in household', h.householdSize ?? '', { type: 'number', min: 1, max: 30, required: true })}
        ${field('weeknightMaxMinutes', 'Maximum weeknight cooking minutes', prefs.weeknightMaxMinutes ?? '', { type: 'number', min: 1, max: 240, required: true })}
        ${field('dietaryRestrictions', 'Dietary restrictions — enter none if there are none', restrictions, { required: true, wide: true })}
        ${field('stores', 'Preferred stores, in order', stores, { required: true, wide: true, placeholder: 'Costco, Safeway' })}
        <fieldset class="field wide planning-field"><legend>Planning areas</legend><div class="planning-areas">${focusChoices}</div></fieldset>
        <label class="field wide toggle-field"><span>Plan dinner leftovers for lunch</span><input name="leftoversForLunch" type="checkbox" ${prefs.leftoversForLunch ? 'checked' : ''} /></label>
        <div class="field wide"><button class="button primary" type="submit">Save preferences</button></div>
      </form>
    </article>
    <article class="card"><div class="card-head"><h3>Meal slots</h3>${action('Edit meal slots', 'edit-meal-slots')}</div><p class="muted tiny">${mealSlots().map((slot) => `${esc(slot.name)}${slot.enabled ? '' : ' (disabled)'}`).join(' → ')}</p></article>
`;
}

function renderPlanPreferences() {
  if (state.ruleRevisionId) return renderPlanningRules();
  const notes = state.schedule?.notes;
  return `<div class="section-head"><div><h2>Preferences</h2><p>Set your everyday defaults here. Add temporary changes in this week’s notes.</p></div></div>
    <div class="preferences-grid">${renderHouseholdPreferences()}</div>
    ${card(`This week · ${state.weekStart}`, '▦', `<p class="planning-text">${esc(notes || 'No changes for this week.')}</p>`, action('Edit notes', 'edit-week-notes'))}
    ${renderPlanningRules()}`;
}

function renderSettings() {
  const { order, hidden } = dashboardLayout();
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
  const householdsCard = state.client ? `<article class="card" id="settings-households"><div class="card-head"><h3>Your households</h3><span class="card-icon">⌂</span></div>
    <p class="muted tiny">Switch the household used for planning, pantry and shopping here and in MCP.</p>
    <div class="household-picker"><span id="household-choice-label">Active household</span><div id="household-choice">${MealPrepChoices.markup({name:'householdId',inputId:'household-select',labelId:'household-choice-label',value:state.activeHouseholdId,choices:state.households.map(item=>({value:item.id,label:`${item.name} · ${label(item.role)}`}))})}</div></div>
    <div class="stack" style="margin:16px 0">${state.households.map((item) => row(item.name, `${label(item.role)}${item.id === state.activeHouseholdId ? ' · Active' : ''}`)).join('')}</div>
    <form id="create-household-form" class="invite-form"><label for="new-household-name">Create another household</label><input id="new-household-name" name="name" maxlength="120" required placeholder="Household name" /><button class="button primary" type="submit">Create household</button></form>
    ${state.access?.role && state.access.role !== 'owner' ? `<div style="margin-top:16px">${action('Leave this household', 'leave-household', '', 'danger')}</div>` : ''}
  </article>` : '';
  return `<div class="settings-grid"><div class="stack">
    ${renderHouseholdPreferences()}
    <article class="card"><div class="card-head"><h3>Dashboard cards</h3><span class="card-icon">▦</span></div>
      <p class="muted tiny" style="margin-bottom:14px">Choose the cards and order under “More from your household” and in the chat dashboard.</p>
      <form id="dashboard-form" class="stack">${cardRows}<button class="button ghost" type="submit">Save dashboard</button></form>
    </article>
  </div><div class="stack">
    ${householdsCard}
    ${accessCard}
    <article class="card"><h3>Your chat profile</h3><form id="chat-profile-form" class="circle-form"><label for="chat-profile-name">Display name</label><input id="chat-profile-name" name="name" value="${esc(state.chatProfile?.name || '')}" maxlength="60" required /><button type="submit" class="button primary">Save display name</button></form></article>
    <article class="card"><div class="card-head"><h3>Your session</h3><span class="card-icon">○</span></div><p class="muted tiny" style="margin-bottom:15px">${esc(state.session?.user?.email || 'Local demo mode')}</p>${state.client ? action('Sign out', 'sign-out', '', 'danger') : '<p class="muted tiny">Demo data resets when the local server restarts.</p>'}</article>
  </div></div>`;
}

function render() {
  if (recipeBrowser) { state.browserUi = recipeBrowser.snapshot(); recipeBrowser.destroy(); recipeBrowser = null; }

  document.querySelector('#view-title').textContent = TITLES[state.view] || 'Overview';
  document.querySelector('#view-eyebrow').textContent = state.view === 'overview' ? 'Your household' : 'Meal Prep';
  document.querySelectorAll('[data-view]').forEach((button) => button.classList.toggle('active', button.dataset.view === state.view));
  if (!state.snapshot) return;
  const required = VIEW_SECTIONS[state.view] || [];
  if (state.view !== 'overview' && required.some((name) => !sectionStatus(name) || sectionStatus(name) === 'loading')) {
    content.innerHTML = `<div class="section-loading" role="status"><span class="loader"></span>Loading ${esc(TITLES[state.view].toLowerCase())}…</div>`;
    return;
  }
  if (state.view !== 'overview' && required.some((name) => sectionStatus(name) === 'unavailable')) {
    content.innerHTML = empty(`Could not load ${TITLES[state.view].toLowerCase()}`, 'Please try again.') + action('Try again', 'retry-view');
    return;
  }
  const views = { overview: renderOverview, plan: renderPlan, recipes: renderRecipes, pantry: renderPantry, shopping: renderShopping, reviews: renderReviews, circles: renderCircles, settings: renderSettings, notifications: renderNotifications };
  document.body.classList.toggle('chat-view',state.view==='circles');
  if(state.view!=='circles')ChatLive.stop();
  const markup = views[state.view]?.() || renderOverview();
  if (state.view === 'circles') CircleUI.update(content, markup);
  else content.innerHTML = markup;
  if(state.view==='circles')bindChatBehavior();
  circleMentionInstances = circleMentionInstances.filter(item => {
    if (item.field.isConnected) return true;
    item.instance.destroy(); return false;
  });
  const browserRoot = content.querySelector('#recipe-browser');
  if (browserRoot) recipeBrowser = new RecipeBrowser(browserRoot, {
    load: (ui) => api(`/api/recipe-library?${recipeSearchParams(ui)}`),
    mealCard: savedMealCard,
    onChanged: (ui) => { state.browserUi = ui; writeRoute('replace'); },
    openRecipe: (id) => handleAction('open-recipe', id).catch(error => showToast(error.message)),
    graph: {
      load: (ui) => api(`/api/recipe-graph?${recipeSearchParams(ui)}`),
      save: (relationship) => save('/api/recipe-relationships', 'PUT', relationship),
      remove: (id) => api(`/api/recipe-relationships/${encodeURIComponent(id)}`, { method: 'DELETE' }),
    },
  }, state.browserUi);
  if (state.view === 'circles') bindCircleMentions();
}

function recipeSearchParams(ui) {
  const params = new URLSearchParams({query: ui.query || '', limit: ui.itemType === 'meals' ? '50' : '25', item_type: ui.itemType || 'all', offset: String(ui.offset || 0)});
  for (const [kind, values] of Object.entries(ui.filters || {})) values.forEach(value => params.append(kind, value));
  if (ui.maxMinutes) params.set('max_minutes', ui.maxMinutes);
  return params;
}

function view(name, historyMode = 'push') {
  if (name === 'pantry' && state.view !== 'pantry') state.pantrySection = 'items';
  if (name === 'overview') state.weekStart = monday();
  state.view = name;
  state.planTab = 'plan';
  state.ruleRevisionId = null;
  state.rulePreview = null;
  state.rulePreviewError = null;
  state.recipe = null;
  state.shareUrl = null;
  state.shareId = null;
  state.circleShareId = null;
  state.circleDetail = null;
  if (name === 'circles') { state.circleId = null; state.circleHub = 'home'; }
  writeRoute(historyMode);
  loadViewData().catch((error) => showToast(error.message));
  window.scrollTo({ top: 0, behavior: 'smooth' });
}

function openPantrySection(section) {
  if (section !== 'items' && section !== 'photos') return;
  state.pantrySection = section;
  writeRoute();
  render();
  if (section === 'photos') loadPantryPhotos();
}

function field(name, title, value = '', options = {}) {
  if (options.choices) {
    const choices = options.choices.map((choice) => typeof choice === 'string' ? { value: choice, label: label(choice) } : choice);
    const fieldId = `choice-${name}`;
    return `<div class="field ${options.wide ? 'wide' : ''}"><span id="${esc(fieldId)}-label">${esc(title)}</span>
      ${MealPrepChoices.markup({ name, value, choices, labelId: `${fieldId}-label` })}</div>`;
  }
  const input = options.type === 'textarea'
    ? `<textarea name="${esc(name)}" ${options.required ? 'required' : ''} placeholder="${esc(options.placeholder || '')}">${esc(value)}</textarea>`
    : `<input name="${esc(name)}" type="${esc(options.type || 'text')}" value="${esc(value)}" ${options.required ? 'required' : ''} ${options.min !== undefined ? `min="${options.min}"` : ''} ${options.max !== undefined ? `max="${options.max}"` : ''} ${options.step !== undefined ? `step="${options.step}"` : ''} placeholder="${esc(options.placeholder || '')}" />`;
  return `<label class="field ${options.wide ? 'wide' : ''}">${esc(title)}${input}</label>`;
}

function plannedRecipeRow(part = null, index = -1, position = 0) {
  const key = index < 0 ? `new-${crypto.randomUUID()}` : String(index);
  const name = position === 0 ? 'plannedRecipeId' : `plannedRecipeId-${key}`;
  const current = part?.recipeId || '';
  const choices = [{value: '', label: 'Choose a recipe or ready food'}, ...state.mealRecipes.map(recipe => ({value: recipe.id, label: `${recipe.title}${recipe.kind === 'ready_food' ? ' · Ready food' : ''}`}))];
  if (current && !choices.some(choice => choice.value === current)) choices.push({value: current, label: `${part.recipeSnapshot?.title || part.name} · No longer in library`});
  const title = part?.recipeSnapshot?.title || part?.name || '';
  return `<div class="planned-recipe-row wide" data-planned-recipe="${esc(key)}" data-planned-field="${esc(name)}">${field(name, position ? `Recipe or ready food ${position + 1}` : 'Recipe or ready food', current, {wide: true, choices})}<div class="planned-recipe-actions"><a class="text-button planned-recipe-open" href="${current ? `/app?view=recipes&recipe=${encodeURIComponent(current)}` : '#'}" target="_blank" rel="noopener" ${current ? '' : 'hidden'}>Open in library to edit</a><button type="button" class="text-button" data-editor-action="remove-planned-recipe" aria-label="Remove ${esc(title || 'this food')} from planned meal">Remove</button></div></div>`;
}

function componentEditor(item = {}) {
  const key = item.id || crypto.randomUUID();
  const source = item.source || 'ready';
  const reusable = state.editor?.kind === 'library-meal';
  const recipes = reusable ? state.mealRecipes : arr(section('recipes'));
  const sources = [{ value: 'ready', label: 'Bought / ready food' }, { value: 'cook', label: 'Cook a recipe' }, ...(!reusable ? [{ value: 'task', label: 'From a task' }] : []), { value: 'external', label: 'Takeout / eating out' }];
  const choices = (rows, title) => [{ value: '', label: title }, ...rows];
  return `<div class="component-row form-grid" data-component="${key}">${field(`${key}-name`, 'Food or dish', item.name, {wide: true, required: reusable})}${field(`${key}-quantity`, 'Amount', item.quantity, {type: 'number', min: 0.001, step: 0.001})}${field(`${key}-unit`, 'Unit', item.unit)}${field(`${key}-source`, 'Where it comes from', source, {choices: sources})}${field(`${key}-action`, 'Preparation', item.action || 'serve', {choices: [{value: 'serve', label: 'Serve'}, {value: 'heat', label: 'Heat'}, {value: 'cook', label: 'Cook'}]})}<div class="wide component-reference" data-library-reference ${['cook','ready'].includes(source) ? '' : 'hidden'}>${field(`${key}-recipeId`, 'Recipe', item.recipeId, {choices: choices(recipes.map(row => ({value: row.id, label: `${row.title}${row.kind === 'ready_food' ? ' · Ready food' : ''}`})), 'Choose a recipe')})}</div>${reusable ? '' : `<div class="wide component-reference" data-source="ready" ${source === 'ready' ? '' : 'hidden'}>${field(`${key}-pantryItemId`, 'Pantry item (optional)', item.pantryItemId, {choices: choices(arr(section('pantry')).map(row => ({value: row.id, label: `${row.name} · ${row.quantity ?? '?'} ${row.unit || ''}`})), 'No pantry link')})}</div><div class="wide component-reference" data-source="task" ${source === 'task' ? '' : 'hidden'}>${field(`${key}-taskId`, 'Prepared by', item.taskId, {choices: choices(arr(state.plan?.tasks).map(row => ({value: row.id, label: row.title})), 'Choose a task')})}</div>`}${field(`${key}-notes`, 'Notes for this food', item.notes, {wide: true})}<button type="button" class="button ghost small" data-editor-action="remove-row">Remove food</button></div>`;
}

function readComponents(data) {
  return [...fields.querySelectorAll('[data-component]')].map(row => {
    const key = row.dataset.component;
    const read = name => String(data.get(`${key}-${name}`) || '').trim();
    const source = read('source');
    return {id: key, name: read('name'), quantity: numberOrNull(read('quantity')), unit: read('unit'), source, action: read('action'), recipeId: ['cook','ready'].includes(source) ? read('recipeId') || null : null, pantryItemId: source === 'ready' ? read('pantryItemId') || null : null, taskId: source === 'task' ? read('taskId') || null : null, notes: read('notes')};
  }).filter(row => row.name || row.recipeId || row.pantryItemId || row.taskId || row.quantity !== null);
}

function slotEditor(slot) {
  return `<div class="slot-editor-row" data-slot-id="${esc(slot.id)}">${field(`${slot.id}-name`, 'Slot name', slot.name, { required: true })}<label class="check-row"><input type="checkbox" name="${esc(slot.id)}-enabled" ${slot.enabled ? 'checked' : ''} />Enabled</label><div><button type="button" class="button ghost small" data-editor-action="slot-up" aria-label="Move ${esc(slot.name)} up">↑</button><button type="button" class="button ghost small" data-editor-action="slot-down" aria-label="Move ${esc(slot.name)} down">↓</button></div></div>`;
}

function nutritionProfileEditor(profile = {}) {
  const key = crypto.randomUUID();
  return `<div class="nutrition-editor-row form-grid" data-nutrition-profile="${key}">${field(`${key}-name`, 'Variation name', profile.name, {required: true, placeholder: 'e.g. Tasty, Decadent, Heart healthy'})}${field(`${key}-serving`, 'What changes in this variation?', profile.serving, {type: 'textarea', required: true, wide: true})}<details class="wide variation-nutrition-editor" ${MealNutrition.hasNutrition(profile) ? 'open' : ''}><summary>Nutrition (optional)</summary><div class="form-grid">${Object.entries(MealNutrition.macros).map(([id, title]) => field(`${key}-${id}`, `${title} amount`, profile.macros?.[id] || 'unknown', {choices: Object.entries(MealNutrition.labels).map(([value, label]) => ({value, label}))})).join('')}${field(`${key}-portion`, 'Portion for numeric values', profile.portion, {wide: true, placeholder: 'e.g. 1 bowl: 100 g noodles + 150 g tofu'})}${field(`${key}-valueType`, 'Number source', profile.valueType || 'estimated', {choices: [{value: 'estimated', label: 'Estimated'}, {value: 'label', label: 'From label'}]})}${Object.entries({calories: 'Calories (kcal)', ...Object.fromEntries(Object.entries(MealNutrition.macros).map(([id, name]) => [id, `${name} (g)`]))}).map(([id, name]) => field(`${key}-number-${id}`, name, profile.amounts?.[id], {type: 'number', min: 0, step: 0.001, placeholder: 'Unknown'})).join('')}${field(`${key}-micros`, 'Micronutrients — one per line: nutrient | food source | amount | unit (g, mg, mcg)', arr(profile.micronutrients).map(m => `${m.nutrient} | ${m.source}${m.amount == null ? '' : ` | ${m.amount} | ${m.unit}`}`).join('\n'), {type: 'textarea', wide: true})}</div></details><button type="button" class="button ghost small" data-editor-action="remove-nutrition">Remove variation</button></div>`;
}

function nutritionEditor(nutrition) {
  return `<section class="wide"><h3>Recipe variations (optional)</h3><p class="muted tiny">Describe versions of this recipe, such as Tasty, Decadent, Heart healthy or Protein-heavy. Nutrition is optional; record a basis only when adding nutrient guidance or numbers.</p>${field('nutrition-basis', 'Nutrition basis / assumptions', nutrition?.basis, {type: 'textarea', wide: true})}<div id="nutrition-rows">${arr(nutrition?.profiles).map(nutritionProfileEditor).join('')}</div><button type="button" class="button ghost small" data-editor-action="add-nutrition">Add variation</button></section>`;
}

function readNutrition(data) {
  const rows = [...fields.querySelectorAll('[data-nutrition-profile]')];
  if (!rows.length) return null;
  const value = name => String(data.get(name) || '').trim();
  return {basis: value('nutrition-basis'), profiles: rows.map(row => {
    const key = row.dataset.nutritionProfile;
    const numeric = name => {const raw = value(name); return raw === '' ? null : Number.isFinite(Number(raw)) ? Number(raw) : raw;};
    return {portion: value(`${key}-portion`), valueType: value(`${key}-valueType`), amounts: Object.fromEntries(['calories', ...Object.keys(MealNutrition.macros)].map(id => [id, numeric(`${key}-number-${id}`)])), name: value(`${key}-name`), serving: value(`${key}-serving`), macros: Object.fromEntries(Object.keys(MealNutrition.macros).map(id => [id, value(`${key}-${id}`)])), micronutrients: value(`${key}-micros`).split('\n').filter(line => line.trim()).map(line => {const [nutrient, source = '', raw = '', unit = ''] = line.split('|').map(part => part.trim()); return {nutrient, source, amount: raw === '' ? null : Number.isFinite(Number(raw)) ? Number(raw) : raw, unit};})};
  })};
}

function stockInputEditor(input = {}) {
  const key = crypto.randomUUID();
  const stock = arr(section('pantry')).find((row) => row.id === input.itemId);
  return `<div class="stock-editor-row form-grid" data-stock-input="${key}">${field(`${key}-itemId`, 'Pantry food', input.itemId, { choices: [{ value: '', label: 'Choose pantry food' }, ...arr(section('pantry')).map((row) => ({ value: row.id, label: `${row.name} · ${row.quantity ?? '?'} ${row.unit || ''} left` }))] })}${field(`${key}-quantity`, 'Actual amount used', input.quantity, { type: 'number', min: 0.001, step: 0.001, required: true })}<p class="wide tiny stock-input-unit">${stock ? `Amounts in ${esc(stock.unit || 'the pantry item’s unit')}` : 'Choose food to see its tracked unit.'}</p><button type="button" class="button ghost small" data-editor-action="remove-row">Remove food used</button></div>`;
}

function stockOutputEditor(output = {}) {
  const key = crypto.randomUUID();
  return `<div class="stock-editor-row form-grid" data-stock-output="${key}">${field(`${key}-name`, 'Prepared food name', output.name, { required: true, wide: true })}${field(`${key}-quantity`, 'Actual quantity remaining', output.quantity, { type: 'number', min: 0.001, step: 0.001, required: true })}${field(`${key}-unit`, 'Output unit', output.unit, { required: true })}${field(`${key}-location`, 'Storage location', output.storageLocation || 'fridge', { choices: ['pantry', 'fridge', 'freezer', 'other'] })}<button type="button" class="button ghost small" data-editor-action="remove-row">Remove prepared food</button></div>`;
}

fields.addEventListener('click', async (event) => {
  const button = event.target.closest('[data-editor-action]');
  if (!button) return;
  event.preventDefault();
  const action = button.dataset.editorAction;
  if (action === 'select-plan-food') {
    const selected = arr(state.editor?.results).find((row) => row.id === button.dataset.id && row.itemType === button.dataset.itemType);
    if (!selected) return;
    if (state.editor.combining) {
      if (selected.itemType === 'meals' || state.editor.selectedFoods.length >= 10 ||
          state.editor.selectedFoods.some((food) => food.id === selected.id)) return;
      state.editor.selectedFoods.push(selected);
      fields.querySelector('#plan-food-search').value = '';
      updatePlanFoodSelection();
      await updatePlanFoodResults();
    } else {
      state.editor.selectedFoods = [selected];
      fields.querySelector('[name="servings"]').value = selected.servings || 1;
      fields.querySelector('[name="notes"]').value = selected.itemType === 'meals' ? selected.notes || '' : '';
      fields.querySelector('#plan-food-results').innerHTML = '';
      updatePlanFoodSelection();
    }
    return;
  }
  if (action === 'combine-plan-food') {
    state.editor.combining = true;
    fields.querySelector('#plan-food-search').value = '';
    updatePlanFoodSelection();
    await updatePlanFoodResults();
    fields.querySelector('#plan-food-search').focus();
    return;
  }
  if (action === 'advanced-library-meal') {
    await loadMealRecipes();
    return openEditor('library-meal');
  }
  if (action === 'remove-plan-food') {
    state.editor.selectedFoods = state.editor.selectedFoods.filter((food) => food.id !== button.dataset.id);
    if (!state.editor.selectedFoods.length) state.editor.combining = false;
    updatePlanFoodSelection();
    await updatePlanFoodResults();
    return;
  }
  if (action === 'add-planned-recipe') {
    const rows = fields.querySelectorAll('[data-planned-recipe]');
    if (rows.length >= 10) {
      document.querySelector('#dialog-error').textContent = 'A planned meal can include at most 10 recipes or ready foods.';
      return;
    }
    fields.querySelector('#planned-recipe-rows').insertAdjacentHTML('beforeend', plannedRecipeRow(null, -1, rows.length));
    fields.querySelector('#planned-recipe-rows [data-planned-recipe]:last-child .choice-trigger').focus();
    return;
  }
  if (action === 'remove-planned-recipe') {
    button.closest('[data-planned-recipe]').remove();
    return;
  }
  if (action === 'add-nutrition') fields.querySelector('#nutrition-rows').insertAdjacentHTML('beforeend', nutritionProfileEditor());
  if (action === 'remove-nutrition') button.closest('[data-nutrition-profile]').remove();
  if (action === 'add-component') fields.querySelector('#component-rows').insertAdjacentHTML('beforeend', componentEditor());
  if (action === 'add-slot') fields.querySelector('#slot-rows').insertAdjacentHTML('beforeend', slotEditor({ id: crypto.randomUUID(), name: '', enabled: true }));
  if (action === 'add-stock-input') fields.querySelector('#stock-inputs').insertAdjacentHTML('beforeend', stockInputEditor());
  if (action === 'add-stock-output') fields.querySelector('#stock-outputs').insertAdjacentHTML('beforeend', stockOutputEditor());
  if (action === 'remove-row') button.closest('[data-component], [data-stock-input], [data-stock-output]').remove();
  const slot = button.closest('[data-slot-id]');
  if (action === 'slot-up' && slot.previousElementSibling) slot.previousElementSibling.before(slot);
  if (action === 'slot-down' && slot.nextElementSibling) slot.nextElementSibling.after(slot);
});

function updatePlanFoodSelection() {
  if (!['plan-search', 'library-combine'].includes(state.editor?.kind)) return;
  const foods = state.editor.selectedFoods;
  fields.querySelector('#plan-food-selection').textContent = foods.length === 1
    ? `${foods[0].itemType === 'meals' ? 'Saved meal' : foods[0].itemType === 'ready_food' ? 'Ready food' : 'Recipe'}: ${foods[0].title || foods[0].name}`
    : foods.length > 1 ? `${foods.length} recipes and ready foods combined` : '';
  fields.querySelector('#plan-food-selected').innerHTML = state.editor.combining
    ? foods.map((food) => `<div class="plan-food-selected-row"><span>${esc(food.title || food.name)} <small>· ${food.itemType === 'ready_food' ? 'Ready food' : 'Recipe'}</small></span><button type="button" class="button ghost small" data-editor-action="remove-plan-food" data-id="${esc(food.id)}" aria-label="Remove ${esc(food.title || food.name)}">Remove</button></div>`).join('') : '';
  fields.querySelector('#combine-plan-food').hidden = state.editor.combining || foods.length !== 1 || foods[0].itemType === 'meals';
  document.querySelector('#dialog-save').disabled = foods.length < (state.editor.kind === 'library-combine' ? 2 : 1);
}

async function updatePlanFoodResults() {
  if (!['plan-search', 'library-combine'].includes(state.editor?.kind)) return;
  const query = fields.querySelector('#plan-food-search')?.value.trim() || '';
  const request = ++state.editor.searchRequest;
  const resultBox = fields.querySelector('#plan-food-results');
  if (state.editor.combining && state.editor.selectedFoods.length >= 10) {
    resultBox.innerHTML = '<p class="muted tiny">A meal can include up to 10 recipes or ready foods.</p>';
    return;
  }
  resultBox.innerHTML = '<p class="muted tiny">Searching your library…</p>';
  try {
    const result = await api(`/api/recipe-library?item_type=all&limit=25&query=${encodeURIComponent(query)}`);
    if (!['plan-search', 'library-combine'].includes(state.editor?.kind) || request !== state.editor.searchRequest) return;
    state.editor.results = arr(result.items).filter((item) => !state.editor.combining ||
      (item.itemType !== 'meals' && !state.editor.selectedFoods.some((food) => food.id === item.id)));
    resultBox.innerHTML = state.editor.results.length ? state.editor.results.map((item) => `<button type="button" class="plan-food-result" data-editor-action="select-plan-food" data-id="${esc(item.id)}" data-item-type="${esc(item.itemType)}"><strong>${esc(item.title || item.name)}</strong><small>${item.itemType === 'meals' ? 'Saved meal' : item.itemType === 'ready_food' ? 'Ready food' : 'Recipe'} · ${esc(item.servings || 1)} servings</small></button>`).join('') : '<p class="muted tiny">No matching library items. Add a recipe or ready food in the library first.</p>';
  } catch (error) {
    if (['plan-search', 'library-combine'].includes(state.editor?.kind) && request === state.editor.searchRequest) resultBox.innerHTML = `<p class="form-error" role="alert">${esc(error.message || 'Could not search the library.')}</p>`;
  }
}

fields.addEventListener('input', (event) => {
  if (event.target.id !== 'plan-food-search' || !['plan-search', 'library-combine'].includes(state.editor?.kind)) return;
  if (!state.editor.combining) {
    state.editor.selectedFoods = [];
    updatePlanFoodSelection();
  }
  clearTimeout(state.editor.searchTimer);
  state.editor.searchTimer = setTimeout(updatePlanFoodResults, 180);
});

fields.addEventListener('change', (event) => {
  const planned = event.target.closest('[data-planned-recipe]');
  if (planned && event.target.name === planned.dataset.plannedField) {
    const link = planned.querySelector('.planned-recipe-open');
    link.hidden = !event.target.value;
    if (event.target.value) link.href = `/app?view=recipes&recipe=${encodeURIComponent(event.target.value)}`;
  }
  const row = event.target.closest('[data-component]');
  if (row) {
    const key = row.dataset.component;
    if (event.target.name === `${key}-source`) {
      row.querySelector('[data-library-reference]').hidden = !['ready','cook'].includes(event.target.value);
      row.querySelectorAll('[data-source]').forEach((field) => { field.hidden = field.dataset.source !== event.target.value; });
    }
    const name = row.querySelector(`[name="${key}-name"]`);
    if (event.target.name === `${key}-recipeId`) {
      const recipe = (state.editor?.kind === 'library-meal' ? state.mealRecipes : arr(section('recipes'))).find(item => item.id === event.target.value);
      if (recipe) {
        const source = recipe.kind === 'ready_food' ? 'ready' : 'cook';
        MealPrepChoices.setValue(row.querySelector(`[name="${key}-source"]`).closest('[data-choice-control]'), source);
        MealPrepChoices.setValue(row.querySelector(`[name="${key}-action"]`).closest('[data-choice-control]'), source === 'cook' ? 'cook' : 'serve');
        row.querySelectorAll('[data-source]').forEach(field => { field.hidden = field.dataset.source !== source; });
      }
      if (recipe && !name.value) name.value = recipe.title;
      if (recipe && recipe.kind !== 'ready_food' && !row.querySelector(`[name="${key}-unit"]`).value) row.querySelector(`[name="${key}-unit"]`).value = 'servings';
    }
    if (event.target.name === `${key}-pantryItemId`) {
      const stock = arr(section('pantry')).find((item) => item.id === event.target.value);
      if (stock && !name.value) name.value = stock.name;
      if (stock && !row.querySelector(`[name="${key}-unit"]`).value) row.querySelector(`[name="${key}-unit"]`).value = stock.unit || '';
    }
  }
  const input = event.target.closest('[data-stock-input]');
  if (input && event.target.name.endsWith('-itemId')) {
    const stock = arr(section('pantry')).find((row) => row.id === event.target.value);
    input.querySelector('.stock-input-unit').textContent = stock ? `Amounts in ${stock.unit || 'the pantry item’s unit'}` : 'Choose pantry food.';
  }
});

function openEditor(kind, item = null, selectedDate = null) {
  if (state.editor?.searchTimer) clearTimeout(state.editor.searchTimer);
  state.editor = { kind, item, feedbackId: crypto.randomUUID() };
  errorBox.hidden = true;
  let title, markup;
  if (kind === 'recipe') {
    title = item ? 'Edit recipe' : 'Add recipe';
    markup = field('kind', 'Library type', item?.kind || 'recipe', {choices: [{value: 'recipe', label: 'Recipe'}, {value: 'ready_food', label: 'Ready food'}]}) + field('title', 'Recipe name', item?.title, { required: true, wide: true }) + field('description', 'Description', item?.description, { type: 'textarea', wide: true }) + field('servings', 'Servings', item?.servings || 4, { type: 'number', min: 1 }) + field('totalMinutes', 'Total minutes', item?.total_minutes ?? item?.totalMinutes, { type: 'number', min: 1 }) + field('activeMinutes', 'Active minutes', item?.active_minutes ?? item?.activeMinutes, { type: 'number', min: 1 }) + field('tags', 'Tags, separated by commas', joinNames(item?.tags), { wide: true }) + ['cuisines','eating_goals','meal_types','diets'].map((key, index) => field(key, ['Cuisines','Eating goals (e.g. protein rich)','Meals (e.g. dinner)','Diets (e.g. vegetarian)'][index] + ', separated by commas', joinNames(item?.[key]), { wide: true })).join('') + field('ingredients', 'Ingredients — one per line: name | quantity | unit', arr(item?.ingredients).map((entry) => typeof entry === 'string' ? entry : `${entry.name || ''} | ${entry.quantity ?? ''} | ${entry.unit || ''}`).join('\n'), { type: 'textarea', wide: true }) + field('instructions', 'Instructions — one step per line', arr(item?.instructions).map((entry) => typeof entry === 'string' ? entry : entry.text || entry.instruction || '').join('\n'), { type: 'textarea', wide: true }) + field('sourceUrl', 'Source URL', item?.source_url || item?.sourceUrl, { type: 'url', wide: true });
    markup += nutritionEditor(item?.nutrition);
  } else if (kind === 'library-combine') {
    title = 'Combine recipes and ready food';
    markup = `<div class="wide plan-food-picker"><label class="field">Find a recipe or ready food<input id="plan-food-search" type="search" autocomplete="off" placeholder="Search your food library" /></label><div id="plan-food-results" class="plan-food-results" role="group" aria-label="Food search results"></div><p id="plan-food-selection" class="plan-food-selection" role="status"></p><div id="plan-food-selected"></div><button id="combine-plan-food" type="button" hidden></button></div>` + field('servings', 'Default servings', 4, {type: 'number', min: 0.001, step: 0.001, required: true}) + field('notes', 'Notes', '', {type: 'textarea', wide: true}) + '<p class="wide muted tiny">Choose at least two library foods. The combination will use their names and stay available for future weeks.</p><button type="button" class="button ghost small wide" data-editor-action="advanced-library-meal">Advanced meal details</button>';
    state.editor.searchRequest = 0;
    state.editor.results = [];
    state.editor.selectedFoods = [];
    state.editor.combining = true;
  } else if (kind === 'library-meal') {
    title = item?.id ? 'Edit saved meal' : 'Save meal';
    markup = field('name', 'Meal name', item?.name, {required: true, wide: true}) + field('servings', 'Default servings', item?.servings || 4, {type: 'number', min: 0.001, step: 0.001, required: true}) + `<p class="muted tiny">Amounts below are for these servings. They scale when you plan the meal.</p>` + field('notes', 'Notes', item?.notes, {type: 'textarea', wide: true}) + `<section class="wide editor-components"><h3>What’s in this meal?</h3><p class="muted tiny">Combine recipes and ready food. For a recipe, use servings as its unit. Link pantry food and prep tasks after adding this meal to a week.</p><div id="component-rows">${(item?.components?.length ? item.components : [{}]).map(componentEditor).join('')}</div><button type="button" class="button ghost small" data-editor-action="add-component">Add food</button></section>`;
  } else if (kind === 'plan-search') {
    title = 'Add meal to plan';
    const slots = mealSlots().filter((slot) => slot.enabled);
    markup = `<div class="wide plan-food-picker"><label class="field">Find a recipe or ready food<input id="plan-food-search" type="search" autocomplete="off" placeholder="Search your food library" /></label><div id="plan-food-results" class="plan-food-results" role="group" aria-label="Food search results"></div><p id="plan-food-selection" class="plan-food-selection" role="status"></p><div id="plan-food-selected"></div><button id="combine-plan-food" type="button" class="button ghost small" data-editor-action="combine-plan-food" hidden>Add another recipe or ready food</button></div>` + field('date', 'Day', item?.date || state.weekStart, {type: 'date', required: true}) + field('slot', 'Meal slot', slots.find((slot) => slot.id === 'dinner')?.id || slots[0]?.id, {choices: slots.map((slot) => ({value: slot.id, label: slot.name}))}) + field('servings', 'People / servings', '', {type: 'number', min: 0.001, step: 0.001, required: true}) + field('notes', 'Notes for this time', '', {type: 'textarea', wide: true}) + '<p class="wide muted tiny">Recipes and ready food stay in your library. This adds them together to one dated plan entry.</p>';
    state.editor.searchRequest = 0;
    state.editor.results = [];
    state.editor.selectedFoods = [];
    state.editor.combining = false;
  } else if (kind === 'plan-library') {
    title = 'Plan a saved meal';
    const slots = mealSlots().filter(slot => slot.enabled);
    markup = `<div class="wide library-plan-summary"><h3>${esc(item.name)}</h3><ul class="meal-components">${componentSummary(item, false)}</ul><p class="muted tiny">Amounts scale from ${esc(item.servings)} servings. You can adjust the copy in your weekly plan.</p></div>` + field('date', 'Date', state.weekStart || monday(), {type: 'date', required: true}) + field('slot', 'Meal slot', slots.find(slot => slot.id === 'dinner')?.id || slots[0]?.id, {choices: slots.map(slot => ({value: slot.id, label: slot.name}))}) + field('servings', 'Servings to plan', item.servings, {type: 'number', min: 0.001, step: 0.001, required: true});
  } else if (kind === 'pantry') {
    title = item ? 'Edit pantry item' : 'Add pantry item';
    markup = field('name', 'Item name', item?.name, { required: true, wide: true }) + field('category', 'Category', item?.category || 'auto', { choices: [{ value: 'auto', label: 'Categorize from name' }, ...PANTRY_CATEGORIES.filter(([value]) => value !== 'all').map(([value, title]) => ({ value, label: title }))] }) + field('quantity', 'Quantity', item?.quantity, { type: 'number', min: 0, step: 0.001 }) + field('unit', 'Unit', item?.unit) + field('storageLocation', 'Storage location', pick(item, 'storage_location', 'storageLocation') || 'pantry', { choices: ['pantry', 'fridge', 'freezer', 'other'] }) + field('quantityConfidence', 'Quantity confidence', pick(item, 'quantity_confidence', 'quantityConfidence') || 'estimated', { choices: ['exact', 'estimated', 'unknown'] }) + field('acquiredAt', 'Purchase date (if known)', pick(item, 'acquired_at', 'acquiredAt') || item?.freshness?.purchaseDate, { type: 'date' }) + field('freshnessBasis', 'Freshness notes / evidence', pick(item, 'freshness_basis', 'freshnessBasis'), { wide: true }) + field('useByDate', 'Use by date (only if known)', pick(item, 'use_by_date', 'useByDate'), { type: 'date' });
  } else if (kind === 'pantry-use') {
    title = `Use ${item.name}`;
    markup = `<p class="muted tiny wide">${esc(item.quantity)} ${esc(item.unit || '')} remaining</p>` + field('quantity', `Amount used (${item.unit || 'units'})`, '', { type: 'number', min: 0.001, max: item.quantity, step: 0.001, required: true }) + field('recipeId', 'Saved recipe (optional)', '', { choices: [{ value: '', label: 'No recipe' }, ...arr(section('recipes')).map((recipe) => ({ value: recipe.id, label: recipe.title }))] }) + field('mealTitle', 'Meal (optional)', '', { placeholder: 'e.g. Tuesday dinner', wide: true });
  } else if (kind === 'meal') {
    title = 'Edit planned meal';
    const slots = mealSlots().filter((slot) => slot.enabled || slot.id === item?.slot);
    const parts = arr(item?.components);
    const linked = parts.map((part, index) => ({part, index})).filter(({part}) => part.recipeId && !part.taskId);
    const choices = linked.length ? linked : [{part: null, index: -1}];
    const linkStatus = linked.length ? '' : `<p class="wide muted tiny" role="status">${parts.length ? 'No recipe linked yet. Other planned food will be kept.' : `No recipe linked yet. This older entry was saved by name only: ${esc(item.meal)}.`}</p>`;
    markup = field('date', 'Date', item.date, { type: 'date', required: true }) + field('slot', 'Meal slot', item.slot, { choices: slots.map((slot) => ({ value: slot.id, label: slot.name + (slot.enabled ? '' : ' (disabled)') })) }) + field('servings', 'People / servings', item.servings, { type: 'number', min: 0.001, step: 0.001 }) + linkStatus + `<section class="wide planned-food-section"><div class="planned-food-heading"><h3>Recipes and ready food</h3><button type="button" class="button ghost small" data-editor-action="add-planned-recipe">+ Add food</button></div><div id="planned-recipe-rows">${choices.map(({part, index}, position) => plannedRecipeRow(part, index, position)).join('')}</div></section>` + field('notes', 'Notes', item.notes, { type: 'textarea', wide: true }) + `<button type="button" class="button ghost small wide" data-action="remove-meal" data-id="${esc(item.id)}">Remove this planned meal</button>`;
  } else if (kind === 'task') {
    title = item ? 'Edit task' : 'Add task';
    markup = field('title', 'Task name', item?.title, { required: true, wide: true }) + field('date', 'Date (optional)', item?.date || selectedDate, { type: 'date' }) + field('recipeId', 'Recipe to prepare (optional)', item?.recipeId, { choices: [{ value: '', label: 'No recipe' }, ...arr(section('recipes')).map((recipe) => ({ value: recipe.id, label: recipe.title }))] }) + field('servings', 'Batch servings (if cooking)', item?.servings, { type: 'number', min: 0.001, step: 0.001 }) + field('notes', 'Notes', item?.notes, { type: 'textarea', wide: true }) + `<fieldset class="wide task-meal-links"><legend>Supports these meals (optional)</legend>${arr(state.plan?.entries).map((meal) => `<label class="check-row"><input type="checkbox" name="mealIds" value="${esc(meal.id)}" ${item?.mealIds?.includes(meal.id) ? 'checked' : ''} /><span>${esc(meal.date)} · ${esc(slotName(meal))} · ${esc(meal.meal)}</span></label>`).join('') || '<p class="muted tiny">You can add links after planning meals.</p>'}</fieldset>`;
  } else if (kind === 'meal-slots') {
    title = 'Household meal slots';
    markup = `<p class="wide muted tiny">Name and order your household’s eating occasions. Disable a slot to keep its past meals. Prep belongs in tasks.</p><div id="slot-rows" class="wide">${mealSlots().map(slotEditor).join('')}</div><button type="button" class="button ghost small" data-editor-action="add-slot">Add slot</button>`;
  } else if (kind === 'activity') {
    title = item.kind === 'meal' ? `Record eaten: ${item.meal}` : `Complete: ${item.title}`;
    const inputs = arr(item.components).flatMap((row) => {
      const outputs = arr(arr(state.plan?.tasks).find((task) => task.id === row.taskId)?.stockOutputs);
      const output = outputs.find((value) => value.name.toLowerCase() === row.name.toLowerCase()) || (outputs.length === 1 ? outputs[0] : null);
      const itemId = row.pantryItemId || output?.itemId;
      const stock = arr(section('pantry')).find((value) => value.id === itemId);
      return stock ? [{ itemId, quantity: stock.unit === row.unit ? row.quantity : null }] : [];
    });
    const output = item.kind === 'task' && item.recipeId ? { name: item.recipeSnapshot?.title || item.title, quantity: item.servings, unit: 'servings', storageLocation: 'fridge' } : null;
    markup = `<p class="wide muted tiny">Record actual amounts. Only the stock listed below will change; leave both sections empty for a simple checklist task.</p><section class="wide"><h3>Pantry food used</h3><div id="stock-inputs">${inputs.map(stockInputEditor).join('')}</div><button type="button" class="button ghost small" data-editor-action="add-stock-input">Add food used</button></section><section class="wide"><h3>Prepared food remaining</h3><div id="stock-outputs">${output ? stockOutputEditor(output) : ''}</div><button type="button" class="button ghost small" data-editor-action="add-stock-output">Add prepared food</button></section>`;
  } else if (kind === 'receive') {
    title = `Add ${item.name} to pantry`;
    markup = `<p class="wide muted tiny">Enter the amount received in the unit you’ll track in the pantry, such as 20 pieces for a pack of rotis.</p>` + field('quantity', 'Quantity received', item.quantity, { type: 'number', min: 0.001, step: 0.001, required: true }) + field('unit', 'Pantry unit', item.unit, { required: true }) + field('storageLocation', 'Storage location', 'pantry', { choices: ['pantry', 'fridge', 'freezer', 'other'] });
  } else if (kind === 'shopping-preview') {
    title = 'Shopping needs for this week';
    markup = `<p class="wide muted tiny">Suggestions for unfinished meals and tasks in this week. Review other weeks and household notes before saving.</p><div class="wide shopping-needs">${item.items.map((row) => `<div class="row"><strong>${esc(row.name)}</strong><span>${esc(row.quantity)} ${esc(row.unit)}</span><small>${row.source.reasons.map((reason) => esc(reason.title)).join(', ')}</small></div>`).join('') || '<p>No additional food needed from the known quantities.</p>'}${item.warnings.length ? `<h3>Check before shopping</h3><ul>${item.warnings.map((warning) => `<li>${esc(warning)}</li>`).join('')}</ul>` : ''}</div>`;
  } else if (kind === 'shopping') {
    title = item ? 'Edit grocery item' : 'Add grocery item';
    markup = field('name', 'Item name', item?.name, { required: true, wide: true }) + field('quantity', 'Quantity', item?.quantity, { type: 'number', min: 0.001, step: 'any' }) + field('unit', 'Unit', item?.unit) + field('store', 'Where do you generally buy this? (optional)', item?.store || '', { placeholder: 'Costco, Trader Joe’s…', wide: true }) + (item ? field('listName', 'List name', section('shoppingList')?.name || 'Weekly groceries', { wide: true }) : '');
  } else if (kind === 'week-notes') {
    title = 'Notes for this week';
    markup = `<p class="muted tiny wide">Week of ${esc(state.weekStart)} · Changes that apply only to this week.</p>` + field('notes', 'Guests, ingredients to use, or other changes', item?.notes || '', { type: 'textarea', wide: true, placeholder: 'Guests on Saturday; use the spinach left from last week.' });
  } else if (kind === 'planning-rules') {
    title = 'Meal preferences';
    markup = '<p class="muted tiny wide">Describe meal preferences, nutrition goals, favourite meals, prep, and leftovers in your own words. Each change saves a new version. Leave blank to clear the rules.</p>' + field('text', 'Your usual week', item?.text || '', { type: 'textarea', wide: true, placeholder: 'Prefer protein-heavy variations when available. Keep Tuesday dinner quick. Cook pasta Saturday and use leftovers for lunch.' });
  } else if (kind === 'weekly-review') {
    title = 'Review this week';
    markup = field('weekStart', 'Week of', state.weekStart || monday(), { type: 'date', required: true }) + field('feedbackType', 'How did it go?', 'worked_well', { choices: [{ value: 'worked_well', label: 'Worked well' }, { value: 'problem', label: 'Did not work' }, { value: 'change_next_time', label: 'Change next time' }] }) + field('note', 'What happened?', '', { type: 'textarea', required: true, wide: true, placeholder: 'For example, prepping vegetables on Sunday saved time.' }) + field('nextTime', 'Lesson learned or change for next time (optional)', '', { type: 'textarea', wide: true });
  } else if (kind === 'context-update') {
    title = 'What’s changed at home?';
    markup = field('weekStart', 'Week of', state.weekStart || monday(), {type:'date',required:true}) + field('note', 'What should we know?', '', {type:'textarea',required:true,wide:true,placeholder:'Guests on Friday, late pickup, someone can help with dinner…'}) + signalFields();
  } else if (kind === 'feedback') {
    title = 'Add meal feedback';
    markup = field('recipeId', 'Saved recipe', item?.id || '', { choices: [{ value: '', label: 'No saved recipe' }, ...arr(section('recipes')).map((recipe) => ({ value: recipe.id, label: recipe.title }))] }) + field('weekStart', 'Week of', state.weekStart || monday(), { type: 'date' }) + field('feedbackType', 'How did it go?', 'worked_well', { choices: [{ value: 'worked_well', label: 'Worked well' }, { value: 'problem', label: 'Did not work' }, { value: 'change_next_time', label: 'Change next time' }, { value: 'preference_signal', label: 'Preference signal' }] }) + field('rating', 'Rating (1–5, optional)', '', { type: 'number', min: 1, max: 5 }) + field('note', 'What happened?', '', { type: 'textarea', required: true, wide: true }) + field('nextTime', 'Lesson learned or change for next time (optional)', '', { type: 'textarea', wide: true }) + field('tags', 'Reusable tags, separated by commas', '', { wide: true }) + field('variantName', 'Preparation variant (optional)', '', { wide: true }) + field('adaptations', 'What changed — one per line', '', { type: 'textarea', wide: true });
  } else if (kind === 'memory') {
    title = item ? 'Review memory' : 'Add household memory';
    markup = field('content', 'What should be remembered?', item?.content, { type: 'textarea', required: true, wide: true }) + field('scope', 'Scope', item?.scope || 'persistent', { choices: ['persistent', 'this_week'] }) + (item ? field('action', 'Action', 'update', { choices: ['update', 'forget'] }) : '<p class="muted tiny">New memories are saved as suggestions until confirmed.</p>');
  }
  document.querySelector('#dialog-title').textContent = title;
  document.querySelector('#dialog-save').textContent = kind === 'pantry-use' ? 'Record use' : kind === 'activity' ? 'Record completion' : kind === 'receive' ? 'Record received' : kind === 'shopping-preview' ? 'Update shopping list' : kind === 'library-combine' ? 'Save combination' : 'Save';
  if (kind === 'feedback') markup += field('mealPlanEntryId','Planned meal (optional)','',{choices:[{value:'',label:'No specific planned meal'},...arr(state.plan?.entries).map(entry=>({value:entry.id,label:`${entry.date} · ${entry.meal}`}))],wide:true});
  if (['weekly-review','feedback'].includes(kind)) markup += signalFields();
  fields.innerHTML = markup;
  if (!dialog.open) dialog.showModal();
  fields.querySelector('input,textarea,select')?.focus();
  document.querySelector('#dialog-save').disabled = ['plan-search', 'library-combine'].includes(kind);
  if (['plan-search', 'library-combine'].includes(kind)) updatePlanFoodResults();
}

async function submitEditor(data) {
  const { kind, item } = state.editor;
  const value = (name) => String(data.get(name) || '').trim();
  const lines = (name) => value(name).split('\n').map((part) => part.trim()).filter(Boolean);
  const comma = (name) => value(name).split(',').map((part) => part.trim()).filter(Boolean);
  if (kind === 'recipe') {
    const recipe = { id: item?.id, kind: value('kind'), title: value('title'), description: value('description'), servings: Number(value('servings')), totalMinutes: numberOrNull(value('totalMinutes')), activeMinutes: numberOrNull(value('activeMinutes')), tags: comma('tags'), cuisines: comma('cuisines'), eating_goals: comma('eating_goals'), meal_types: comma('meal_types'), diets: comma('diets'), ingredients: lines('ingredients').map((line) => { const [name, quantity, unit] = line.split('|').map((part) => part.trim()); return { name, quantity: numberOrNull(quantity), unit: unit || null }; }), instructions: lines('instructions'), sourceUrl: value('sourceUrl') || null, ...((item?.nutrition || fields.querySelector('[data-nutrition-profile]')) ? {nutrition: readNutrition(data)} : {}) };
    const saved = await save('/api/recipes', 'PUT', recipe);
    await loadRecipe(saved.id);
    state.view = 'recipes';
    writeRoute();
  } else if (kind === 'library-combine') {
    if (state.editor.selectedFoods.length < 2) throw new Error('Choose at least two recipes or ready foods.');
    await save('/api/meals/combine', 'POST', {recipeIds: state.editor.selectedFoods.map((food) => food.id),
      servings: Number(value('servings')), notes: value('notes')});
    recipeBrowser?.destroy(); recipeBrowser = null; state.browserUi = {itemType: 'meals', query: '', filters: {}};
    state.recipe = null; state.view = 'recipes'; writeRoute();
  } else if (kind === 'library-meal') {
    await save('/api/meals', 'PUT', {id: item?.id, name: value('name'), servings: Number(value('servings')), notes: value('notes'), components: readComponents(data)});
    recipeBrowser?.destroy(); recipeBrowser = null; state.browserUi = {itemType: 'meals', query: '', filters: {}}; state.recipe = null; state.view = 'recipes'; writeRoute();
  } else if (kind === 'plan-search') {
    const foods = state.editor.selectedFoods;
    if (!foods.length) throw new Error('Choose a recipe or ready food from the search results.');
    const date = value('date');
    if (monday(`${date}T12:00:00`) !== state.weekStart) throw new Error('Choose a date in the selected week.');
    const payload = {weekStart: state.weekStart, date, slot: value('slot'), servings: Number(value('servings')), notes: value('notes')};
    if (foods.length > 1) {
      if (foods.some((food) => food.itemType === 'meals')) throw new Error('Combine recipes and ready food only.');
      await save('/api/meal-plan/combine', 'POST', {...payload, recipeIds: foods.map((food) => food.id)});
    } else {
      await save(`/api/${foods[0].itemType === 'meals' ? 'meals' : 'recipes'}/${encodeURIComponent(foods[0].id)}/plan`, 'POST', payload);
    }
    state.view = 'plan'; state.planTab = 'plan'; writeRoute();
  } else if (kind === 'plan-library') {
    const weekStart = monday(`${value('date')}T12:00:00`);
    await save(`/api/meals/${encodeURIComponent(item.id)}/plan`, 'POST', {weekStart, date: value('date'), slot: value('slot'), servings: Number(value('servings'))});
    state.weekStart = weekStart; state.view = 'plan'; state.planTab = 'plan'; writeRoute();
  } else if (kind === 'pantry') {
    await save('/api/pantry', 'PUT', { id: item?.id, name: value('name'), category: value('category') === 'auto' ? null : value('category'), quantity: numberOrNull(value('quantity')), unit: value('unit') || null, storageLocation: value('storageLocation'), quantityConfidence: value('quantityConfidence'), acquiredAt: value('acquiredAt') || null, freshnessBasis: value('freshnessBasis') || null, useByDate: value('useByDate') || null });
  } else if (kind === 'pantry-use') {
    await save('/api/pantry/use', 'POST', { itemId: item.id, quantity: Number(value('quantity')), recipeId: value('recipeId') || null, mealTitle: value('mealTitle') || null });
  } else if (kind === 'meal') {
    if (monday(`${value('date')}T12:00:00`) !== state.weekStart) throw new Error('Choose a date in the selected week.');
    const servings = numberOrNull(value('servings'));
    const originalParts = arr(item.components);
    const selectedParts = new Map();
    const addedParts = [];
    let changed = false;
    const rows = [...fields.querySelectorAll('[data-planned-recipe]')];
    if (rows.length > 10) throw new Error('A planned meal can include at most 10 recipes or ready foods.');
    for (const row of rows) {
      const key = row.dataset.plannedRecipe;
      const index = key.startsWith('new-') ? -1 : Number(key);
      const selectedId = value(row.dataset.plannedField);
      const original = index < 0 ? null : originalParts[index];
      if (!selectedId) {
        if (original || row !== rows[0] || originalParts.some(part => part.recipeId && !part.taskId)) throw new Error('Choose a recipe or ready food, or remove the empty row.');
        continue;
      }
      if (selectedId === original?.recipeId) {
        selectedParts.set(index, {...original});
        continue;
      }
      const recipe = state.mealRecipes.find(row => row.id === selectedId);
      if (!recipe) throw new Error('Choose a recipe or ready food from this household.');
      const part = {id: original?.id || crypto.randomUUID(), name: recipe.title, quantity: servings || recipe.servings || 1, unit: 'servings', source: recipe.kind === 'ready_food' ? 'ready' : 'cook', action: recipe.kind === 'ready_food' ? 'serve' : 'cook', recipeId: recipe.id};
      if (index < 0) addedParts.push(part); else selectedParts.set(index, part);
      changed = true;
    }
    const components = originalParts.flatMap((part, index) => {
      if (!part.recipeId || part.taskId) return [{...part}];
      if (!selectedParts.has(index)) { changed = true; return []; }
      return [selectedParts.get(index)];
    }).concat(addedParts);
    if (!components.length && originalParts.length) throw new Error('Choose another food, or remove this planned meal from the week.');
    if (new Set(components.map(part => part.recipeId).filter(Boolean)).size !== components.filter(part => part.recipeId).length) throw new Error('Choose each recipe or ready food only once.');
    if (servings && servings !== item.servings) for (const part of components) {
      const old = originalParts.find(row => row.id === part.id);
      if (old?.recipeId && old.unit === 'servings' && old.quantity === item.servings) part.quantity = servings;
    }
    const meal = changed ? plannedFoodsLabel(components) : item.meal;
    await save('/api/meal-plan/items', 'PATCH', { weekStart: state.weekStart, kind: 'meal', item: { id: item.id, date: value('date'), slot: value('slot'), meal, servings, notes: value('notes'), components, ...(changed ? {sourceMeal: null} : {}) } });
  } else if (kind === 'task') {
    await save('/api/meal-plan/items', 'PATCH', { weekStart: state.weekStart, kind: 'task', item: { id: item?.id, title: value('title'), date: value('date') || null, notes: value('notes'), recipeId: value('recipeId') || null, servings: numberOrNull(value('servings')), mealIds: data.getAll('mealIds') } });
  } else if (kind === 'meal-slots') {
    const slots = [...fields.querySelectorAll('[data-slot-id]')].map((row) => ({ id: row.dataset.slotId, name: String(data.get(`${row.dataset.slotId}-name`) || '').trim(), enabled: data.has(`${row.dataset.slotId}-enabled`) }));
    await save('/api/meal-slots', 'PUT', { slots });
  } else if (kind === 'activity') {
    const inputs = [...fields.querySelectorAll('[data-stock-input]')].map((row) => ({ itemId: value(`${row.dataset.stockInput}-itemId`), quantity: Number(value(`${row.dataset.stockInput}-quantity`)) }));
    const outputs = [...fields.querySelectorAll('[data-stock-output]')].map((row) => { const key = row.dataset.stockOutput; return { name: value(`${key}-name`), quantity: Number(value(`${key}-quantity`)), unit: value(`${key}-unit`), storageLocation: value(`${key}-location`) }; });
    await save('/api/meal-plan/complete', 'POST', { weekStart: state.weekStart, kind: item.kind, itemId: item.id, inputs, outputs });
  } else if (kind === 'receive') {
    await save('/api/shopping-list/receive', 'POST', { itemId: item.id, quantity: Number(value('quantity')), unit: value('unit'), storageLocation: value('storageLocation') });
  } else if (kind === 'shopping-preview') {
    await save('/api/meal-plan/shopping', 'POST', { weekStart: state.weekStart });
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
  } else if (kind === 'week-notes') {
    await save('/api/schedule', 'PUT', { weekStart: state.weekStart, days: item?.days || DAYS.map((day) => ({ day, mode: 'flexible' })), notes: value('notes'), isNormalWeek: item?.is_normal_week ?? true, rememberRhythm: item?.remember_rhythm ?? true });
  } else if (kind === 'planning-rules') {
    await save('/api/meal-plan-rules', 'PUT', { text: value('text'), expectedRevision: item?.revision || 0 });
  } else if (kind === 'context-update') {
    await save('/api/feedback','POST',{id:state.editor.feedbackId,weekStart:monday(`${value('weekStart')}T12:00:00`),feedbackType:'context_update',note:value('note'),occurredOn:value('occurredOn')||null,signals:readSignals(data)});
  } else if (kind === 'weekly-review') {
    await save('/api/feedback', 'POST', { weekStart: monday(`${value('weekStart')}T12:00:00`), feedbackType: value('feedbackType'), note: value('note'), nextTime: value('nextTime'), tags: ['weekly-check-in'], id: state.editor.feedbackId, occurredOn: value('occurredOn') || null, signals: readSignals(data) });
  } else if (kind === 'feedback') {
    if (!value('recipeId') && !value('weekStart')) throw new Error('Choose a recipe or a week.');
    await save('/api/feedback', 'POST', { recipeId: value('recipeId') || null, mealPlanEntryId: value('mealPlanEntryId') || null, weekStart: value('weekStart') || null, feedbackType: value('feedbackType'), note: value('note'), nextTime: value('nextTime'), tags: comma('tags'), rating: numberOrNull(value('rating')), variantName: value('variantName'), adaptations: lines('adaptations'), id: state.editor.feedbackId, occurredOn: value('occurredOn') || null, signals: readSignals(data) });
    if (state.recipe?.id) state.recipe = await api(`/api/recipes/${encodeURIComponent(state.recipe.id)}`);
  } else if (kind === 'memory') {
    if (item) await save(`/api/memories/${encodeURIComponent(item.id)}`, 'PATCH', { action: value('action'), content: value('content') });
    else await save('/api/memories', 'POST', { content: value('content'), scope: value('scope'), status: 'suggested' });
  }
  dialog.close();
  await refresh(kind === 'pantry-use' ? 'Pantry quantity updated.' : 'Saved to your household.');
}

async function handleAction(actionName, id) {
  if (actionName === 'today-mode') {
    state.todayMode = id; render(); return;
  }
  if (actionName === 'close-planned-meal') { plannedMealDialog.close(); return; }
  if (actionName === 'open-planned-meal') {
    const entry = arr(state.plan?.entries).find((row) => row.id === id);
    if (!entry) throw new Error('This meal is no longer in the selected week. Refresh the plan.');
    openPlannedMeal(entry);
    return;
  }
  if (actionName === 'search-planned-recipe') {
    const entry = arr(state.plan?.entries).find((row) => row.id === id);
    if (!entry) throw new Error('This meal is no longer in the selected week. Refresh the plan.');
    state.browserUi = {itemType: 'recipes', query: entry.meal, filters: {}};
    state.recipe = null;
    plannedMealDialog.close();
    state.view = 'recipes';
    await loadSection('recipes');
    writeRoute();
    return render();
  }
  if (await chatAction(actionName,id)) return;
  if (actionName === 'circle-retry') return loadCircleData();
  if (actionName === 'circle-cancel-food') { state.circleFoodReview = null; render(); return; }
  if (actionName === 'circle-confirm-food') {
    const review = state.circleFoodReview;
    if (!review) return;
    if (review.householdId !== state.activeHouseholdId) {
      state.circleFoodReview = null; render(); throw new Error('The active household changed. Review the food again.');
    }
    const current = await api(`/api/${review.kind === 'meal' ? 'meals' : 'recipes'}/${encodeURIComponent(review.id)}`);
    if (JSON.stringify(current) !== JSON.stringify(review.source)) {
      state.circleFoodReview = null; render(); throw new Error('The food changed. Review it again before sharing.');
    }
    if (review.place === 'group') {
      const circles = await api('/api/chats');
      const currentCircle = arr(circles.items).find((item) => item.id === review.circleId);
      const audience = arr(currentCircle?.audience).map((member) => `${member.userId}:${member.membershipId}`).sort();
      if (!currentCircle || JSON.stringify(audience) !== JSON.stringify(review.audienceKeys)) {
        state.circleFoodReview = null; await loadCircleData(); throw new Error('Circle membership changed. Review the recipients again.');
      }
      await save(`/api/circles/${encodeURIComponent(review.circleId)}/messages`, 'POST', {
        body: review.body, attachmentKind: review.kind, attachmentId: review.id,
        mentionIds: review.mentionIds, expectedAudience: review.audienceKeys});
    } else if (review.place === 'direct') {
      await save('/api/direct-shares', 'POST', {email: review.email, kind: review.kind,
        recipeId: review.kind === 'recipe' ? review.id : null, mealId: review.kind === 'meal' ? review.id : null});
      state.circleComposer = null;
    } else {
      await api(review.kind === 'meal' ? `/api/meals/${encodeURIComponent(review.id)}/shares` : `/api/recipes/${encodeURIComponent(review.id)}/shares`, {method: 'POST'});
      state.circleComposer = null;
    }
    if (review.place === 'group') resetCircleForm(document.querySelector('#circle-message-form'));
    state.circleFoodReview = null; await loadCircleData(); showToast(review.place === 'public' ? 'Public link created.' : 'Food shared.'); return;
  }
  if (actionName === 'circle-members' || actionName === 'circle-share-menu') {
    state.chatFormError=null; chatReturnFocus=document.activeElement;
    state.circleShareId = null; state.circleDetail = null;
    state.circlePanel = actionName === 'circle-members' ? 'members' : 'share';
    writeRoute(); render();
    document.querySelector('.circle-side-panel input, .circle-side-panel button')?.focus(); return;
  }
  if (actionName === 'circle-close-panel') {
    queueMicrotask(()=>chatReturnFocus?.isConnected && chatReturnFocus.focus({preventScroll:true}));
    state.circlePanel = null; state.circleShareId = null; state.circleDetail = null;
    state.circleReview = null;
    if (state.circleFoodReview?.place === 'group') state.circleFoodReview = null;
    writeRoute(); render(); document.querySelector('#circle-message')?.focus(); return;
  }
  if (['circle-home', 'circle-world', 'circle-activity'].includes(actionName)) {
    state.circlePanel = null;
    state.circleHub = actionName === 'circle-world' ? 'world' : actionName === 'circle-activity' ? 'activity' : 'home';
    state.circleId = null; state.circleShareId = null; state.circleDetail = null;
    state.circleComposer = null; state.directReview = null; state.circleFoodReview = null; writeRoute(); render(); return;
  }
  if (actionName === 'circle-cancel-compose') { state.circleComposer = null; state.directReview = null; state.circleFoodReview = null; render(); return; }
  if (actionName === 'direct-compose-recipe' || actionName === 'direct-compose-week') {
    state.circleHub = 'home'; state.circleId = null; state.circleShareId = null; state.circleDetail = null;
    state.circleFoodReview = null;
    state.circleComposer = actionName === 'direct-compose-recipe' ? 'direct-food' : 'direct-week';
    writeRoute(); render(); document.querySelector('#direct-email')?.focus(); return;
  }
  if (actionName === 'direct-publish-week') {
    const review = state.directReview;
    if (!review) return;
    if (review.householdId !== state.activeHouseholdId) throw new Error('The active household changed. Review the week again.');
    const latest = (await api(`/api/meal-plan?week_start=${encodeURIComponent(review.weekStart)}`)).plan;
    if (JSON.stringify(latest) !== JSON.stringify(review.plan)) {
      state.directReview = {...review, plan: latest}; render(); throw new Error('The weekly plan changed. Review it again before publishing.');
    }
    await save('/api/direct-shares', 'POST', {email: review.email, kind: 'week', weekStart: review.weekStart});
    state.directReview = null; state.circleComposer = null; await loadCircleData(); showToast('Week shared with your friend.'); return;
  }
  if (actionName === 'public-compose-recipe' || actionName === 'public-compose-meal') {
    state.circleHub = 'world'; state.circleId = null; state.circleShareId = null;
    state.circleFoodReview = null;
    state.circleComposer = 'public-food';
    writeRoute(); render(); return;
  }
  if (actionName === 'public-copy') {
    const item = state.publicShares.find((share) => share.id === id);
    if (!item?.url) throw new Error('This link is no longer available.');
    await navigator.clipboard.writeText(item.url); showToast('Link copied.'); return;
  }
  if (actionName === 'public-revoke') {
    await api(`/api/public-shares/${encodeURIComponent(id)}`, {method: 'DELETE'});
    await loadCircleData(); showToast('Public link revoked.'); return;
  }
  if (actionName === 'circle-load-more') {
    if (state.circleNextOffset === null) return;
    const roomId=state.circleId,generation=state.dataGeneration;
    const page = await api(`/api/chats/${encodeURIComponent(roomId)}/history?cursor=${encodeURIComponent(state.circleNextOffset)}`);
    if(roomId!==state.circleId||generation!==state.dataGeneration||state.view!=='circles')return;
    state.circleLoadRequest+=1;
    state.circleFeed.push(...arr(page.items).filter(post=>!state.circleFeed.some(existing=>existing.id===post.id)));
    state.circleNextOffset = page.nextCursor;
    cacheCircleFeed(state.circleId, {items: state.circleFeed, nextCursor: page.nextCursor});
    render(); return;
  }
  if (actionName === 'circle-open') {
    state.chatResults=null; state.chatSearchOpen=false; state.chatInlineError=null; state.chatReply=null;
    if (!state.circles.some((circle) => circle.id === id && circle.myStatus === 'accepted')) return;
    state.circleId = id; state.circleHub = 'home'; state.circleShareId = null; state.circleDetail = null; state.circleReview = null; state.circleFoodReview = null; state.circlePanel = null; state.circleComposer = null;
    const cached = state.circleFeeds.get(id);
    state.circleFeed = arr(cached?.items); state.circleNextOffset = cached?.nextCursor ?? null;
    state.circleFeedLoading = !cached; state.circleError = null;
    writeRoute(); render(); await loadCircleData(); return;
  }
  if (actionName === 'circle-compose-create') { state.circleComposer = 'create'; render(); return; }
  if (actionName === 'circle-compose-recipe') {
    state.circlePanel = 'food'; state.chatPickerQuery = ''; render(); await loadChatPicker(''); return;
  }
  if (actionName === 'circle-share-week') {
    state.circlePanel = null;
    const weekStart = state.weekStart || monday();
    const plan = (await api(`/api/meal-plan?week_start=${encodeURIComponent(weekStart)}`)).plan;
    if (!plan) throw new Error('Weekly plan was not found');
    const circle = state.circles.find((item) => item.id === id);
    state.circleReview = {circleId: id, weekStart, plan, householdId: state.activeHouseholdId,
      audienceKeys: arr(circle?.audience).map((member) => `${member.userId}:${member.membershipId}`).sort()}; render(); return;
  }
  if (actionName === 'circle-cancel-review') { state.circleReview = null; render(); return; }
  if (actionName === 'circle-publish-week') {
    const review = state.circleReview;
    if (!review || review.circleId !== id) return;
    if (review.householdId !== state.activeHouseholdId) {
      state.circleReview = null; render(); throw new Error('The active household changed. Review the week again before publishing.');
    }
    const latest = (await api(`/api/meal-plan?week_start=${encodeURIComponent(review.weekStart)}`)).plan;
    if (JSON.stringify(latest) !== JSON.stringify(review.plan)) {
      state.circleReview = latest ? {...review, plan: latest} : null;
      render(); throw new Error('The weekly plan changed. Review it again before publishing.');
    }
    await save(`/api/circles/${encodeURIComponent(id)}/weeks`, 'POST',
      {weekStart: review.weekStart, expectedAudience: review.audienceKeys});
    state.circleReview = null;
    await loadCircleData(); showToast('Whole week shared with your circle.'); return;
  }
  if (actionName === 'circle-open-share') {
    const generation = state.dataGeneration;
    const roomId = state.circleId;
    const groupPost = state.circleFeed.some(post => post.id === id);
    chatReturnFocus = document.activeElement;
    state.circleShareId = id; state.circleDetail = null; state.circlePanel = null;
    if (groupPost) { writeRoute(); render(); }
    const detail = await api(`/api/circle-shares/${encodeURIComponent(id)}`);
    if (generation !== state.dataGeneration || state.circleShareId !== id || state.circleId !== roomId || state.view !== 'circles') return;
    state.circleDetail = detail;
    state.circleId = state.circleDetail.conversationId || state.circleDetail.circleId;
    const feed = await api(`/api/chats/${encodeURIComponent(state.circleId)}/history`);
    state.circleFeed = feed.items; state.circleNextOffset = feed.nextCursor;
    state.circleHub = 'home';
    writeRoute(); render();
    if (matchMedia('(max-width: 740px)').matches) document.querySelector('.circle-thread-panel')?.scrollIntoView();
    return;
  }
  if (actionName === 'circle-back') {
    queueMicrotask(()=>chatReturnFocus?.isConnected && chatReturnFocus.focus({preventScroll:true}));
    state.circlePanel = null;
    state.circleShareId = null; state.circleDetail = null; writeRoute(); render();
    if (matchMedia('(max-width: 740px)').matches) document.querySelector('.circle-feed, .circle-hub')?.scrollIntoView();
    return;
  }
  if (actionName === 'circle-accept' || actionName === 'circle-decline') {
    await save(`/api/circles/${encodeURIComponent(id)}/invitation-response`, 'POST', {accept: actionName === 'circle-accept'});
    await loadCircleData(); return;
  }
  if (actionName === 'circle-remove-friend') {
    const [circleId, userId] = id.split(':');
    await api(`/api/circles/${encodeURIComponent(circleId)}/members/${encodeURIComponent(userId)}`, {method: 'DELETE'});
    await loadCircleData(); showToast('Friend removed from circle.'); return;
  }
  if (actionName === 'circle-leave') {
    await api(`/api/circles/${encodeURIComponent(id)}/leave`, {method: 'POST'});
    await loadCircleData(); showToast('You left the circle.'); return;
  }
  if (actionName === 'circle-save-recipe') {
    const [shareId, recipeId] = id.split(':');
    await api(`/api/circle-shares/${encodeURIComponent(shareId)}/recipes/${encodeURIComponent(recipeId)}/save`, {method: 'POST'});
    state.circleDetail = await api(`/api/circle-shares/${encodeURIComponent(shareId)}`); render(); showToast('Recipe saved to your household.'); return;
  }
  if (actionName === 'circle-delete-comment') {
    await api(`/api/circle-comments/${encodeURIComponent(id)}`, {method: 'DELETE'});
    state.circleDetail = await api(`/api/circle-shares/${encodeURIComponent(state.circleShareId)}`);
    render(); showToast('Comment removed.'); return;
  }
  if (actionName === 'circle-open-saved') {
    await Promise.all([loadSection('recipes'), loadRecipe(id)]);
    state.view = 'recipes';
    writeRoute(); render(); return;
  }
  if (actionName === 'circle-revoke') {
    const wasMessage = state.circleDetail?.kind === 'message';
    await api(`/api/circle-shares/${encodeURIComponent(id)}`, {method: 'DELETE'});
    state.circleShareId = null; state.circleDetail = null; writeRoute(); await loadCircleData(); showToast(wasMessage ? 'Message removed.' : 'Share removed.'); return;
  }
  if (actionName === 'retry-section') { const request = loadSection(id, true); render(); return request; }
  if (actionName === 'retry-view') return loadViewData(true);
  if (actionName === 'today-recipe') {
    state.view = 'recipes';
    await loadRecipe(id);
    writeRoute();
    return render();
  }
  // Editors that link recipes fetch the library only when it is needed.
  if (['edit-meal', 'add-task', 'edit-task', 'use-pantry', 'add-feedback'].includes(actionName)) await loadSection('recipes');
  if (['eat-meal', 'cook-task'].includes(actionName)) await loadSection('pantry');
  if (actionName === 'edit-meal') await loadMealRecipes();
  const recipes = arr(section('recipes'));
  const pantry = arr(section('pantry'));
  const shopping = arr(section('shoppingList')?.items);
  const plan = arr(state.plan?.entries);
  if (actionName === 'use-saved-meal') { recipeBrowser?.destroy(); recipeBrowser = null; state.browserUi = {itemType: 'meals', query: '', filters: {}}; state.recipe = null; return view('recipes'); }
  if (actionName === 'create-library-meal') return openEditor('library-combine');
  if (['edit-library-meal', 'save-as-meal'].includes(actionName)) {
    if (plannedMealDialog.open) plannedMealDialog.close();
    await loadMealRecipes();
    let draft = null;
    if (actionName === 'edit-library-meal') draft = await api(`/api/meals/${encodeURIComponent(id)}`);
    if (actionName === 'save-as-meal') {
      const entry = plan.find(row => row.id === id);
      if (!entry) throw new Error('This meal is no longer in the selected week. Refresh the plan.');
      draft = {name: entry.meal, servings: entry.servings || 1, notes: entry.notes, components: arr(entry.components).map(row => {
        const recipeId = row.source === 'task' ? arr(state.plan.tasks).find(task => task.id === row.taskId)?.recipeId : row.recipeId;
        const ready = state.mealRecipes.find(recipe => recipe.id === recipeId)?.kind === 'ready_food';
        return {...row, id: crypto.randomUUID(), source: row.source === 'task' ? (recipeId && !ready ? 'cook' : 'ready') : row.source, recipeId: recipeId || null, pantryItemId: null, taskId: null, recipeSnapshot: undefined, action: row.source === 'task' ? (recipeId && !ready ? 'cook' : row.action === 'heat' ? 'heat' : 'serve') : row.action};
      })};
    }
    return openEditor('library-meal', draft);
  }
  if (actionName === 'plan-library-meal') return openEditor('plan-library', await api(`/api/meals/${encodeURIComponent(id)}`));
  if (actionName === 'archive-library-meal') {
    await api(`/api/meals/${encodeURIComponent(id)}`, {method: 'DELETE'}); return refresh('Meal archived.');
  }
  if (actionName === 'toggle-notification-archive') {
    const archived = !state.notificationsArchived;
    if (archived) state.archivedNotifications = arr((await api('/api/notifications?archived=true')).items);
    state.notificationsArchived = archived;
    return render();
  }
  if (actionName === 'toggle-notification-read' || actionName === 'archive-notification') {
    const items = state.notificationsArchived ? state.archivedNotifications : state.notifications;
    const item = items.find((notification) => notification.id === id);
    if (!item) return;
    if (actionName === 'toggle-notification-read') {
      const result = await api(`/api/notifications/${encodeURIComponent(id)}/read?read=${!item.read_at}`, { method: 'PATCH' });
      item.read_at = result.readAt;
    } else {
      const result = await api(`/api/notifications/${encodeURIComponent(id)}/archive?archived=${!state.notificationsArchived}`, { method: 'PATCH' });
      item.archived_at = result.archivedAt;
      items.splice(items.indexOf(item), 1);
      (state.notificationsArchived ? state.notifications : state.archivedNotifications).unshift(item);
    }
    updateNotificationCount();
    return render();
  }
  if (actionName === 'open-notification') {
    const item = [...state.notifications, ...state.archivedNotifications].find((notification) => notification.id === id);
    if (!item) return;
    if (!item.read_at) {
      const result = await api(`/api/notifications/${encodeURIComponent(id)}/read`, { method: 'PATCH' });
      item.read_at = result.readAt;
      updateNotificationCount();
    }
    if (item.household_id && item.household_id !== state.activeHouseholdId) {
      await api(`/api/households/${encodeURIComponent(item.household_id)}/activate`, { method: 'POST' });
    }
    location.assign(item.target_path);
    return;
  }
  if (actionName === 'review-invite') { location.assign('/invite'); return; }
  if (actionName === 'leave-household') {
    if (!confirm('Leave this household? You will lose access to its shared data.')) return;
    await api('/api/households/leave', { method: 'POST' });
    recipeBrowser?.destroy(); recipeBrowser = null; state.browserUi = {};
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
  if (actionName === 'explore-recipe') {
    if (!state.browserUi.matchingRecipeIds?.includes(id)) state.browserUi = {query: state.recipe?.title || '', filters: {}};
    state.browserUi.exploreOpen = true;
    state.browserUi.graphUi = {...state.browserUi.graphUi, selected: `recipe:${id}`};
    state.recipe = null; writeRoute(); return render();
  }
  if (actionName === 'filter-recipe-category') {
    recipeBrowser?.destroy(); recipeBrowser = null;
    const separator = id.indexOf(':');
    state.browserUi = {query: '', filters: {[id.slice(0, separator)]: [id.slice(separator + 1)]}, tab: id.slice(0, separator)};
    state.recipe = null; writeRoute(); return render();
  }
  if (actionName === 'filter-recipe-tag') {
    recipeBrowser?.destroy(); recipeBrowser = null;
    state.browserUi = {query: '', filters: {tag: [id]}, tab: 'tag'};
    state.recipe = null; writeRoute(); return render();
  }
  if (actionName === 'add-recipe') return openEditor('recipe');
  if (actionName === 'edit-recipe') return openEditor('recipe', state.recipe || recipes.find((item) => item.id === id));
  if (actionName === 'open-recipe') {
    await loadRecipe(id);
    if (plannedMealDialog.open) plannedMealDialog.close();
    state.view = 'recipes';
    writeRoute();
    return loadViewData();
  }
  if (actionName === 'close-recipe') { state.recipe = null; state.shareUrl = null; state.shareId = null; state.recipeShareReview = null; writeRoute(); return render(); }
  if (actionName === 'create-share') {
    state.recipeShareReview = {source: await api(`/api/recipes/${encodeURIComponent(id)}`),
      householdId: state.activeHouseholdId};
    render(); return;
  }
  if (actionName === 'recipe-cancel-share') { state.recipeShareReview = null; render(); return; }
  if (actionName === 'recipe-confirm-share') {
    const review = state.recipeShareReview;
    if (!review || review.householdId !== state.activeHouseholdId || review.source.id !== id) {
      state.recipeShareReview = null; render(); throw new Error('Review the recipe again before sharing.');
    }
    const current = await api(`/api/recipes/${encodeURIComponent(id)}`);
    if (JSON.stringify(current) !== JSON.stringify(review.source)) {
      state.recipeShareReview = null; render(); throw new Error('The recipe changed. Review it again before sharing.');
    }
    const share = await api(`/api/recipes/${encodeURIComponent(id)}/shares`, { method: 'POST' });
    state.shareUrl = share.url;
    state.shareId = share.id;
    state.recipeShareReview = null;
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
  if (actionName === 'pantry-stock') { state.pantryStock = id; state.pantryReview = false; state.pantryCategory = 'all'; return render(); }
  if (actionName === 'restock-pantry') {
    const item = pantry.find((entry) => entry.id === id);
    openEditor('pantry', item);
    fields.querySelector('[name=quantity]').value = '';
    fields.querySelector('[name=quantity]').required = true;
    fields.querySelector('[name=quantity]').min = '0.001';
    fields.querySelector('[name=acquiredAt]').value = new Date().toLocaleDateString('en-CA', { timeZone: 'America/Los_Angeles' });
    fields.querySelector('[name=useByDate]').value = '';
    fields.querySelector('[name=freshnessBasis]').value = '';
    fields.querySelector('[name=quantity]').focus();
    return;
  }
  if (actionName === 'review-produce') { state.pantryReview = !state.pantryReview; return render(); }
  if (actionName === 'edit-quantity' || actionName === 'cancel-quantity') {
    state.pantryQuantityId = actionName === 'edit-quantity' ? id : null;
    render();
    content.querySelector('.pantry-inline-form input')?.focus();
    return;
  }
  if (actionName === 'half-pantry' || actionName === 'finish-pantry') {
    const item = pantry.find((entry) => entry.id === id);
    const quantity = actionName === 'half-pantry' ? Math.ceil(Number(item.quantity) * 500) / 1000 : Number(item.quantity);
    await save('/api/pantry/use', 'POST', { itemId: id, quantity });
    return refresh('Pantry quantity updated.');
  }
  if (actionName === 'add-pantry') return openEditor('pantry');
  if (actionName === 'load-pantry-photos') return loadPantryPhotos();
  if (actionName === 'load-older-pantry-photos') return loadPantryPhotos(true);
  if (actionName === 'edit-pantry') return openEditor('pantry', pantry.find((item) => item.id === id));
  if (actionName === 'use-pantry') return openEditor('pantry-use', pantry.find((item) => item.id === id));
  if (actionName === 'add-meal') return openEditor('plan-search', {date: id || state.weekStart});
  if (actionName === 'edit-meal-slots') return openEditor('meal-slots');
  if (actionName === 'add-task') return openEditor('task', null, id || null);
  if (actionName === 'edit-task') return openEditor('task', arr(state.plan?.tasks).find((task) => task.id === id));
  if (actionName === 'remove-task') {
    const task = arr(state.plan?.tasks).find((task) => task.id === id);
    if (!task || !confirm(`Remove ${task.title}?`)) return;
    await save('/api/meal-plan', 'PUT', planPayload({ tasks: arr(state.plan?.tasks).filter((row) => row.id !== id) }));
    return refresh('Task removed.');
  }
  if (actionName === 'eat-meal' || actionName === 'cook-task') {
    const item = (actionName === 'eat-meal' ? plan : arr(state.plan?.tasks)).find((row) => row.id === id);
    if (item) return openEditor('activity', { ...item, kind: actionName === 'eat-meal' ? 'meal' : 'task' });
  }
  if (actionName === 'shopping-preview') {
    const preview = await api(`/api/meal-plan/shopping-preview?week_start=${state.weekStart}`);
    return openEditor('shopping-preview', preview);
  }
  if (actionName === 'receive-shopping') return openEditor('receive', shopping.find((item) => item.id === id));
  if (actionName === 'edit-meal' || actionName === 'remove-meal') {
    if (plannedMealDialog.open) plannedMealDialog.close();
    const item = plan.find((entry) => (entry.id || `${entry.day}:${entry.slot}`) === id);
    if (!item) return;
    if (actionName === 'edit-meal') return openEditor('meal', item);
    if (!confirm(`Remove ${item.meal || item.title} from this plan?`)) return;
    const tasks = arr(state.plan?.tasks).map((task) => ({ ...task, mealIds: arr(task.mealIds).filter((mealId) => mealId !== item.id) }));
    await save('/api/meal-plan', 'PUT', planPayload({ entries: plan.filter((entry) => entry !== item), tasks }));
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
  if (actionName === 'edit-week-notes') return openEditor('week-notes', state.schedule);
  if (actionName === 'plan-tab') return openPlanTab(id);
  if (actionName === 'view-rule-revision') return openPlanTab('rules', id);
  if (actionName === 'edit-planning-rules') {
    const result = await api('/api/meal-plan-rules');
    state.mealPlanRules = result.rules;
    return openEditor('planning-rules', result.rules);
  }
  if (actionName === 'view-rule-history') {
    state.ruleHistory = arr((await api('/api/meal-plan-rules/history')).items);
    return render();
  }
  if (actionName === 'review-week') return openEditor('weekly-review');
  if (actionName === 'add-context-update') return openEditor('context-update');
  if (actionName === 'add-feedback') { await loadSection('mealPlan'); return openEditor('feedback', recipes.find((item) => item.id === id)); }
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
  content.querySelectorAll('.chat-message-menu[open], .chat-room-menu[open]').forEach(menu=>{if(!menu.contains(event.target))menu.removeAttribute('open');});
  const pantrySection = event.target.closest('[data-pantry-section]');
  if (pantrySection) return openPantrySection(pantrySection.dataset.pantrySection);
  const pantryFilter = event.target.closest('[data-pantry-category]');
  if (pantryFilter) { state.pantryCategory = pantryFilter.dataset.pantryCategory; render(); return; }
  const nav = event.target.closest('[data-view]');
  if (nav) {
    if (mobileMenu.open) mobileMenu.close();
    return view(nav.dataset.view);
  }
  const button = event.target.closest('[data-action]');
  if (!button) return;
  event.preventDefault();
  event.stopPropagation();
  button.closest('.chat-message-menu, .chat-room-menu')?.removeAttribute('open');
  button.disabled = true;
  try { await handleAction(button.dataset.action, button.dataset.id); }
  catch (error) { showToast(error.message || 'Something went wrong.'); }
  finally { if (button.dataset.action !== 'card-up' && button.dataset.action !== 'card-down') button.disabled = false; }
});

content.addEventListener('toggle', (event) => {
  if(event.target.matches('.chat-message-menu, .chat-room-menu')){positionChatMenus();return;}
  if (event.target.id !== 'household-dashboard' || state.dashboardExpanded === event.target.open) return;
  state.dashboardExpanded = event.target.open;
  if (state.dashboardExpanded) loadViewData().catch((error) => showToast(error.message));
}, true);

content.addEventListener('keydown', (event) => {
  const openMenu=content.querySelector('.chat-message-menu[open], .chat-room-menu[open]');
  if(event.key==='Escape'&&openMenu){openMenu.removeAttribute('open');openMenu.querySelector('summary').focus();event.preventDefault();return;}
  if (event.key === 'Escape' && content.querySelector('.circle-panel-layer')) {
    handleAction('circle-back').catch(error => showToast(error.message)); return;
  }
  if (event.target.matches?.('#circle-message, #circle-comment') && event.key === 'Enter' && !event.shiftKey && !event.isComposing) {
    if (event.defaultPrevented || document.querySelector('.mention-dropdown.active')) return;
    event.preventDefault();
    event.target.form?.requestSubmit();
    return;
  }
  const tab = event.target.closest('[role="tab"]');
  if (!tab || !['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
  event.preventDefault();
  const tabs = ['plan', 'tasks', 'rules'];
  const index = tabs.indexOf(tab.dataset.id);
  const next = event.key === 'Home' ? 'plan' : event.key === 'End' ? 'rules' : tabs[(index + (event.key === 'ArrowRight' ? 1 : -1) + tabs.length) % tabs.length];
  openPlanTab(next);
});

content.addEventListener('change', async (event) => {
  if (event.target.id === 'week-picker') {
    try { await loadWeek(event.target.value); writeRoute(); }
    catch (error) { showToast(error.message); }
  }
  const taskCheck = event.target.closest('[data-complete-task]');
  if (taskCheck) {
    const task = arr(state.plan?.tasks).find((row) => row.id === taskCheck.dataset.completeTask);
    if (task.recipeId) {
      taskCheck.checked = false;
      await loadSection('pantry');
      openEditor('activity', { ...task, kind: 'task' });
    } else {
      taskCheck.disabled = true;
      try { await save('/api/meal-plan/complete', 'POST', { weekStart: state.weekStart, kind: 'task', itemId: task.id }); await refresh('Task completed.'); }
      catch (error) { taskCheck.checked = false; taskCheck.disabled = false; showToast(error.message); }
    }
    return;
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
  if(event.target.id==='chat-profile-name'){event.target.dataset.dirty='true';return;}
  if(event.target.id==='chat-food-query'){loadChatPicker(event.target.value);return;}
  if (event.target.matches?.('[data-mention]')) {
    const composer = event.target.form;
    if (event.target.id === 'circle-message') state.circleDrafts.set(composer.dataset.circleId, event.target.value);
    if (composer?.dataset.attachmentId && !composerMentions(composer).some((item) =>
      String(item.id) === `${composer.dataset.attachmentKind}:${composer.dataset.attachmentId}`)) {
      delete composer.dataset.attachmentKind;
      delete composer.dataset.attachmentId;
      const preview = composer.querySelector('.circle-attachment');
      if (preview) { preview.textContent = ''; preview.hidden = true; }
    }
    return;
  }
  if (event.target.id === 'circle-search') {
    const start = event.target.selectionStart;
    state.circleSearch = event.target.value;
    render();
    const next = content.querySelector('#circle-search');
    next?.focus();
    if(next?.type !== 'search') next?.setSelectionRange(start, start);
    return;
  }
  if (event.target.id !== 'pantry-search') return;
  const start = event.target.selectionStart;
  state.pantrySearch = event.target.value;
  render();
  const next = content.querySelector('#pantry-search');
  next?.focus();
  if(next?.type !== 'search') next?.setSelectionRange(start, start);
});

content.addEventListener('submit', async (event) => {
  if (['chat-search-form','chat-edit-form','chat-profile-form'].includes(event.target.id)) { event.preventDefault(); await chatSubmit(event); return; }
  if (['circle-create-form', 'circle-recipe-form', 'circle-comment-form', 'circle-message-form', 'direct-share-form', 'public-share-form'].includes(event.target.id) || event.target.matches('.circle-invite-form')) {
    event.preventDefault();
    const target = event.target;
    state.chatFormError=null;
    const submit = target.querySelector('[type="submit"]');
    if (submit.disabled) return;
    if (target.id==='circle-message-form' && !target.querySelector('textarea').value.trim()) return;
    submit.disabled = true;
    try {
      const data = new FormData(target);
      if (target.id === 'circle-create-form') {
        const circle = await save('/api/circles', 'POST', {name: String(data.get('name') || '').trim()});
        state.circleId = circle.id;
        state.circleComposer = null;
        writeRoute('replace');
      } else if (target.id === 'circle-recipe-form') {
        await save(`/api/circles/${encodeURIComponent(target.dataset.circleId)}/recipes`, 'POST', {recipeId: data.get('recipeId')});
        state.circleComposer = null;
      } else if (target.id === 'circle-comment-form') {
        const [targetType, targetId] = String(data.get('target') || 'post').split(':');
        const mentionIds = composerMentions(target).filter((item) => String(item.id).startsWith('user:')).map((item) => String(item.id).slice(5));
        await save(`/api/circle-shares/${encodeURIComponent(state.circleShareId)}/comments`, 'POST', {
          body: String(data.get('body') || '').trim(), targetType, targetId: targetId || null, mentionIds,
        });
        resetCircleForm(target);
      } else if (target.id === 'circle-message-form') {
        const mentions = composerMentions(target);
        const attachment = mentions.find((item) => String(item.id) === `${target.dataset.attachmentKind}:${target.dataset.attachmentId}`);
        const mentionIds = mentions.filter((item) => String(item.id).startsWith('user:')).map((item) => String(item.id).slice(5));
        const body = String(data.get('body') || '').replace(attachment ? `@${attachment.name}` : '\0', '').trim();
        if (attachment) {
          await prepareFoodReview('group', target.dataset.attachmentKind, target.dataset.attachmentId,
            {circleId: target.dataset.circleId, body, mentionIds});
          return;
        }
        await sendCircleText(target, body, mentionIds);
        return;
      } else if (target.id === 'direct-share-form') {
        const email = String(data.get('email') || '').trim();
        if (target.dataset.kind === 'week') {
          const weekStart = String(data.get('weekStart') || '');
          const plan = (await api(`/api/meal-plan?week_start=${encodeURIComponent(weekStart)}`)).plan;
          if (!plan) throw new Error('Weekly plan was not found');
          state.directReview = {email, weekStart, plan, householdId: state.activeHouseholdId};
          state.circleComposer = null; render(); return;
        }
        const selected = composerMentions(target).find((item) => String(item.id) === `${target.dataset.attachmentKind}:${target.dataset.attachmentId}`);
        if (!selected) throw new Error('Select a recipe or saved meal from the @ search results.');
        await prepareFoodReview('direct', target.dataset.attachmentKind, target.dataset.attachmentId, {email});
        return;
      } else if (target.id === 'public-share-form') {
        const selected = composerMentions(target).find((item) => String(item.id) === `${target.dataset.attachmentKind}:${target.dataset.attachmentId}`);
        if (!selected) throw new Error('Select a recipe or saved meal from the @ search results.');
        await prepareFoodReview('public', target.dataset.attachmentKind, target.dataset.attachmentId);
        return;
      } else {
        await save(`/api/circles/${encodeURIComponent(target.dataset.circleId)}/invitations`, 'POST', {email: data.get('email')});
        resetCircleForm(target);
      }
      await loadCircleData();
    } catch (error) { state.chatFormError=error.message || 'Could not save.'; showToast(state.chatFormError); render(); }
    finally { submit.disabled = false; }
    return;
  }
  if (event.target.matches('.pantry-inline-form')) {
    event.preventDefault();
    const submit = event.target.querySelector('[type="submit"]');
    submit.disabled = true;
    try {
      const data = new FormData(event.target);
      await save('/api/pantry', 'PUT', { id: event.target.dataset.quantityId, quantity: Number(data.get('quantity')), unit: String(data.get('unit') || '').trim() || null, quantityConfidence: 'estimated' });
      state.pantryQuantityId = null;
      await refresh('Pantry quantity updated.');
    } catch (error) { showToast(error.message); }
    finally { submit.disabled = false; }
    return;
  }
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
    await refresh(event.target.id === 'settings-form' ? 'Preferences saved.' : 'Settings saved.');
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
document.querySelector('#notifications-button').addEventListener('click', () => {
  view('notifications');
  loadNotifications(state.dataGeneration);
});
window.addEventListener('focus', () => { if (state.snapshot) loadNotifications(state.dataGeneration); });
document.addEventListener('visibilitychange', () => {
  if (!document.hidden && state.snapshot) loadNotifications(state.dataGeneration);
});
setInterval(() => { if (!document.hidden && state.snapshot) loadNotifications(state.dataGeneration); }, 60000);
document.querySelector('#account-button').addEventListener('click', () => {
  document.querySelector('#account-menu-email').textContent = state.session?.user?.email || 'Local demo';
  document.querySelector('#account-menu-household').textContent = state.households.find(item => item.id === state.activeHouseholdId)?.name || 'Demo household';
  document.querySelector('#account-switch-household').hidden = !state.client;
  accountMenu.showModal();
  document.querySelector('#account-button').setAttribute('aria-expanded','true');
});
document.querySelector('#account-menu-close').addEventListener('click',()=>accountMenu.close());
accountMenu.addEventListener('close',()=>{
  const button=document.querySelector('#account-button');button.setAttribute('aria-expanded','false');
  if(!accountMenu.dataset.navigating)button.focus({preventScroll:true});
  delete accountMenu.dataset.navigating;
});
accountMenu.addEventListener('click',event=>{if(event.target===accountMenu){const b=accountMenu.getBoundingClientRect();if(event.clientX<b.left||event.clientX>b.right||event.clientY<b.top||event.clientY>b.bottom)accountMenu.close();}});
async function openAccountSettings(switchHousehold=false){
  accountMenu.dataset.navigating='true';accountMenu.close();view('settings');await loadViewData();if(state.view!=='settings')return;render();
  const target=switchHousehold?document.querySelector('#household-choice .choice-trigger'):null;
  target?.scrollIntoView({block:'center'});target?.focus({preventScroll:true});
}
document.querySelector('#account-open-settings').addEventListener('click',()=>openAccountSettings());
document.querySelector('#account-switch-household').addEventListener('click',()=>openAccountSettings(true));
content.addEventListener('change', async event => {
  const householdChoice=event.target.closest('#household-choice');
  if(!householdChoice)return;
  const householdSelect=householdChoice.querySelector('#household-select');
  MealPrepChoices.setDisabled(householdChoice.querySelector('[data-choice-control]'), true);
  try {
    await api(`/api/households/${encodeURIComponent(householdSelect.value)}/activate`, { method: 'POST' });
    recipeBrowser?.destroy(); recipeBrowser = null; state.browserUi = {};
    state.weekStart = null;
    state.planTab = 'plan';
    state.ruleRevisionId = null;
    state.rulePreview = null;
    state.rulePreviewError = null;
    state.recipe = null;
    state.shareUrl = null;
    state.shareId = null;
    writeRoute('replace');
    await refresh('Household switched.');
  } catch (error) {
    MealPrepChoices.setValue(householdChoice.querySelector('[data-choice-control]'), state.activeHouseholdId || '');
    showToast(error.message);
  } finally { if(householdChoice.isConnected)MealPrepChoices.setDisabled(householdChoice.querySelector('[data-choice-control]'), false); }
});

async function start() {
  const route = routeFromUrl();
  state.view = route.view;
  recipeBrowser?.destroy(); recipeBrowser = null;
  state.browserUi = route.browserUi;
  state.weekStart = route.weekStart;
  state.planTab = route.planTab;
  state.ruleRevisionId = route.ruleRevisionId;
  state.pantrySection = route.pantrySection;
  state.circleId = route.circleId;
  state.circleShareId = route.circleShareId;
  state.circleHub = route.circleHub;
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
  recipeBrowser?.destroy(); recipeBrowser = null;
  state.browserUi = route.browserUi;
  state.planTab = route.planTab;
  state.ruleRevisionId = route.ruleRevisionId;
  state.rulePreview = null;
  state.rulePreviewError = null;
  state.pantrySection = route.pantrySection;
  state.circleId = route.circleId;
  state.circleShareId = route.circleShareId;
  state.circleHub = route.circleHub;
  state.circleDetail = null;
  state.recipe = null;
  state.shareUrl = null;
  state.shareId = null;
  state.plan = section('mealPlan');
  state.schedule = section('schedule');
  state.weekStart = route.weekStart || monday();
  try {
    await Promise.all([loadViewData(), ...(route.ruleRevisionId ? [loadRulePreview(route.ruleRevisionId)] : [])]);
    render();
    if (route.recipeId) { await loadRecipe(route.recipeId); render(); }
    if (route.view === 'pantry' && route.pantrySection === 'photos') await loadPantryPhotos();
  } catch (error) { showToast(error.message || 'Could not open this page.'); }
});

start().catch((error) => {
  content.innerHTML = empty('Could not open Meal Prep', error.message || 'Please reload and try again.');
});

function chatPickerMarkup() {
  return `<div class="chat-food-picker"><label for="chat-food-query">Search your food library</label><input id="chat-food-query" type="search" maxlength="80" value="${esc(state.chatPickerQuery)}" placeholder="Find a recipe, ready food, or saved meal" />
    <div class="chat-food-results" role="status">${state.chatPickerStatus==='loading' ? 'Finding food…' : state.chatPickerStatus==='error' ? `<p role="alert">Could not load food.</p>${action('Retry food search','chat-picker-retry')}` : state.chatPicker.length ? state.chatPicker.map(item=>`<button class="chat-food-option" type="button" data-action="chat-pick-food" data-id="${item.itemType==='meals'?'meal':'recipe'}:${esc(item.id)}"><strong>${esc(item.title||item.name)}</strong><small>${item.itemType==='meals'?'Saved meal':item.kind==='ready_food'?'Ready food':'Recipe'}</small></button>`).join('') : 'No food matches. Try another search or add food in Recipes.'}</div></div>`;
}
let pickerTimer;
async function loadChatPicker(query) {
  state.chatPickerQuery=query;const request=++state.chatPickerRequest,generation=state.dataGeneration;
  state.chatPickerStatus='loading';render();clearTimeout(pickerTimer);
  pickerTimer=setTimeout(async()=>{
    try{const data=await api(`/api/recipe-library?item_type=all&query=${encodeURIComponent(query)}&limit=20`);
      if(request!==state.chatPickerRequest||generation!==state.dataGeneration)return;
      state.chatPicker=data.items;state.chatPickerStatus='ready';
    }catch{if(request!==state.chatPickerRequest||generation!==state.dataGeneration)return;state.chatPickerStatus='error';}
    render();
  },150);
}

async function chatAction(name,id) {
  if(!name.startsWith('chat-')&&!['week-previous','week-next','week-today','pantry-clear-filters'].includes(name))return false;
  const room=state.circles.find(c=>c.id===state.circleId);
  const post=state.circleFeed.find(p=>p.id===id)||state.chatResults?.find(p=>p.id===id);
  if(name==='week-previous'||name==='week-next'||name==='week-today'){
    const date=new Date(`${state.weekStart}T12:00:00`);date.setDate(date.getDate()+(name==='week-previous'?-7:7));
    state.weekStart=name==='week-today'?monday():`${date.getFullYear()}-${String(date.getMonth()+1).padStart(2,'0')}-${String(date.getDate()).padStart(2,'0')}`;
    writeRoute();await loadViewData();return true;
  }
  if(name==='pantry-clear-filters'){state.pantrySearch='';state.pantryCategory='all';state.pantryStock='on-hand';state.pantryReview=false;render();return true;}
  if(name==='chat-search-toggle'){state.chatSearchOpen=!state.chatSearchOpen;state.chatResults=null;render();document.querySelector('#chat-history-query')?.focus();}
  if(name==='chat-search-more'){const roomId=state.circleId,generation=state.dataGeneration;const result=await api(`/api/chats/${encodeURIComponent(roomId)}/history?${state.chatSearchParams}&cursor=${encodeURIComponent(state.chatSearchCursor)}`);if(roomId===state.circleId&&generation===state.dataGeneration&&state.chatResults!==null){state.chatResults.push(...result.items.filter(post=>!state.chatResults.some(old=>old.id===post.id)));state.chatSearchCursor=result.nextCursor;render();}}
  if(name==='chat-clear-search'){state.chatResults=null;state.chatSearch='';state.chatSearchOpen=false;render();}
  if(name==='chat-jump'){const log=document.querySelector('.circle-timeline');if(log){log.scrollTop=log.scrollHeight;chatMarkRead();}}
  if(name==='chat-mute'){await save(`/api/chats/${encodeURIComponent(id)}/state`,'PATCH',{muted:!room.muted});await loadCircleData();}
  if(name==='chat-quote'&&post){state.chatReply={circleId:state.circleId,id:post.id,name:post.createdByName,text:circlePostTitle(post).slice(0,160)};render();document.querySelector('#circle-message')?.focus();}
  if(name==='chat-remove-attachment'){const form=document.querySelector('#circle-message-form')||document.querySelector('#direct-share-form, #public-share-form');const item=composerMentions(form).find(item=>String(item.id)===`${form.dataset.attachmentKind}:${form.dataset.attachmentId}`);const field=form.querySelector('textarea');if(item){field.value=field.value.replace(`@${item.name}`,'').trim();field.dispatchEvent(new Event('input',{bubbles:true}));}delete form.dataset.attachmentId;delete form.dataset.attachmentKind;const preview=form.querySelector('.circle-attachment');preview.hidden=true;preview.textContent='';field.focus();}
  if(name==='chat-unquote'){state.chatReply=null;render();}
  if(name==='chat-edit'&&post){state.chatEdit={id:post.id};render();document.querySelector('#chat-edit-body')?.focus();}
  if(name==='chat-cancel-edit'){state.chatEdit=null;render();}
  if(name==='chat-react'){
    const split=id.indexOf(':'),postId=id.slice(0,split),emoji=id.slice(split+1);
    const message=state.circleFeed.find(p=>p.id===postId)||state.chatResults?.find(p=>p.id===postId);
    const updated=await save(`/api/chat-messages/${encodeURIComponent(postId)}/reaction`,'PUT',{emoji,active:!arr(message?.reactions).find(r=>r.emoji===emoji)?.mine});
    chatReplacePost(updated);render();
  }
  if(name==='chat-retry'){const pending=state.circlePending.get(id);if(pending?.failed)await sendCircleText(document.querySelector('#circle-message-form'),pending.snapshot.text,pending.mentionIds,pending);}
  if(name==='chat-edit-failed'){const pending=state.circlePending.get(id);if(pending){state.circlePending.delete(id);const field=document.querySelector('#circle-message');field.value=pending.snapshot.text;state.circleDrafts.set(state.circleId,field.value);render();field.focus();}}
  if(name==='chat-picker-retry')await loadChatPicker(state.chatPickerQuery);
  if(name==='chat-pick-food'){
    const [kind,itemId]=id.split(':');state.circlePanel=null;
    await prepareFoodReview('group',kind,itemId,{circleId:state.circleId,body:document.querySelector('#circle-message')?.value.trim()||'',mentionIds:[]});
  }
  return true;
}

function chatReplacePost(updated){state.circleLoadRequest+=1;if(state.chatResults)state.chatResults=state.chatResults.map(post=>post.id===updated.id?updated:post);state.circleFeed=state.circleFeed.map(post=>post.id===updated.id?updated:post);cacheCircleFeed(state.circleId,{items:state.circleFeed,nextCursor:state.circleNextOffset});}

async function chatSubmit(event) {
  const form=event.target;
  if(!['chat-search-form','chat-edit-form','chat-profile-form'].includes(form.id))return false;
  event.preventDefault();const data=new FormData(form),submit=form.querySelector('[type="submit"]');
  if(submit.disabled)return true;submit.disabled=true;
  const generation=state.dataGeneration,roomId=state.circleId;
  try{
    if(form.id==='chat-search-form'){
      state.chatSearch=String(data.get('query')||'');
      const params=new URLSearchParams({query:state.chatSearch});
      if(data.get('sender'))params.set('sender',data.get('sender'));if(data.get('date'))params.set('date_from',data.get('date'));if(data.get('kind'))params.set('kind',data.get('kind'));
      const result=await api(`/api/chats/${encodeURIComponent(roomId)}/history?${params}`);
      if(generation!==state.dataGeneration||roomId!==state.circleId)return true;
      state.chatResults=result.items;state.chatSearchCursor=result.nextCursor;state.chatSearchParams=params.toString();
    }else if(form.id==='chat-edit-form'){
      const updated=await save(`/api/chat-messages/${encodeURIComponent(form.dataset.id)}`,'PATCH',{body:String(data.get('body')||'')});
      chatReplacePost(updated);state.chatEdit=null;
    }else{state.chatProfileRequest=(state.chatProfileRequest||0)+1;state.chatProfile=await save('/api/chat-profile','PUT',{name:String(data.get('name')||'')});showToast('Display name saved.');}
    state.chatInlineError=null;render();
  }catch(error){state.chatInlineError=error.message;showToast(error.message);if(form.id==='chat-profile-form'){let alert=form.querySelector('[role=alert]');if(!alert){alert=document.createElement('p');alert.setAttribute('role','alert');form.append(alert);}alert.textContent=error.message;}else render();}
  finally{submit.disabled=false;}
  return true;
}

let chatReadBusy=false;
async function chatMarkRead(){
  const room=state.circles.find(c=>c.id===state.circleId),latest=state.circleFeed[0];
  if(chatReadBusy||!room||!latest||room.lastReadId===latest.id||state.chatResults!==null||document.hidden)return;
  const log=document.querySelector('.circle-timeline');if(!log||log.scrollHeight-log.scrollTop-log.clientHeight>48)return;
  chatReadBusy=true;const generation=state.dataGeneration;
  try{const result=await save(`/api/chats/${encodeURIComponent(room.id)}/state`,'PATCH',{lastReadId:latest.id});if(generation===state.dataGeneration){Object.assign(room,result,{unreadCount:0});}}
  catch{}finally{chatReadBusy=false;}
}
function positionChatMenus(){
  content.querySelectorAll('.chat-message-menu[open], .chat-room-menu[open]').forEach(menu=>{
    const panel=menu.querySelector('div'),anchor=menu.querySelector('summary').getBoundingClientRect();
    const height=window.visualViewport?.height||innerHeight;panel.style.maxHeight=`${height-24}px`;
    const bounds=panel.getBoundingClientRect();panel.style.left=`${Math.max(12,Math.min(anchor.right-bounds.width,innerWidth-bounds.width-12))}px`;panel.style.top=`${Math.max(12,Math.min(anchor.bottom+6,height-bounds.height-12))}px`;
  });
}

function bindChatBehavior(){
  positionChatMenus();
  const log=document.querySelector('.circle-timeline'),form=document.querySelector('#circle-message-form');
  if(form){const chip=form.querySelector('.chat-reply-chip'),reply=state.chatReply?.circleId===state.circleId?state.chatReply:null;
    chip.hidden=!reply;chip.innerHTML=reply?`Replying to ${esc(reply.name)}: ${esc(reply.text)} ${action('Remove quoted reply','chat-unquote')}`:'';
    const attachment=form.querySelector('.circle-attachment');if(attachment&&!attachment.hidden&&!attachment.querySelector('button'))attachment.insertAdjacentHTML('beforeend',action('Remove attachment','chat-remove-attachment'));
  }
  if(log&&!log.dataset.bound){log.dataset.bound='true';log.addEventListener('scroll',()=>{
    const away=log.scrollHeight-log.scrollTop-log.clientHeight>48;const jump=document.querySelector('.chat-jump');if(jump)jump.hidden=!away;
    if(!away)chatMarkRead();
  },{passive:true});}
  const jump=document.querySelector('.chat-jump');if(jump&&log)jump.hidden=log.scrollHeight-log.scrollTop-log.clientHeight<=48;
  chatMarkRead();
}
ChatLive.configure({active:()=>state.view==='circles'&&Boolean(state.snapshot),key:()=>`${state.session?.user?.id||'demo'}:${state.activeHouseholdId}:${state.dataGeneration}`,
  headers:async()=>{const headers={};if(state.client){const {data}=await state.client.auth.getSession();if(!data.session?.access_token)throw new Error('Sign in');headers.Authorization=`Bearer ${data.session.access_token}`;}return headers;},
  changed:async()=>{if(state.view==='circles')await loadCircleData(true);},
  statusChanged:()=>document.querySelectorAll('.chat-connection').forEach(el=>el.textContent=ChatLive.status())});
