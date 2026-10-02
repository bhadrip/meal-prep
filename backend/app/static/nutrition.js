/* Shared website / MCP App rendering. Amounts are per recorded serving, never daily targets. */
(() => {
  const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const levels = {unknown: 0, low: 1, moderate: 2, high: 3};
  const labels = {unknown: 'Unknown', low: 'Lower', moderate: 'Moderate', high: 'Higher'};
  const macros = {protein: 'Protein', carbs: 'Carbs', fat: 'Fat', fiber: 'Fiber'};
  const example = {
    basis: 'Illustrative serving ideas, based on ingredients only. Costco product and portions are unverified.',
    profiles: [
      {name: 'Standard', serving: 'Steam or heat the teriyaki noodles as usual. Keep gochujang separate; offer tofu and vegetables alongside.', macros: {protein: 'low', carbs: 'high', fat: 'unknown', fiber: 'unknown'}, micronutrients: []},
      {name: 'Protein-heavy', serving: 'Use the same noodles in a smaller portion. Add a generous serving of tofu and edamame, plus broccoli. Toss your plate with gochujang.', macros: {protein: 'high', carbs: 'moderate', fat: 'unknown', fiber: 'high'}, micronutrients: [{nutrient: 'Iron', source: 'Tofu and edamame'}, {nutrient: 'Vitamin C', source: 'Broccoli'}]}
    ]
  };
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
    const controls = profiles.length > 1 ? `<div class="nutrition-toggle" role="group" aria-label="Nutrition variation">${profiles.map((profile, index) => `<button type="button" data-nutrition-variation="${index}" aria-pressed="${index === selected}" aria-controls="${id}-${index}">${esc(profile.name)}</button>`).join('')}</div>` : '';
    return `<div class="nutrition-switcher">${controls}<div class="nutrition-profiles">${profiles.map((profile, index) => renderProfile(profile).replace('<article ', `<article id="${id}-${index}" data-nutrition-panel="${index}" ${index === selected ? '' : 'hidden'} `)).join('')}</div></div>`;
  }
  document.addEventListener('click', event => {
    const button = event.target.closest('[data-nutrition-variation]');
    if (!button) return;
    const scope = button.closest('.nutrition-switcher');
    scope.querySelectorAll('[data-nutrition-variation]').forEach(control => control.setAttribute('aria-pressed', String(control === button)));
    scope.querySelectorAll('[data-nutrition-panel]').forEach(panel => {panel.hidden = panel.dataset.nutritionPanel !== button.dataset.nutritionVariation;});
  });
  function render(value) {
    if (!value?.profiles?.length) return '<p class="nutrition-unknown">Nutrition not added yet. Unknown does not mean zero.</p>';
    return `<div class="nutrition-guide"><p class="nutrition-caption">Per plate · estimates or label values, not daily targets</p>${switcher(value.profiles, profile => `<article class="nutrition-profile"><h4>${esc(profile.name)}</h4><p class="nutrition-serving">${esc(profile.serving)}</p>${numeric(profile)}<div class="nutrition-macros">${Object.entries(macros).map(([key, name]) => {const level = Object.hasOwn(levels, profile.macros?.[key]) ? profile.macros[key] : 'unknown'; return `<div class="nutrition-macro" data-nutrient="${key}" data-level="${level}"><span>${name}</span><span class="nutrition-segments" aria-hidden="true">${[1,2,3].map(n => `<i class="${n <= levels[level] ? 'filled' : ''}"></i>`).join('')}</span><b>${labels[level]}</b></div>`;}).join('')}</div><h5>Micronutrient food sources</h5>${profile.micronutrients?.length ? `<ul>${profile.micronutrients.map(micro => `<li><b>${esc(micro.nutrient)}</b>${microAmount(profile, micro)} · ${esc(micro.source)}</li>`).join('')}</ul>` : '<p class="nutrition-unknown">Sources not assessed</p>'}</article>`)}<p class="nutrition-basis">Basis: ${esc(value.basis)}</p></div>`;
  }
  function renderWeek(summary) {
    if (!summary?.profiles?.length) return '<section class="nutrition-card weekly-nutrition"><h3>Weekly nutrition</h3><p class="nutrition-unknown">No nutrition recorded for this week. Add serving values to planned meals to compare plates across the week.</p></section>';
    const coverage = count => `${count} of ${summary.mealCount} meals`;
    return `<section class="nutrition-card weekly-nutrition"><h3>Weekly nutrition · known totals</h3><p class="nutrition-caption">${esc(summary.basis)}</p>${switcher(summary.profiles, profile => `<article class="nutrition-profile" data-weekly-profile="${esc(profile.name)}"><h4>${esc(profile.name)}</h4><p class="nutrition-caption">${esc(profile.plannedPlates)} planned plates · ${esc(summary.mealCount)} meals in plan</p><dl class="weekly-nutrition-numbers">${Object.entries({calories: 'Calories', ...macros}).map(([key, title]) => {const value = profile.amounts[key]; return `<div><dt>${title}</dt><dd data-weekly-amount="${key}">${value.total == null ? 'Unknown' : `${esc(value.total)} ${key === 'calories' ? 'kcal' : 'g'}`}</dd><small>${coverage(value.coveredMeals)} recorded</small></div>`;}).join('')}</dl><h5>Micronutrients · known totals</h5>${profile.micronutrients.length ? `<ul>${profile.micronutrients.map(m => `<li>${esc(m.nutrient)} · ${esc(m.total)} ${esc(m.unit)} <small>(${coverage(m.coveredMeals)})</small></li>`).join('')}</ul>` : '<p class="nutrition-unknown">Numeric amounts not recorded</p>'}</article>`)}</section>`;
  }
  window.MealNutrition = {render, renderWeek, example, macros, labels};
})();
