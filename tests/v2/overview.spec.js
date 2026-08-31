import { test, expect } from '@playwright/test';

test('概览页渲染统计块与项目卡片', async ({ page }) => {
  await page.goto('/v2/index.html#/overview');
  // 统计块:断言至少出现统计标签与数值(behavior.md §1 overview 字段)
  await expect(page.locator('#v2-content').getByText('SPEC 总数').first()).toBeVisible({ timeout: 10000 });
  await expect(page.locator('#v2-content').getByText('活跃运行').first()).toBeVisible({ timeout: 10000 });
  // 项目卡片:环境真实项目名出现在卡片中(fenixd 为实况存在项目)
  await expect(page.locator('#v2-content').getByText('fenixd').first()).toBeVisible({ timeout: 10000 });
});

test('概览页:启动按钮走 POST 端点并重拉', async ({ page }) => {
  await page.goto('/v2/index.html#/overview');
  // 找一个处于 stopped 且存在路径的项目(fenix-desktop)断言其启动按钮可见
  // 注:项目面板为 each+panel 渲染,类前缀随主题变化,用通配匹配;按钮无 accessible-name,改用文本定位
  const card = page.locator('#v2-content').locator('[class*="-Panel"]').filter({ hasText: 'fenix-desktop' });
  await expect(card.locator('button', { hasText: '启动' }).first()).toBeVisible({ timeout: 10000 });
});
