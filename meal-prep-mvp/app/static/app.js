const root = document.querySelector("#view-root");
const modelStatus = document.querySelector("#model-status");
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
