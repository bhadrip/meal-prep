(() => {
  const escape = (value) => String(value ?? '').replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;').replaceAll('"', '&quot;').replaceAll("'", '&#39;');
  let sequence = 0;
  let active = null;
  let frameBounds = null;

  function markup({ name, value = '', choices, labelId, inputId = '' }) {
    const id = `meal-prep-choice-${++sequence}`;
    const items = choices.map((item) => ({ value: String(item.value), label: String(item.label) }));
    const selected = items.find((item) => item.value === String(value)) || items[0];
    return `<div class="choice-control" data-choice-control>
      <input type="hidden" name="${escape(name)}" ${inputId ? `id="${escape(inputId)}"` : ''} value="${escape(selected?.value || '')}">
      <button type="button" class="choice-trigger" aria-haspopup="listbox" aria-expanded="false" aria-controls="${id}-menu" aria-labelledby="${escape(labelId)} ${id}-value" ${items.length ? '' : 'disabled'}>
        <span class="choice-value" id="${id}-value">${escape(selected?.label || 'No options available')}</span><span class="choice-chevron" aria-hidden="true"></span>
      </button>
      <div id="${id}-menu" class="choice-menu" role="listbox" aria-labelledby="${escape(labelId)}" popover="manual" hidden>${items.map((item) => `<button type="button" class="choice-option" role="option" tabindex="-1" aria-selected="${item.value === selected.value}" data-choice-value="${escape(item.value)}"><span class="choice-option-label">${escape(item.label)}</span><span class="choice-check" aria-hidden="true">✓</span></button>`).join('')}</div>
    </div>`;
  }

  function setValue(control, value) {
    const option = [...control.querySelectorAll('.choice-option')].find((item) => item.dataset.choiceValue === String(value));
    if (!option) return;
    control.querySelector('input[type="hidden"]').value = option.dataset.choiceValue;
    control.querySelector('.choice-value').textContent = option.querySelector('.choice-option-label').textContent;
    control.querySelectorAll('.choice-option').forEach((item) => item.setAttribute('aria-selected', String(item === option)));
  }

  function setDisabled(control, disabled) {
    control.querySelector('input[type="hidden"]').disabled = disabled;
    control.querySelector('.choice-trigger').disabled = disabled;
    if (disabled) close(control);
  }

  function close(control = active, restoreFocus = false) {
    if (!control) return;
    const menu = control.querySelector('.choice-menu');
    if (menu.hidePopover && menu.matches(':popover-open')) menu.hidePopover();
    menu.hidden = true;
    control.classList.remove('open');
    const trigger = control.querySelector('.choice-trigger');
    trigger.setAttribute('aria-expanded', 'false');
    if (active === control) active = null;
    if (restoreFocus && trigger.isConnected) trigger.focus({ preventScroll: true });
  }

  function position() {
    if (!active) return;
    if (!active.isConnected) return close();
    const trigger = active.querySelector('.choice-trigger');
    const menu = active.querySelector('.choice-menu');
    const rect = trigger.getBoundingClientRect();
    const viewport = window.visualViewport;
    const left = Math.max(viewport?.offsetLeft || 0, frameBounds?.left || 0);
    const fields = trigger.closest('.dialog-fields');
    const fieldBounds = fields?.getBoundingClientRect();
    const top = Math.max(viewport?.offsetTop || 0, frameBounds?.top || 0, fieldBounds?.top || 0);
    const right = Math.min((viewport?.offsetLeft || 0) + (viewport?.width || document.documentElement.clientWidth), frameBounds?.right ?? Infinity);
    const bottom = Math.min((viewport?.offsetTop || 0) + (viewport?.height || window.innerHeight), frameBounds?.bottom ?? Infinity, fieldBounds?.bottom ?? Infinity);
    if (rect.bottom <= top || rect.top >= bottom || rect.right <= left || rect.left >= right) return close();
    const width = Math.min(Math.max(rect.width, 200), right - left - 16);
    menu.style.width = `${width}px`;
    const below = Math.max(0, bottom - rect.bottom - 14);
    const above = Math.max(0, rect.top - top - 14);
    const upwards = below < Math.min(menu.scrollHeight + 2, 244) && above > below;
    const height = Math.min(244, upwards ? above : below);
    if (height < 40 || width < 40) return close();
    menu.style.maxHeight = `${height}px`;
    menu.style.left = `${Math.max(left + 8, Math.min(rect.left, right - width - 8))}px`;
    menu.style.top = `${upwards ? rect.top - menu.getBoundingClientRect().height - 6 : rect.bottom + 6}px`;
  }

  function open(control) {
    if (control.querySelector('.choice-trigger').disabled) return;
    close();
    active = control;
    const menu = control.querySelector('.choice-menu');
    menu.hidden = false;
    if (menu.showPopover) menu.showPopover();
    control.classList.add('open');
    control.querySelector('.choice-trigger').setAttribute('aria-expanded', 'true');
    position();
    if (active !== control) return;
    const selected = control.querySelector('.choice-option[aria-selected="true"]') || control.querySelector('.choice-option');
    selected?.focus({ preventScroll: true });
    selected?.scrollIntoView({ block: 'nearest' });
  }

  function choose(option) {
    const control = option.closest('[data-choice-control]');
    const input = control.querySelector('input[type="hidden"]');
    const changed = input.value !== option.dataset.choiceValue;
    setValue(control, option.dataset.choiceValue);
    close(control, true);
    if (changed) input.dispatchEvent(new Event('change', { bubbles: true }));
  }

  document.addEventListener('click', (event) => {
    const option = event.target.closest('.choice-option');
    if (option) return choose(option);
    const trigger = event.target.closest('.choice-trigger');
    if (!trigger) return close();
    const control = trigger.closest('[data-choice-control]');
    if (active === control) close(control, true);
    else open(control);
  });

  document.addEventListener('keydown', (event) => {
    const control = event.target.closest('[data-choice-control]');
    if (!control || control.querySelector('.choice-trigger').disabled) return;
    const options = [...control.querySelectorAll('.choice-option')];
    const opened = active === control;
    const option = event.target.closest('.choice-option');
    if (event.key === 'Escape' && opened) {
      event.preventDefault();
      event.stopPropagation();
      close(control, true);
    } else if (event.key === 'Tab' && opened) {
      close(control, true);
    } else if (['Enter', ' '].includes(event.key)) {
      event.preventDefault();
      if (option) choose(option);
      else open(control);
    } else if (['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(event.key)) {
      event.preventDefault();
      if (!opened) open(control);
      let index = options.indexOf(document.activeElement);
      if (event.key === 'Home') index = 0;
      else if (event.key === 'End') index = options.length - 1;
      else if (opened) index = Math.max(0, Math.min(options.length - 1, index + (event.key === 'ArrowDown' ? 1 : -1)));
      options[index]?.focus({ preventScroll: true });
      options[index]?.scrollIntoView({ block: 'nearest' });
    } else if (event.key.length === 1 && !event.ctrlKey && !event.metaKey && !event.altKey) {
      event.preventDefault();
      if (!opened) open(control);
      const now = Date.now();
      control.choiceSearch = now - (control.choiceSearchAt || 0) < 700 ? (control.choiceSearch || '') + event.key.toLowerCase() : event.key.toLowerCase();
      control.choiceSearchAt = now;
      const query = /^(.)(\1)+$/.test(control.choiceSearch) ? event.key.toLowerCase() : control.choiceSearch;
      const index = options.indexOf(document.activeElement);
      const ordered = [...options.slice(index + 1), ...options.slice(0, index + 1)];
      const match = ordered.find((item) => item.querySelector('.choice-option-label').textContent.toLowerCase().startsWith(query));
      match?.focus({ preventScroll: true });
      match?.scrollIntoView({ block: 'nearest' });
    }
  });
  document.addEventListener('focusin', (event) => { if (active && !active.contains(event.target)) close(); });
  document.addEventListener('scroll', (event) => { if (active && !active.querySelector('.choice-menu').contains(event.target)) position(); }, true);
  window.addEventListener('resize', position);
  window.visualViewport?.addEventListener('resize', position);
  window.visualViewport?.addEventListener('scroll', position);
  // Frame height can exceed the part visible in the host. IntersectionObserver
  // supplies that clipped area even when the parent has a different origin.
  if (window.parent !== window && 'IntersectionObserver' in window) {
    const observeViewport = () => {
      const marker = document.createElement('div');
      marker.setAttribute('aria-hidden', 'true');
      marker.style.cssText = 'position:fixed;inset:0;pointer-events:none;opacity:0';
      document.body.append(marker);
      new IntersectionObserver(([entry]) => {
        frameBounds = entry.intersectionRect;
        position();
      }, { threshold: Array.from({ length: 101 }, (_, index) => index / 100) }).observe(marker);
    };
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', observeViewport, { once: true });
    else observeViewport();
  }
  new MutationObserver(() => { if (active && !active.isConnected) close(); }).observe(document.documentElement, { childList: true, subtree: true });
  window.MealPrepChoices = { markup, setValue, setDisabled, close };
})();
