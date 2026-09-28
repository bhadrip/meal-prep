const root = document.querySelector("#view-root");
const modelStatus = document.querySelector("#model-status");
const pageIntro = document.querySelector(".page-intro");
let currentView = null;

const authHeaders = () => {
  const accessToken = sessionStorage.getItem("meal-prep-access-token");
  return accessToken ? { Authorization: `Bearer ${accessToken}` } : {};
};

const escapeHtml = (value) => String(value ?? "")
  .replaceAll("&", "&amp;")
  .replaceAll("<", "&lt;")
  .replaceAll(">", "&gt;")
  .replaceAll('"', "&quot;")
  .replaceAll("'", "&#039;");

function button(action) {
  const target = action.target_id ? ` data-target="${escapeHtml(action.target_id)}"` : "";
  return `<button type="button" class="btn ${escapeHtml(action.style)}" data-action="${escapeHtml(action.action)}"${target}>${escapeHtml(action.label)}</button>`;
}

function renderHero(component) {
  const meal = component.data;
  const hasImage = Boolean(meal.image);
  const tags = [
    `${meal.minutes} min`,
    `Serves ${meal.servings}`,
    ...(meal.tags || []),
  ].map((tag) => `<span class="tag">${escapeHtml(tag)}</span>`).join("");
  return `
    <section class="hero-meal ${hasImage ? "" : "no-image"}" aria-labelledby="today-meal-title">
      ${hasImage ? `<img class="hero-image" src="${escapeHtml(meal.image)}" alt="Paneer rice bowl with spinach and roasted vegetables" />` : ""}
      <div class="hero-content">
        <p class="hero-eyebrow">${escapeHtml(meal.eyebrow)}</p>
        <h2 id="today-meal-title">${escapeHtml(meal.name)}</h2>
        <div class="hero-meta">${tags}</div>
        <p class="hero-reason">${escapeHtml(meal.reason)}</p>
        <div class="actions">${component.actions.map(button).join("")}</div>
      </div>
    </section>`;
}

function renderUseSoon(component) {
  const itemIcons = ["◒", "⌁", "●"];
  const items = component.data.items.map((item, index) => `
    <div class="use-soon-item">
      <span class="produce-dot" aria-hidden="true">${itemIcons[index] || "•"}</span>
      <div><strong>${escapeHtml(item.name)}</strong><small>${escapeHtml(item.amount)}</small></div>
      <span class="window ${escapeHtml(item.tone)}">${escapeHtml(item.window)}</span>
    </div>`).join("");
  return `
    <section class="card use-soon" aria-labelledby="use-soon-title">
      <div class="card-header"><div><p class="card-kicker">Pantry signal</p><h3 id="use-soon-title">${escapeHtml(component.data.title)}</h3></div></div>
      <div class="card-body"><div class="use-soon-list">${items}</div><p class="fine-print">${escapeHtml(component.data.note)}</p></div>
    </section>`;
}

function renderPlan(component) {
  const days = component.data.days.map((day) => `
    <div class="day ${escapeHtml(day.state)}">
      <span class="day-name">${escapeHtml(day.day)}</span>
      <strong>${escapeHtml(day.meal)}</strong>
    </div>`).join("");
  return `
    <section class="card plan-strip" aria-labelledby="plan-title">
      <div class="card-header"><h3 id="plan-title">${escapeHtml(component.data.title)}</h3>${component.actions.map(button).join("")}</div>
      <div class="card-body"><div class="days">${days}</div></div>
    </section>`;
}

function renderPrep(component) {
  const tasks = component.data.tasks.map((task) => `
    <label class="prep-row ${task.done ? "done" : ""}">
      <input type="checkbox" data-action="toggle_prep" data-target="${escapeHtml(task.id)}" ${task.done ? "checked" : ""} />
      <span>${escapeHtml(task.label)}</span>
      <small>${escapeHtml(task.minutes)} min</small>
    </label>`).join("");
  return `
    <section class="card prep-card" aria-labelledby="prep-title">
      <div class="card-header"><div><p class="card-kicker">Weekend prep</p><h3 id="prep-title">${escapeHtml(component.data.title)}</h3></div><small>${escapeHtml(component.data.subtitle)}</small></div>
      <div class="card-body"><div class="prep-list">${tasks}</div></div>
    </section>`;
}

function renderShopping(component) {
  const percent = Math.round((component.data.done / component.data.total) * 100);
  return `
    <section class="card shopping-card" aria-labelledby="shopping-title">
      <div class="card-header"><h3 id="shopping-title">${escapeHtml(component.data.title)}</h3>${component.actions.map(button).join("")}</div>
      <div class="card-body">
        <div class="progress-ring" style="--progress:${percent}%"><strong>${percent}%</strong></div>
        <p class="shopping-summary"><strong>${escapeHtml(component.data.remaining)} items</strong> left for this week</p>
      </div>
    </section>`;
}

function renderScoped(component) {
  return `
    <section class="card scoped-card" aria-labelledby="scope-title">
      <div><h3 id="scope-title">${escapeHtml(component.data.title)}</h3><p>${escapeHtml(component.data.hint)}</p></div>
      <form class="scope-form" id="scope-form">
        <label class="sr-only" for="scope-input">Describe what changed</label>
        <input id="scope-input" name="text" maxlength="600" required placeholder="${escapeHtml(component.data.placeholder)}" />
        <button class="btn primary" type="submit">Find options</button>
      </form>
    </section>`;
}

function renderStatus(component) {
  return `
    <section class="flow-header">
      <div><p class="hero-eyebrow">${escapeHtml(component.data.eyebrow)}</p><h2>${escapeHtml(component.data.title)}</h2><p>${escapeHtml(component.data.description)}</p></div>
      <div>${component.actions.map(button).join("")}</div>
    </section>`;
}

function renderChoices(component) {
  const choices = component.data.choices.map((choice) => `
    <button class="choice-button" type="button" data-action="choose_easier" data-goal="${escapeHtml(choice.id)}">
      <strong>${escapeHtml(choice.label)}</strong><span>${escapeHtml(choice.description)}</span>
    </button>`).join("");
  return `<section class="choice-grid" aria-label="Ways to make dinner easier">${choices}</section>`;
}

function renderMealOptions(component) {
  const options = component.data.options.map((meal, index) => `
    <article class="meal-option">
      <span class="option-number">${index + 1}</span>
      <h3>${escapeHtml(meal.name)}</h3>
      <p>${escapeHtml(meal.reason)}</p>
      <div class="option-meta"><span>${escapeHtml(meal.minutes)} min</span><span>·</span><span>Serves ${escapeHtml(meal.servings)}</span></div>
      <button class="btn primary" type="button" data-action="select_swap" data-target="${escapeHtml(meal.id)}">Choose this</button>
    </article>`).join("");
  return `<section class="meal-option-grid" aria-label="Meal options">${options}</section>`;
}

function renderConfirmation(component) {
  const changes = component.data.changes.map((change) => `<li>${escapeHtml(change)}</li>`).join("");
  return `
    <section class="card confirm-card" aria-labelledby="confirm-title">
      <div class="confirm-icon" aria-hidden="true">↔</div>
      <h2 id="confirm-title">${escapeHtml(component.data.title)}</h2>
      <p>${escapeHtml(component.data.note)}</p>
      <ul class="change-list">${changes}</ul>
      <div class="actions">${component.actions.map(button).join("")}</div>
    </section>`;
}

function renderToast(component) {
  return `<section class="toast-card" role="status"><p>${escapeHtml(component.data.message)}</p><div>${component.actions.map(button).join("")}</div></section>`;
}

function checked(value, selected) {
  return selected.includes(value) ? " checked" : "";
}

function renderOnboarding(component) {
  const data = component.data;
  const stressors = data.stressOptions.map((option) => `
    <label class="select-chip"><input type="checkbox" name="stressors" value="${escapeHtml(option)}"${checked(option, data.stressors)} /><span>${escapeHtml(option)}</span></label>`).join("");
  const successes = data.successOptions.map((option) => `
    <label class="select-chip"><input type="checkbox" name="successfulStrategies" value="${escapeHtml(option)}"${checked(option, data.successfulStrategies)} /><span>${escapeHtml(option)}</span></label>`).join("");
  return `
    <form class="card guided-form" id="onboarding-form">
      <fieldset><legend>Who are we feeding?</legend><div class="form-pair">
        <label>People in the household<input name="householdSize" type="number" min="1" max="30" required value="${escapeHtml(data.householdSize)}" /></label>
        <label>Dietary restrictions <small>Comma separated; leave blank if none</small><input name="dietaryRestrictions" value="${escapeHtml(data.dietaryRestrictions)}" placeholder="No shellfish, vegetarian…" /></label>
      </div></fieldset>
      <fieldset><legend>What does the coming week need?</legend><div class="form-pair">
        <label>Dinners to plan<select name="plannedDinners">${[1,2,3,4,5,6,7].map((count) => `<option value="${count}"${count === data.plannedDinners ? " selected" : ""}>${count}</option>`).join("")}</select></label>
        <label>Week outlook<select name="weekShape">
          <option value="normal"${data.weekShape === "normal" ? " selected" : ""}>Normal week</option>
          <option value="busy"${data.weekShape === "busy" ? " selected" : ""}>Busy week</option>
          <option value="unpredictable"${data.weekShape === "unpredictable" ? " selected" : ""}>Unpredictable week</option>
          <option value="specific"${data.weekShape === "specific" ? " selected" : ""}>I’ll set specific nights next</option>
        </select></label>
      </div></fieldset>
      <fieldset><legend>How current is the pantry?</legend><div class="radio-row">
        ${[["mostly_current","Mostly current"],["important_items","I’ll add key items"],["skip","Plan without it"]].map(([value,label]) => `<label><input type="radio" name="pantryStatus" value="${value}"${value === data.pantryStatus ? " checked" : ""} /><span>${label}</span></label>`).join("")}
      </div></fieldset>
      <fieldset><legend>What makes meal planning stressful?</legend><div class="chip-picker">${stressors}</div></fieldset>
      <fieldset><legend>What has worked well before?</legend><div class="chip-picker">${successes}</div></fieldset>
      <div class="form-footer"><p>We’ll treat restrictions as rules. Everything else is an editable preference.</p><button class="btn primary" type="submit">Create my starting plan</button></div>
    </form>`;
}

function renderScheduleCheck(component) {
  const modeOptions = [
    ["cook", "Cook"], ["quick", "Quick meal"], ["leftovers", "Leftovers"],
    ["flexible", "Flexible / backup"], ["out", "Eating out"], ["prep", "Prep day"],
  ];
  const days = component.data.days.map((item) => `
    <label class="schedule-row" data-day="${escapeHtml(item.day)}">
      <strong>${escapeHtml(item.day)}</strong>
      <select name="scheduleMode">${modeOptions.map(([value, label]) => `<option value="${value}"${value === item.mode ? " selected" : ""}>${label}</option>`).join("")}</select>
    </label>`).join("");
  return `
    <form class="card guided-form schedule-form" id="schedule-form">
      <div class="schedule-question"><div><h3>Week outlook</h3><p>Specific nights override the usual rhythm for this week.</p></div>
        <div class="radio-row">
          <label><input type="radio" name="isNormalWeek" value="true"${component.data.isNormalWeek ? " checked" : ""} /><span>Mostly normal</span></label>
          <label><input type="radio" name="isNormalWeek" value="false"${!component.data.isNormalWeek ? " checked" : ""} /><span>Different this week</span></label>
        </div>
      </div>
      <div class="schedule-grid">${days}</div>
      <div class="form-footer"><label class="plain-check"><input type="checkbox" name="rememberRhythm"${component.data.rememberRhythm ? " checked" : ""} /> Use this as the starting point next week</label><button class="btn primary" type="submit">Use this schedule</button></div>
    </form>`;
}

function renderRetro(component) {
  const outcomeOptions = [["cooked", "Cooked"], ["swapped", "Swapped"], ["skipped", "Skipped"]];
  const meals = component.data.meals.map((item) => `
    <div class="retro-meal" data-id="${escapeHtml(item.id)}" data-meal="${escapeHtml(item.meal)}">
      <div><small>${escapeHtml(item.day)}</small><strong>${escapeHtml(item.meal)}</strong></div>
      <div class="segmented">${outcomeOptions.map(([value, label]) => `<label><input type="radio" name="outcome-${escapeHtml(item.id)}" value="${value}"${value === item.outcome ? " checked" : ""} /><span>${label}</span></label>`).join("")}</div>
    </div>`).join("");
  const chips = (name, options, selected) => options.map((option) => `<label class="select-chip"><input type="checkbox" name="${name}" value="${escapeHtml(option)}"${checked(option, selected)} /><span>${escapeHtml(option)}</span></label>`).join("");
  return `
    <form class="card guided-form retro-form" id="retro-form">
      <fieldset><legend>What happened to the plan?</legend><div class="retro-meals">${meals}</div></fieldset>
      <fieldset><legend>What worked?</legend><div class="chip-picker">${chips("workedWell", component.data.workedOptions, component.data.workedWell)}</div></fieldset>
      <fieldset><legend>What felt stressful?</legend><div class="chip-picker">${chips("retroStressors", component.data.stressOptions, component.data.stressors)}</div></fieldset>
      <fieldset><legend>Anything else worth carrying forward?</legend><textarea name="retroNote" maxlength="600" placeholder="Optional — e.g. Wednesday ran late, but the freezer meal saved us.">${escapeHtml(component.data.note)}</textarea></fieldset>
      <div class="form-footer"><p>We’ll use this for the next draft. Lasting memories still require confirmation.</p><button class="btn primary" type="submit">Continue to next week</button></div>
    </form>`;
}

function renderMemoryOverview(component) {
  const data = component.data;
  const household = data.household;
  const restrictions = data.foodRules.restrictions.map((item) => `<span class="rule-chip restriction">${escapeHtml(item)}</span>`).join("");
  const allowances = data.foodRules.allowances.map((item) => `<span class="rule-chip allowance">${escapeHtml(item)} allowed</span>`).join("");
  const priorities = data.planningPriorities.map((item, index) => `
    <li><span class="priority-number">${index + 1}</span><div><strong>${escapeHtml(item.title)}</strong><p>${escapeHtml(item.detail)}</p></div></li>`).join("");
  const defaults = data.planningDefaults.map((item) => `<li>${escapeHtml(item)}</li>`).join("");
  const people = data.people.length ? data.people.map((person) => `
    <article class="person-preference">
      <div class="person-heading"><span class="person-avatar" aria-hidden="true">${escapeHtml(person.name).slice(0, 1)}</span><div><strong>${escapeHtml(person.name)}</strong><small>${escapeHtml(person.detail)}</small></div></div>
      <div class="preference-tags">${person.likes.map((item) => `<span>${escapeHtml(item)}</span>`).join("")}</div>
    </article>`).join("") : `<p class="empty-copy">No individual likes or dislikes are saved yet.</p>`;
  const stores = data.stores.map((store, index) => `
    <li><span>${index + 1}</span><strong>${escapeHtml(store)}</strong><small>${index === 0 ? "First stop" : "Next stop"}</small></li>`).join("");
  const collections = data.collections.map((item) => `
    <li class="collection-row ${escapeHtml(item.status)}">
      <span class="collection-status" aria-hidden="true">${item.status === "empty" ? "0" : "!"}</span>
      <div><strong>${escapeHtml(item.name)}</strong><small>${escapeHtml(item.detail)}</small></div>
      <span class="collection-label">${item.status === "empty" ? "Empty" : "Unavailable"}</span>
    </li>`).join("");
  const memberSummary = household.members.map((member) => `<span>${escapeHtml(member)}</span>`).join("");

  return `
    <section class="memory-overview" aria-label="Saved household profile">
      <article class="household-profile-card">
        <div class="household-icon" aria-hidden="true"><span>2</span><span>8</span><span>3½</span></div>
        <div class="household-profile-copy">
          <div class="section-label">Household profile</div>
          <div class="household-title-row"><h2>${escapeHtml(household.name)}</h2><span class="role-badge">${escapeHtml(household.role)}</span></div>
          <p>${escapeHtml(household.size)} people in this household</p>
          <div class="member-summary">${memberSummary}</div>
        </div>
        <div class="household-id"><span>Household ID</span><code>${escapeHtml(household.id)}</code></div>
      </article>

      <div class="memory-columns">
        <article class="card memory-section food-rules-card">
          <div class="memory-section-heading"><span class="memory-section-icon rules" aria-hidden="true">✓</span><div><p class="section-label">Hard constraints</p><h3>Food rules</h3></div></div>
          <p class="section-copy">Every recommendation must respect these rules.</p>
          <div class="rule-chips">${restrictions}${allowances}</div>
        </article>

        <article class="card memory-section planning-card">
          <div class="memory-section-heading"><span class="memory-section-icon planning" aria-hidden="true">◇</span><div><p class="section-label">Meal balance</p><h3>Every meal should include</h3></div></div>
          <ol class="priority-list">${priorities}</ol>
        </article>
      </div>

      <div class="memory-columns secondary">
        <article class="card memory-section defaults-card">
          <div class="memory-section-heading"><span class="memory-section-icon timing" aria-hidden="true">◷</span><div><p class="section-label">Planning defaults</p><h3>What works for this family</h3></div></div>
          <ul class="default-list">${defaults}</ul>
        </article>

        <article class="card memory-section people-card">
          <div class="memory-section-heading"><span class="memory-section-icon people" aria-hidden="true">☺</span><div><p class="section-label">People</p><h3>Individual preferences</h3></div></div>
          <div class="people-list">${people}</div>
          <p class="empty-copy preference-note">No other individual preferences are saved yet.</p>
        </article>
      </div>

      <div class="memory-columns secondary">
        <article class="card memory-section stores-card">
          <div class="memory-section-heading"><span class="memory-section-icon stores" aria-hidden="true">⌂</span><div><p class="section-label">Shopping order</p><h3>Preferred stores</h3></div></div>
          <ol class="store-list">${stores}</ol>
        </article>

        <article class="card memory-section collections-card">
          <div class="memory-section-heading"><span class="memory-section-icon data" aria-hidden="true">▦</span><div><p class="section-label">Data coverage</p><h3>What else is stored</h3></div></div>
          <ul class="collection-list">${collections}</ul>
        </article>
      </div>
    </section>`;
}

function renderCollectionOverview(component) {
  const data = component.data;
  const groups = data.groups.map((group) => `
    <article class="collection-stat">
      <span class="collection-stat-icon" aria-hidden="true">${escapeHtml(group.icon)}</span>
      <div><strong>${escapeHtml(group.count)}</strong><small>${escapeHtml(group.label)}</small></div>
    </article>`).join("");
  const benefits = data.benefits.map((benefit) => `<li>${escapeHtml(benefit)}</li>`).join("");
  return `
    <section class="collection-overview" aria-label="${escapeHtml(data.title)}">
      <div class="collection-metric-row"><span class="section-label">Current saved data</span><strong>${escapeHtml(data.metric)}</strong></div>
      <div class="collection-stats">${groups}</div>
      <article class="card collection-empty-state">
        <div class="collection-illustration ${escapeHtml(data.kind)}" aria-hidden="true"><span>＋</span></div>
        <div class="collection-empty-copy"><p class="section-label">Nothing stored here yet</p><h2>${escapeHtml(data.emptyTitle)}</h2><p>${escapeHtml(data.emptyDescription)}</p></div>
        <aside><strong>When data is added</strong><ul>${benefits}</ul></aside>
      </article>
    </section>`;
}

function renderMemoryList(component) {
  if (!component.data.items.length) {
    return `<section class="card empty-memory"><div class="empty-memory-icon" aria-hidden="true">◎</div><div><p class="section-label">Learned memory</p><h3>No learned memories yet</h3><p>Household settings above are saved. Patterns from weekly retros will appear here for you to confirm, correct, or forget once memory storage is available.</p></div></section>`;
  }
  const labels = { constraint: "Household rule", pressure: "Stress signal", success: "What works", schedule: "Weekly rhythm" };
  const items = component.data.items.map((item) => `
    <article class="memory-card ${item.status}">
      <div class="memory-meta"><span>${escapeHtml(labels[item.category] || item.category)}</span><span>${item.scope === "this_week" ? "This week only" : "Ongoing"}</span></div>
      <form class="memory-edit-form" data-target="${escapeHtml(item.id)}">
        <input name="content" maxlength="240" value="${escapeHtml(item.content)}" aria-label="Memory text" />
        <button class="btn quiet" type="submit">Save correction</button>
      </form>
      <p>Source: ${escapeHtml(item.source)}${item.evidenceCount > 1 ? ` · seen ${escapeHtml(item.evidenceCount)} times` : ""}</p>
      <div class="memory-actions">
        ${item.status === "suggested" ? `<span class="suggested-badge">Suggested</span><button class="btn primary" type="button" data-action="confirm_memory" data-target="${escapeHtml(item.id)}">Confirm</button>` : `<span class="confirmed-badge">Confirmed</span>`}
        <button class="btn quiet" type="button" data-action="forget_memory" data-target="${escapeHtml(item.id)}">Forget</button>
      </div>
    </article>`).join("");
  return `<section class="memory-grid" aria-label="Household memories">${items}</section>`;
}

const renderers = {
  hero_meal: renderHero,
  use_soon: renderUseSoon,
  plan_strip: renderPlan,
  prep_checklist: renderPrep,
  shopping_progress: renderShopping,
  scoped_prompt: renderScoped,
  status_row: renderStatus,
  choice_group: renderChoices,
  meal_options: renderMealOptions,
  confirmation: renderConfirmation,
  toast: renderToast,
  onboarding_form: renderOnboarding,
  schedule_check: renderScheduleCheck,
  retro_form: renderRetro,
  memory_overview: renderMemoryOverview,
  memory_list: renderMemoryList,
  collection_overview: renderCollectionOverview,
};

function updateModelStatus(view) {
  modelStatus.classList.remove("ready", "fallback");
  if (view.source === "model") {
    modelStatus.classList.add("ready");
    modelStatus.querySelector("span:last-child").textContent = `AI composed · ${view.model_label}`;
  } else if (view.source === "policy") {
    modelStatus.classList.add("ready");
    modelStatus.querySelector("span:last-child").textContent = "Policy checked";
  } else if (view.model_label) {
    modelStatus.classList.add("ready");
    modelStatus.querySelector("span:last-child").textContent = `${view.model_label} configured`;
  } else {
    modelStatus.classList.add("fallback");
    modelStatus.querySelector("span:last-child").textContent = "Deterministic fallback";
  }
}

function renderView(view) {
  currentView = view;
  const isFlow = view.view_id !== "home";
  const content = view.components.map((component) => {
    const renderer = renderers[component.type];
    return renderer ? renderer(component) : "";
  }).join("");
  root.className = isFlow ? "view-grid flow-view" : "view-grid";
  root.innerHTML = content;
  const introCopy = {
    onboarding: ["Welcome to Meal Prep", "Let’s set up your household", "A useful first plan starts with a few real-life signals."],
    "weekly-retro": ["Weekly reset", "Plan from what actually happened", "A quick reflection keeps next week realistic."],
    "schedule-check": ["Next week", "Shape the plan around your time", "Confirm the rhythm before choosing meals."],
    "plan-review": ["Next week", "Your household plan", "Built around the rhythm you just confirmed."],
    "household-memory": ["Meal Prep memory", "What Meal Prep knows", "A clear view of the household data shaping every recommendation."],
    "pantry-collection": ["Kitchen inventory", "Pantry", "See what is on hand, what to use soon, and what should not be added to the list."],
    "recipes-collection": ["Family library", "Recipes", "Trusted meals, saved with the context that makes them useful."],
    "shopping-collection": ["Store priority", "Shopping", "A clear, pantry-aware list grouped around where you prefer to shop."],
  };
  const intro = introCopy[view.view_id] || ["Tuesday · September 23", "Good afternoon, Ben", "Dinner is covered. One ingredient needs attention today."];
  pageIntro.querySelector(".eyebrow").textContent = intro[0];
  pageIntro.querySelector("h1").textContent = intro[1];
  pageIntro.querySelector(".intro-note").textContent = intro[2];
  pageIntro.classList.toggle("flow-context", view.view_id !== "home");
  const activeNav = view.view_id === "household-memory" ? "show_memory"
    : view.view_id === "pantry-collection" ? "show_pantry"
    : view.view_id === "recipes-collection" ? "show_recipes"
    : view.view_id === "shopping-collection" ? "show_shopping"
    : view.view_id.includes("plan") || view.view_id.includes("schedule") || view.view_id.includes("retro") ? "show_plan"
    : "home";
  document.querySelectorAll("[data-nav]").forEach((item) => {
    const selected = item.dataset.nav === activeNav;
    item.classList.toggle("active", selected);
    if (selected) item.setAttribute("aria-current", "page");
    else item.removeAttribute("aria-current");
  });
  root.setAttribute("aria-busy", "false");
  updateModelStatus(view);
  window.scrollTo({ top: 0, behavior: "smooth" });
}

function renderError(message) {
  root.className = "view-grid";
  root.innerHTML = `<section class="card error-card"><h2>We could not update the plan</h2><p>${escapeHtml(message)}</p><button class="btn quiet" type="button" data-action="home">Try again</button></section>`;
  root.setAttribute("aria-busy", "false");
}

async function requestView(payload) {
  root.classList.add("loading-overlay");
  root.setAttribute("aria-busy", "true");
  try {
    const response = await fetch("/api/interactions", {
      method: "POST",
      headers: { "Content-Type": "application/json", ...authHeaders() },
      body: JSON.stringify({
        view_id: currentView?.view_id || "home",
        state_version: currentView?.state_version || 1,
        ...payload,
      }),
    });
    if (!response.ok) {
      const error = await response.json().catch(() => ({ detail: "Request failed" }));
      throw new Error(error.detail || "Request failed");
    }
    const view = await response.json();
    renderView(view);
    return view;
  } catch (error) {
    renderError(error.message);
    throw error;
  } finally {
    root.classList.remove("loading-overlay");
  }
}

async function loadDashboard() {
  try {
    const response = await fetch("/api/dashboard", { headers: authHeaders() });
    if (!response.ok) throw new Error("Dashboard is unavailable.");
    renderView(await response.json());
  } catch (error) {
    renderError(error.message);
  }
}

document.addEventListener("click", (event) => {
  const target = event.target.closest("[data-action], [data-nav]");
  if (!target || target.matches("input[type=checkbox]")) return;
  const action = target.dataset.action || target.dataset.nav;
  const payload = { action };
  if (target.dataset.target) payload.target_id = target.dataset.target;
  if (target.dataset.goal) payload.parameters = { goal: target.dataset.goal };
  if (action === "confirm_swap") payload.idempotency_key = crypto.randomUUID();
  requestView(payload).catch(() => {});
});

document.addEventListener("change", (event) => {
  if (!event.target.matches("input[data-action='toggle_prep']")) return;
  requestView({ action: "toggle_prep", target_id: event.target.dataset.target }).catch(() => {});
});

document.addEventListener("submit", (event) => {
  if (event.target.matches("#onboarding-form")) {
    event.preventDefault();
    const form = new FormData(event.target);
    const restrictions = String(form.get("dietaryRestrictions") || "").split(",").map((value) => value.trim()).filter(Boolean);
    requestView({ action: "complete_onboarding", parameters: {
      householdSize: Number(form.get("householdSize")),
      dietaryRestrictions: restrictions,
      plannedDinners: Number(form.get("plannedDinners")),
      weekShape: form.get("weekShape"),
      pantryStatus: form.get("pantryStatus"),
      stressors: form.getAll("stressors"),
      successfulStrategies: form.getAll("successfulStrategies"),
    }}).catch(() => {});
    return;
  }
  if (event.target.matches("#schedule-form")) {
    event.preventDefault();
    const form = new FormData(event.target);
    const days = [...event.target.querySelectorAll(".schedule-row")].map((row) => ({ day: row.dataset.day, mode: row.querySelector("select").value }));
    requestView({ action: "save_schedule", parameters: {
      isNormalWeek: form.get("isNormalWeek") === "true",
      rememberRhythm: form.get("rememberRhythm") === "on",
      days,
    }}).catch(() => {});
    return;
  }
  if (event.target.matches("#retro-form")) {
    event.preventDefault();
    const form = new FormData(event.target);
    const outcomes = [...event.target.querySelectorAll(".retro-meal")].map((row) => ({
      id: row.dataset.id,
      meal: row.dataset.meal,
      outcome: row.querySelector("input[type=radio]:checked").value,
    }));
    requestView({ action: "save_retro", parameters: {
      outcomes,
      workedWell: form.getAll("workedWell"),
      stressors: form.getAll("retroStressors"),
      note: form.get("retroNote"),
    }}).catch(() => {});
    return;
  }
  if (event.target.matches(".memory-edit-form")) {
    event.preventDefault();
    const form = new FormData(event.target);
    requestView({ action: "update_memory", target_id: event.target.dataset.target, parameters: { content: form.get("content") } }).catch(() => {});
    return;
  }
  if (!event.target.matches("#scope-form")) return;
  event.preventDefault();
  const text = new FormData(event.target).get("text");
  requestView({ action: "scoped_request", parameters: { text } }).catch(() => {});
});

function registerWebMCP() {
  const context = document.modelContext;
  if (!context?.registerTool) return;
  const requireEmptyInput = (input) => {
    if (input == null) return;
    if (typeof input !== "object" || Array.isArray(input) || Object.keys(input).length > 0) {
      throw new TypeError("This tool does not accept input fields.");
    }
  };
  const tools = [
    {
      name: "read_current_meal_plan",
      title: "Read current meal plan",
      description: "Return the currently visible meal-planning view without changing household state.",
      inputSchema: { type: "object", properties: {}, additionalProperties: false },
      annotations: { readOnlyHint: true, untrustedContentHint: false },
      execute: async (input) => {
        requireEmptyInput(input);
        return { viewId: currentView?.view_id, stateVersion: currentView?.state_version, purpose: currentView?.purpose };
      },
    },
    {
      name: "start_meal_swap",
      title: "Start meal swap",
      description: "Open approved replacement options for tonight; this does not commit a plan change.",
      inputSchema: { type: "object", properties: {}, additionalProperties: false },
      annotations: { readOnlyHint: true, untrustedContentHint: false },
      execute: async (input) => {
        requireEmptyInput(input);
        const view = await requestView({ action: "swap_meal" });
        return { viewId: view.view_id, optionCount: view.components.find((item) => item.type === "meal_options")?.data.options.length || 0 };
      },
    },
  ];
  tools.forEach((tool) => {
    try { Promise.resolve(context.registerTool(tool)).catch(() => {}); } catch (_) {}
  });
}

loadDashboard().then(registerWebMCP);
