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
