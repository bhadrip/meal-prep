const form = document.querySelector('#login-form');
const message = document.querySelector('#message');

function continuationPath() {
  const value = new URLSearchParams(location.search).get('next');
  if (!value || !value.startsWith('/') || value.startsWith('//')) return null;
  const url = new URL(value, location.origin);
  if (url.origin !== location.origin) return null;
  return `${url.pathname}${url.search}${url.hash}`;
}

async function setup() {
  message.textContent = 'Preparing sign-in…';
  const config = await fetch('/api/auth/config').then((response) => response.json());
  if (!config.supabaseUrl || !config.supabaseAnonKey) {
    message.textContent = 'Supabase is not configured yet. The app is currently using demo mode.';
    form.hidden = true;
    return;
  }
  const client = window.supabase.createClient(config.supabaseUrl, config.supabaseAnonKey);
  message.textContent = 'Checking your session…';
  const next = continuationPath();
  const { data: { session } } = await client.auth.getSession();
  message.textContent = '';
  if (session?.access_token) {
    sessionStorage.setItem('meal-prep-access-token', session.access_token);
    if (next) {
      message.textContent = 'Signed in. Returning to authorization…';
      location.replace(next);
      return;
    }
    location.replace('/');
    return;
  }
  client.auth.onAuthStateChange((_event, nextSession) => {
    if (!nextSession?.access_token) return;
    sessionStorage.setItem('meal-prep-access-token', nextSession.access_token);
    location.replace(next || '/');
  });
  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    message.textContent = 'Sending…';
    const email = new FormData(form).get('email');
    const redirectUrl = new URL(config.redirectUrl, location.origin);
    if (next) redirectUrl.searchParams.set('next', next);
    const { error } = await client.auth.signInWithOtp({
      email,
      options: {
        emailRedirectTo: redirectUrl.toString(),
        shouldCreateUser: true,
      },
    });
    message.textContent = error ? error.message : 'Check your email for the sign-in link.';
  });
}

setup().catch((error) => { message.textContent = error.message; });
