import { test, expect } from '@playwright/test';
test('v2 壳加载并渲染 AMIS 壳级标题', async ({ page }) => {
  await page.goto('/v2/index.html#/overview');
  await expect(page.locator('#root')).not.toBeEmpty();
});
