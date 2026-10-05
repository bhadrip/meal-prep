// Exercise the navigation the user actually sees on the current viewport.
async function navigateToView(page, view) {
  const desktop = page.locator(`.sidebar [data-view="${view}"]`);
  if (await desktop.isVisible()) return desktop.click();
  const primary = page.locator(`.mobile-nav [data-view="${view}"]`);
  if (await primary.count()) return primary.click();
  await page.locator('#mobile-more').click();
  await page.locator(`#mobile-menu-dialog [data-view="${view}"]`).click();
}

module.exports = { navigateToView };

async function openConversationSettings(page) {
  const menu=page.getByLabel('Conversation settings',{exact:true});
  if(await menu.getAttribute('aria-expanded')!=='true' && !await page.getByRole('button',{name:'Members and circle settings',exact:true}).isVisible())await menu.click();
  await page.getByRole('button',{name:'Members and circle settings',exact:true}).click();
}
async function openMessageThread(post) {
  await require('@playwright/test').expect(post).toBeVisible();
  await require('@playwright/test').expect(post.locator('.circle-send-state')).toHaveCount(0);
  const id=await post.getAttribute('data-id');
  post=post.page().locator(`.circle-post[data-id="${id}"]`);
  const action=post.getByRole('button',{name:/Reply in thread/});
  if(!await action.isVisible())await post.getByLabel('Message actions',{exact:true}).click();
  await action.click();
}
module.exports.openConversationSettings=openConversationSettings;
module.exports.openMessageThread=openMessageThread;
