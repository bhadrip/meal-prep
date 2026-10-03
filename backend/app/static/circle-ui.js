/* Keep chat DOM, drafts, focus and scroll positions alive across data updates. */
window.CircleUI = (() => {
  const key = (node) => node.nodeType === 1
    ? node.getAttribute('data-key') || node.id || null : null;

  function patch(current, next) {
    if (current.nodeType !== next.nodeType || current.nodeName !== next.nodeName
        || key(current) !== key(next)) {
      current.replaceWith(next.cloneNode(true));
      return;
    }
    if (current.nodeType !== 1) {
      if (current.textContent !== next.textContent) current.textContent = next.textContent;
      return;
    }
    // A composer owns its live draft and MentionJS instance until its room changes.
    if (current.matches('[data-live-form]') || current.isEqualNode(next)) return;
    const scrollTop = current.scrollTop;
    for (const attr of [...current.attributes]) {
      if (!next.hasAttribute(attr.name)) current.removeAttribute(attr.name);
    }
    for (const attr of next.attributes) {
      if (current.getAttribute(attr.name) !== attr.value) current.setAttribute(attr.name, attr.value);
    }
    if (current.matches('input, textarea, select')) return;
    const old = [...current.childNodes];
    const keyed = new Map(old.filter(key).map(node => [key(node), node]));
    let index = 0;
    for (const desired of [...next.childNodes]) {
      const position = current.childNodes[index];
      const candidate = key(desired) ? keyed.get(key(desired))
        : position && !key(position) ? position : null;
      if (candidate) {
        if (candidate !== position) current.insertBefore(candidate, position);
        patch(candidate, desired);
      } else current.insertBefore(desired.cloneNode(true), position);
      index += 1;
    }
    while (current.childNodes.length > index) current.lastChild.remove();
    current.scrollTop = scrollTop;
  }

  function update(container, markup) {
    const template = document.createElement('template');
    template.innerHTML = markup;
    const next = template.content.firstElementChild;
    const current = container.firstElementChild;
    if (current?.matches('.circle-page') && next?.matches('.circle-page')) patch(current, next);
    else container.replaceChildren(template.content);
  }
  return {update};
})();
