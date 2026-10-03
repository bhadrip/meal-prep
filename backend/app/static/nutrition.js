/* Shared website / MCP App rendering. Amounts are per recorded serving, never daily targets. */
(() => {
  const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const levels = {unknown: 0, low: 1, moderate: 2, high: 3};
  const labels = {unknown: 'Unknown', low: 'Lower', moderate: 'Moderate', high: 'Higher'};
  const macros = {protein: 'Protein', carbs: 'Carbs', fat: 'Fat', fiber: 'Fiber'};
  function numeric(profile) {
    if (!profile.portion) return '';
    const approximate = profile.valueType !== 'label';
    return `<section class="nutrition-numbers"><p><b>${approximate ? 'Estimated' : 'From label'} · ${esc(profile.portion)}</b></p><dl>${Object.entries({calories: 'Calories', ...macros}).map(([key, title]) => `<div><dt>${title}</dt><dd data-amount="${key}">${profile.amounts?.[key] == null ? 'Unknown' : `${approximate ? '≈ ' : ''}${esc(profile.amounts[key])} ${key === 'calories' ? 'kcal' : 'g'}`}</dd></div>`).join('')}</dl></section>`;
  }
  function microAmount(profile, micro) {
    return micro.amount == null ? '' : ` · ${profile.valueType === 'label' ? '' : '≈ '}${esc(micro.amount)} ${esc(micro.unit)}`;
  }
  let switcherId = 0;
  function switcher(profiles, renderProfile) {
    const id = `nutrition-variation-${++switcherId}`;
    const standard = profiles.findIndex(profile => profile.name.toLocaleLowerCase() === 'standard');
    const selected = standard < 0 ? 0 : standard;
    const controls = profiles.length > 1 ? `<div class="nutrition-toggle" role="group" aria-label="Variation">${profiles.map((profile, index) => `<button type="button" data-nutrition-variation="${index}" aria-pressed="${index === selected}" aria-controls="${id}-${index}">${esc(profile.name)}</button>`).join('')}</div>` : '';
    return `<div class="nutrition-switcher">${controls}<div class="nutrition-profiles">${profiles.map((profile, index) => renderProfile(profile).replace('<article ', `<article id="${id}-${index}" data-nutrition-panel="${index}" ${index === selected ? '' : 'hidden'} `)).join('')}</div></div>`;
  }
  document.addEventListener('click', event => {
    const button = event.target.closest('[data-nutrition-variation]');
    if (!button) return;
    const scope = button.closest('.nutrition-switcher');
    scope.querySelectorAll('[data-nutrition-variation]').forEach(control => control.setAttribute('aria-pressed', String(control === button)));
    scope.querySelectorAll('[data-nutrition-panel]').forEach(panel => {panel.hidden = panel.dataset.nutritionPanel !== button.dataset.nutritionVariation;});
  });
  function hasNutrition(profile) {
    return Object.values(profile.macros || {}).some(level => level !== 'unknown')
      || Object.values(profile.amounts || {}).some(amount => amount != null)
      || (profile.micronutrients || []).length > 0;
  }
  function render(value) {
    if (!value?.profiles?.length) return '';
    return `<div class="nutrition-guide"><p class="nutrition-caption">${value.profiles.some(hasNutrition) ? 'Per plate · estimates or label values, not daily targets' : 'Choose a variation to see what changes'}</p>${switcher(value.profiles, profile => `<article class="nutrition-profile"><h4>${esc(profile.name)}</h4><p class="nutrition-serving">${esc(profile.serving)}</p>${hasNutrition(profile) ? `${numeric(profile)}<div class="nutrition-macros">${Object.entries(macros).map(([key, name]) => {const level = Object.hasOwn(levels, profile.macros?.[key]) ? profile.macros[key] : 'unknown'; return `<div class="nutrition-macro" data-nutrient="${key}" data-level="${level}"><span>${name}</span><span class="nutrition-segments" aria-hidden="true">${[1,2,3].map(n => `<i class="${n <= levels[level] ? 'filled' : ''}"></i>`).join('')}</span><b>${labels[level]}</b></div>`;}).join('')}</div>${profile.micronutrients?.length ? `<h5>Micronutrient food sources</h5><ul>${profile.micronutrients.map(micro => `<li><b>${esc(micro.nutrient)}</b>${microAmount(profile, micro)} · ${esc(micro.source)}</li>`).join('')}</ul>` : ''}` : ''}</article>`)}${value.basis && value.profiles.some(hasNutrition) ? `<p class="nutrition-basis">Basis: ${esc(value.basis)}</p>` : ''}</div>`;
  }
  function renderWeek(summary) {
    const profiles = (summary?.profiles || []).filter(profile => Object.values(profile.amounts || {}).some(amount => amount.total != null) || profile.micronutrients?.length);
    if (!profiles.length) return '';
    const coverage = count => `${count} of ${summary.mealCount} meals`;
    return `<section class="nutrition-card weekly-nutrition"><h3>Weekly nutrition · known totals</h3><p class="nutrition-caption">${esc(summary.basis)}</p>${switcher(profiles, profile => `<article class="nutrition-profile" data-weekly-profile="${esc(profile.name)}"><h4>${esc(profile.name)}</h4><p class="nutrition-caption">${esc(profile.plannedPlates)} planned plates · ${esc(summary.mealCount)} meals in plan</p><dl class="weekly-nutrition-numbers">${Object.entries({calories: 'Calories', ...macros}).map(([key, title]) => {const value = profile.amounts[key]; return `<div><dt>${title}</dt><dd data-weekly-amount="${key}">${value.total == null ? 'Unknown' : `${esc(value.total)} ${key === 'calories' ? 'kcal' : 'g'}`}</dd><small>${coverage(value.coveredMeals)} recorded</small></div>`;}).join('')}</dl>${profile.micronutrients.length ? `<h5>Micronutrients · known totals</h5><ul>${profile.micronutrients.map(m => `<li>${esc(m.nutrient)} · ${esc(m.total)} ${esc(m.unit)} <small>(${coverage(m.coveredMeals)})</small></li>`).join('')}</ul>` : ''}</article>`)}</section>`;
  }
  function title(value) {
    return value.profiles.some(hasNutrition) ? 'Nutrition &amp; variations' : 'Variations';
  }
  function renderCard(value) {
    const content = render(value);
    return content ? `<section class="nutrition-card recipe-nutrition"><h3>${title(value)}</h3>${content}</section>` : '';
  }
  function renderDetails(value) {
    const content = render(value);
    return content ? `<details class="nutrition-details"><summary>${title(value)}</summary>${content}</details>` : '';
  }
  window.MealNutrition = {render, renderCard, renderDetails, renderWeek, macros, labels, hasNutrition};
})();
