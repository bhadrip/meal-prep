const saveButton = document.querySelector('#save-recipe');
const message = document.querySelector('#message');

saveButton?.addEventListener('click', async () => {
  const token = location.pathname.split('/').pop();
  saveButton.disabled = true;
  message.textContent = 'Saving…';
  try {
    const config = await fetch('/api/auth/config').then((response) => response.json());
    let accessToken = null;
    if (config.supabaseUrl && config.supabaseAnonKey) {
      const client = window.supabase.createClient(config.supabaseUrl, config.supabaseAnonKey);
      const { data, error } = await client.auth.getSession();
      if (error || !data.session?.access_token) {
        location.assign(`/login?next=${encodeURIComponent(location.pathname)}`);
        return;
      }
      accessToken = data.session.access_token;
    }
    const response = await fetch(`/api/shares/${encodeURIComponent(token)}/save`, {
      method: 'POST',
      headers: accessToken ? { Authorization: `Bearer ${accessToken}` } : {},
    });
    if (response.status === 401) {
      location.assign(`/login?next=${encodeURIComponent(location.pathname)}`);
      return;
    }
    if (!response.ok) throw new Error('Could not save this recipe. The link may have expired or been revoked.');
    message.textContent = 'Saved to your household recipes.';
    saveButton.textContent = 'Saved';
  } catch (error) {
    message.textContent = error.message;
    saveButton.disabled = false;
  }
});
