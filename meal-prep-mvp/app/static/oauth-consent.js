const summary = document.querySelector('#summary');
const scopes = document.querySelector('#scopes');
const actions = document.querySelector('.actions');
const message = document.querySelector('#message');

async function setup() {
  const authorizationId = new URLSearchParams(location.search).get('authorization_id');
  if (!authorizationId) throw new Error('Missing authorization request.');
  const config = await fetch('/api/auth/config').then((response) => response.json());
  const client = window.supabase.createClient(config.supabaseUrl, config.supabaseAnonKey);
  const { data: { session } } = await client.auth.getSession();
  if (!session) {
    const next = encodeURIComponent(location.pathname + location.search);
    location.href = `/login?next=${next}`;
    return;
  }
  const { data, error } = await client.auth.oauth.getAuthorizationDetails(authorizationId);
  if (error) throw error;
  const clientName = data.client?.name || data.client_name || 'an AI assistant';
  summary.textContent = `${clientName} is requesting access to your Meal Prep account.`;
  const requested = String(data.scope || '').split(/\s+/).filter(Boolean);
  scopes.innerHTML = requested.map((scope) => `<li>${scope}</li>`).join('') || '<li>Use your account identity and household data</li>';
  actions.hidden = false;
  actions.addEventListener('click', async (event) => {
    const decision = event.target.dataset.decision;
    if (!decision) return;
    actions.hidden = true;
    message.textContent = decision === 'approve' ? 'Approving…' : 'Denying…';
    const result = decision === 'approve'
      ? await client.auth.oauth.approveAuthorization(authorizationId)
      : await client.auth.oauth.denyAuthorization(authorizationId);
    if (result.error) throw result.error;
    const redirectUrl = new URL(result.data.redirect_url);
    const isLoopback = redirectUrl.protocol === 'http:'
      && ['127.0.0.1', 'localhost', '[::1]'].includes(redirectUrl.hostname);
    if (redirectUrl.protocol !== 'https:' && !isLoopback) {
      throw new Error('The OAuth client returned an unsupported callback URL.');
    }
    message.textContent = decision === 'approve'
      ? 'Access allowed. Returning to Codex…'
      : 'Access denied. Returning to Codex…';
    location.replace(redirectUrl.toString());
  });
}

setup().catch((error) => { summary.textContent = 'Unable to complete authorization.'; message.textContent = error.message; });
