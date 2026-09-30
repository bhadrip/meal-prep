const form = document.querySelector('#login-form');
const codeForm = document.querySelector('#code-form');
const codeInput = document.querySelector('#code');
const codeEmail = document.querySelector('#code-email');
const changeEmail = document.querySelector('#change-email');
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
  let pendingEmail = null;
  let completing = false;

  function completeSignIn(session) {
    if (!session?.access_token || completing) return;
    completing = true;
    sessionStorage.setItem('meal-prep-access-token', session.access_token);
    location.replace(next || '/');
  }

  const { data: { session } } = await client.auth.getSession();
  message.textContent = '';
  if (session?.access_token) return completeSignIn(session);
  client.auth.onAuthStateChange((_event, nextSession) => {
    completeSignIn(nextSession);
  });
  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    message.textContent = 'Sending…';
    const email = String(new FormData(form).get('email')).trim();
    const submit = form.querySelector('button[type="submit"]');
    submit.disabled = true;
    const { error } = await client.auth.signInWithOtp({
      email,
      options: { shouldCreateUser: false },
    });
    submit.disabled = false;
    if (error) {
      message.textContent = error.message;
      return;
    }
    pendingEmail = email;
    codeEmail.textContent = email;
    form.hidden = true;
    codeForm.hidden = false;
    codeInput.focus();
    message.textContent = 'Check your email for the eight-digit code.';
  });
  codeForm.addEventListener('submit', async (event) => {
    event.preventDefault();
    const token = String(new FormData(codeForm).get('code')).trim();
    const submit = codeForm.querySelector('button[type="submit"]');
    submit.disabled = true;
    message.textContent = 'Verifying…';
    const { data, error } = await client.auth.verifyOtp({
      email: pendingEmail,
      token,
      type: 'email',
    });
    submit.disabled = false;
    if (error) {
      message.textContent = error.message;
      return;
    }
    completeSignIn(data.session);
  });
  changeEmail.addEventListener('click', () => {
    pendingEmail = null;
    codeForm.reset();
    codeForm.hidden = true;
    form.hidden = false;
    message.textContent = '';
    form.querySelector('#email').focus();
  });
}

setup().catch((error) => { message.textContent = error.message; });
