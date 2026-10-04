/* Track the visible area when a phone keyboard or browser toolbar changes it. */
(() => {
  const viewport = window.visualViewport;
  function resize() {
    document.documentElement.style.setProperty('--visible-height', `${viewport?.height || innerHeight}px`);
    document.documentElement.style.setProperty('--visible-top', `${viewport?.offsetTop || 0}px`);
  }
  viewport?.addEventListener('resize', resize);
  viewport?.addEventListener('scroll', resize);
  window.addEventListener('resize', resize);
  resize();
})();
