import { test, expect } from '@playwright/test';

// Task 11 测试:运维记录页时间线渲染 + 壳级告警横幅
// 运行手册:本套依赖环境实况——告警横幅在无告警环境下用 test.fixme 标注(设计 §决策),
// 仅时间线可见性为稳定断言;有未处理告警的 fixture 环境运行第二条用例。

test('运维记录页:时间线渲染 + 跨项目页签', async ({ page }) => {
  await page.goto('/v2/index.html#/activities');
  // Timeline 组件(act-timeline)存在且渲染(空环境也不报错;跨项目模式 flat 列表)
  await expect(page.locator('#v2-content [class*="Timeline"]').first()).toBeVisible({ timeout: 10000 });
  // 跨项目页签「全部」存在(activities.json Tabs 第一项)
  await expect(page.locator('#v2-content').getByText('全部').first()).toBeVisible({ timeout: 10000 });
});

test('运维记录页:单项目路由 #/activities/:project 传 ?project= 过滤', async ({ page }) => {
  await page.goto('/v2/index.html#/activities/fenixd');
  // 单项目模式标题「运维记录 · fenixd」(behavior.md §7)
  await expect(page.locator('#v2-content').getByText('运维记录 · fenixd').first()).toBeVisible({ timeout: 10000 });
});

test('告警横幅:有未处理告警时壳级出现横幅', async ({ page }) => {
  // 无告警 fixture 环境下此用例跳过(设计 §决策:无告警环境用 test.fixme 标注)
  test.fixme(true, '无告警环境跳过:需 fixture 存在未处理告警才能断言横幅可见并能打开列表标记已处理');
  await page.goto('/v2/index.html#/overview');
  // 横幅存在且可见,显示条数(behavior.md §7 Scenario: 无告警不显示 → 有则可见)
  const banner = page.locator('#v2-content').getByText(/条未处理告警/).first();
  await expect(banner).toBeVisible({ timeout: 10000 });
  // 点击横幅打开列表 Dialog
  await banner.click();
  const dialog = page.locator('.amis-dialog, [role="dialog"]').first();
  await expect(dialog).toBeVisible({ timeout: 10000 });
  // 单条「标记已处理」按钮存在
  await expect(page.locator('#v2-content').getByText('标记已处理').first()).toBeVisible({ timeout: 10000 });
});
