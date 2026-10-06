/* PostHog is optional; its project token is supplied by /api/auth/config. */
(() => {
  let enabled = false;

  function loadPostHog() {
    if (window.posthog?.__loaded || window.posthog?.__SV) return;
    !function(t,e){var o,n,p,r;e.__SV||(window.posthog&&window.posthog.__loaded)||(window.posthog=e,e._i=[],e.init=function(i,s,a){function g(t,e){var o=e.split('.');2==o.length&&(t=t[o[0]],e=o[1]),t[e]=function(){t.push([e].concat(Array.prototype.slice.call(arguments,0)))}}p||((p=t.createElement('script')).type='text/javascript',p.crossOrigin='anonymous',p.async=!0,p.src=s.api_host.replace('.i.posthog.com','-assets.i.posthog.com')+'/static/array.js',p.onerror=function(){p=null},(r=t.getElementsByTagName('script')[0]).parentNode.insertBefore(p,r));var u=e;for(void 0!==a?u=e[a]=[]:a='posthog',u.people=u.people||[],Object.defineProperty(u,'toString',{configurable:!0,enumerable:!0,writable:!0,value:function(t){var e='posthog';return'posthog'!==a&&(e+='.'+a),t||(e+=' (stub)'),e}}),Object.defineProperty(u.people,'toString',{configurable:!0,enumerable:!0,writable:!0,value:function(){return u.toString(1)+'.people (stub)'}}),o='capture identify reset get_session_id captureException'.split(' '),n=0;n<o.length;n++)g(u,o[n]);e._i.push([i,s,a])},e.__SV=1)}(document,window.posthog||[]);
  }

  function init(config) {
    const token = config?.posthogProjectToken;
    if (!token || enabled) return;
    loadPostHog();
    window.posthog.init(token, {
      api_host: config.posthogHost || 'https://us.i.posthog.com',
      defaults: '2026-05-30',
      person_profiles: 'identified_only',
      autocapture: false,
      capture_pageview: false,
      capture_pageleave: false,
      disable_session_recording: false,
      session_recording: {
        maskAllInputs: true,
        maskTextSelector: '*',
        blockSelector: 'img, video, canvas',
        maskAllElementAttributes: true,
        recordHeaders: false,
        recordBody: false,
      },
    });
    enabled = true;
  }

  function identify(userId) {
    if (enabled && /^[0-9a-f-]{36}$/i.test(userId || '')) window.posthog.identify(userId);
  }

  function capture(event, properties = {}, options = {}) {
    if (enabled) window.posthog.capture(event, { entry_point: 'web', ...properties }, options);
  }

  function sessionId() {
    return enabled ? window.posthog.get_session_id?.() : null;
  }

  function reset() {
    if (enabled) window.posthog.reset();
  }

  window.MealPrepAnalytics = { init, identify, capture, sessionId, reset };
})();
