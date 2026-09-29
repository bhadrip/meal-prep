const saveButton = document.querySelector('#save-recipe');
const message = document.querySelector('#message');

saveButton?.addEventListener('click', async () => {
  const token = location.pathname.split('/').pop();
  const accessToken = sessionStorage.getItem('meal-prep-access-token');
  if (!accessToken) {
    location.href = `/login?next=${encodeURIComponent(location.pathname)}`;
    return;
  }
  saveButton.disabled = true;
  message.textContent = 'Saving…';
  try {
    const response = await fetch(`/api/shares/${encodeURIComponent(token)}/save`, {
      method: 'POST',
      headers: { Authorization: `Bearer ${accessToken}` },
    });
    if (response.status === 401) {
      sessionStorage.removeItem('meal-prep-access-token');
      location.href = `/login?next=${encodeURIComponent(location.pathname)}`;
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
