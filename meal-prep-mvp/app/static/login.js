const form = document.querySelector('#login-form');
const message = document.querySelector('#message');

async function setup() {
  const config = await fetch('/api/auth/config').then((response) => response.json());
  if (!config.supabaseUrl || !config.supabaseAnonKey) {
    message.textContent = 'Supabase is not configured yet. The app is currently using demo mode.';
    form.hidden = true;
    return;
  }
  const client = window.supabase.createClient(config.supabaseUrl, config.supabaseAnonKey);
  const { data: { session } } = await client.auth.getSession();
  if (session?.access_token) {
    sessionStorage.setItem('meal-prep-access-token', session.access_token);
    message.textContent = `Signed in as ${session.user.email}.`;
  }
  client.auth.onAuthStateChange((_event, nextSession) => {
    if (nextSession?.access_token) sessionStorage.setItem('meal-prep-access-token', nextSession.access_token);
  });
  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    message.textContent = 'Sending…';
    const email = new FormData(form).get('email');
    const { error } = await client.auth.signInWithOtp({ email, options: { emailRedirectTo: config.redirectUrl } });
    message.textContent = error ? error.message : 'Check your email for the sign-in link.';
  });
}

setup().catch((error) => { message.textContent = error.message; });
