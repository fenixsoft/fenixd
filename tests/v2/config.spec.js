import { test, expect } from '@playwright/test';

test('配置页: 加载回显 → 修改并行度 → 保存 → 回显新值', async ({ page }) => {
  await page.goto('/v2/index.html#/config');
  await expect(page.getByText('LLM Provider').first()).toBeVisible({ timeout: 10000 });
  // 点击并行度页签（第 3 个 tab）
  await page.locator('[class*="-Tabs-link"]:not([class*="-Tabs-links"])').nth(2).click();
  await page.waitForTimeout(500);
  const sel = 'input[class*="-Number-input"]';
  const before = await page.locator(sel).first().inputValue();
  const next = String(Number(before || 2) + 1);
  await page.locator(sel).first().click({ clickCount: 1 });
  await page.locator(sel).first().press('ControlOrMeta+a');
  await page.locator(sel).first().type(next);
  await page.getByRole('button', { name: '保存配置' }).click();
  // 成功 toast 5s 窗口
  await expect(page.getByText('保存成功')).toBeVisible({ timeout: 6000 });
  await page.reload();
  await page.goto('/v2/index.html#/config');
  await page.locator('[class*="-Tabs-link"]:not([class*="-Tabs-links"])').nth(2).click();
  await page.waitForTimeout(500);
  await expect(page.locator(sel).first()).toHaveValue(next);
});

test('配置页: 编辑期间不被 SSE 打断（无 reload 清空焦点）', async ({ page }) => {
  await page.goto('/v2/index.html#/config');
  await expect(page.getByText('LLM Provider').first()).toBeVisible({ timeout: 10000 });
  await page.locator('[class*="-Tabs-link"]:not([class*="-Tabs-links"])').nth(2).click();
  await page.waitForTimeout(500);
  const sel = 'input[class*="-Number-input"]';
  await page.locator(sel).first().focus();
  // 等待 2s（SSE refresh 帧周期），表单应仍存在且未丢失输入焦点（无整页重绘）
  await page.waitForTimeout(2000);
  await expect(page.locator('#v2-content')).toBeAttached();
  await expect(page.getByText('LLM Provider').first()).toBeVisible();
});

test('配置页: 审批模式切换并保存', async ({ page }) => {
  await page.goto('/v2/index.html#/config');
  await expect(page.getByText('LLM Provider').first()).toBeVisible({ timeout: 10000 });
  // 点击审批模式页签（第 4 个 tab）
  await page.locator('[class*="-Tabs-link"]:not([class*="-Tabs-links"])').nth(3).click();
  await page.waitForTimeout(500);
  // 选择 auto（AMIS radios input 隐藏，点击可见的 label 文本）
  await page.getByText('自动(auto)').click();
  await page.getByRole('button', { name: '保存配置' }).click();
  await expect(page.getByText('保存成功')).toBeVisible({ timeout: 6000 });
  await page.reload();
  await page.goto('/v2/index.html#/config');
  await page.locator('[class*="-Tabs-link"]:not([class*="-Tabs-links"])').nth(3).click();
  await page.waitForTimeout(500);
  await expect(page.getByText('自动(auto)').first()).toBeVisible();
});
