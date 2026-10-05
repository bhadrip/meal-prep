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
      if (!next.hasAttribute(attr.name) && attr.name !== 'data-bound' && !(attr.name === 'open' && current.matches('details'))) current.removeAttribute(attr.name);
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
    const oldLog=container.querySelector('.circle-timeline');
    const anchor=oldLog ? [...oldLog.querySelectorAll('.circle-post')].find(post=>post.getBoundingClientRect().bottom>oldLog.getBoundingClientRect().top+1) : null;
    const before=oldLog ? {anchorId:anchor?.dataset.id,anchorTop:anchor?.getBoundingClientRect().top,key:key(oldLog),top:oldLog.scrollTop,height:oldLog.scrollHeight,bottom:oldLog.scrollHeight-oldLog.scrollTop-oldLog.clientHeight<48,first:oldLog.querySelector('.circle-post')?.dataset.id,last:[...oldLog.querySelectorAll('.circle-post')].at(-1)?.dataset.id} : null;
    const template = document.createElement('template');
    template.innerHTML = markup;
    const next = template.content.firstElementChild;
    const current = container.firstElementChild;
    if (current?.matches('.circle-page') && next?.matches('.circle-page')) patch(current, next);
    else container.replaceChildren(template.content);
    const log=container.querySelector('.circle-timeline');
    if(log){
      const first=log.querySelector('.circle-post')?.dataset.id,last=[...log.querySelectorAll('.circle-post')].at(-1)?.dataset.id;
      if(!before||before.key!==key(log))log.scrollTop=log.scrollHeight;
      else if(before.first!==first&&before.last===last){const anchor=[...log.querySelectorAll('.circle-post')].find(post=>post.dataset.id===before.anchorId);log.scrollTop=before.top+(anchor?anchor.getBoundingClientRect().top-before.anchorTop:log.scrollHeight-before.height);}
      else if(before.bottom)log.scrollTop=log.scrollHeight;
    }
  }
  return {update};
})();
