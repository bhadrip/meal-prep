const message = document.querySelector('#message');
const invitations = document.querySelector('#invitations');
const account = document.querySelector('#account');
let client;

const escapeHtml = (value) => String(value ?? '').replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;').replaceAll('"', '&quot;').replaceAll("'", '&#39;');

async function api(path, method = 'GET') {
  const { data, error } = await client.auth.getSession();
  if (error || !data.session?.access_token) throw new Error('Sign in to continue.');
  const response = await fetch(path, { method, headers: { Authorization: `Bearer ${data.session.access_token}` } });
  const result = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(result.detail || 'Request failed.');
  return result;
}

async function load() {
  message.textContent = 'Checking your invitation…';
  const config = await fetch('/api/auth/config').then((response) => response.json());
  if (!config.supabaseUrl || !config.supabaseAnonKey) throw new Error('Invitations are unavailable in demo mode.');
  client = window.supabase.createClient(config.supabaseUrl, config.supabaseAnonKey);
  const { data, error } = await client.auth.getSession();
  if (error) throw error;
  if (!data.session) {
    message.innerHTML = 'Please <a href="/login?next=%2Finvite">sign in with the invited email address</a> to continue.';
    return;
  }
  account.innerHTML = `Signed in as <strong>${escapeHtml(data.session.user?.email)}</strong> · <button type="button" id="switch-account" class="button ghost small">Switch account</button>`;
  document.querySelector('#switch-account').addEventListener('click', async () => {
    await client.auth.signOut();
    location.assign('/login?next=%2Finvite');
  });
  const pending = await api('/api/invitations/mine');
  if (!pending.invitations?.length) {
    message.textContent = 'No active invitation was found for this account. Ask the household owner to create a new one if it expired or was revoked.';
    return;
  }
  message.textContent = pending.hasHousehold ? 'An untouched personal household can be replaced when you join. Any household with saved data will be preserved.' : '';
  invitations.innerHTML = pending.invitations.map((invite) => `<section class="invite-row"><strong>${escapeHtml(invite.householdName)}</strong><small>Invitation expires ${escapeHtml(new Date(invite.expiresAt).toLocaleDateString())}</small><button class="button primary" type="button" data-id="${escapeHtml(invite.id)}">Join household</button></section>`).join('');
  invitations.addEventListener('click', async (event) => {
    const button = event.target.closest('[data-id]');
    if (!button) return;
    button.disabled = true;
    try {
      await api(`/api/invitations/${encodeURIComponent(button.dataset.id)}/accept`, 'POST');
      message.textContent = 'You joined the household. Opening Meal Prep…';
      location.replace('/');
    } catch (joinError) {
      message.textContent = joinError.message;
      button.disabled = false;
    }
  });
}

load().catch((error) => { message.textContent = error.message || 'Could not load invitations.'; });
