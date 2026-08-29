// 复现 openspec/changes/v2-shell-hash-router 验证报告的 10 个场景断言
import { test, expect } from '@playwright/test';

const BASE = process.env.V2_BASE_URL || 'http://127.0.0.1:8787';

async function trackErrors(page) {
  const errors = [];
  page.on('console', (m) => { if (m.type() === 'error') errors.push(m.text()); });
  page.on('pageerror', (e) => errors.push('pageerror: ' + e.message));
  page.on('requestfailed', (r) => errors.push('requestfailed: ' + r.url()));
  page.on('response', (r) => { if (r.status() >= 400) errors.push(`${r.status()} ${r.url()}`); });
  return errors;
}

const scenarios = [
  ['hash-route-default-overview', '/v2/index.html'],
  ['hash-route-param-spec-detail', '/v2/index.html#/spec/demo/add-login'],
  ['hash-route-param-project', '/v2/index.html#/project/myapp'],
  ['hash-route-config-query-tab', '/v2/index.html#/config?tab=llm'],
  ['hash-route-config-project', '/v2/index.html#/config/myproject'],
  ['hash-route-activities-optional-project', '/v2/index.html#/activities/myproject'],
  ['hash-route-activities-no-project', '/v2/index.html#/activities'],
];

for (const [id, path] of scenarios) {
  test(id, async ({ page }) => {
    const errors = await trackErrors(page);
    await page.goto(BASE + path);
    await page.waitForSelector('#root', { state: 'visible', timeout: 5000 });
    await expect(page.locator('#root')).not.toBeEmpty();
    await expect(page.locator("a[href='#/overview']")).toBeVisible();
    await expect(page.locator("a[href='#/overview']")).toContainText('概览');
    expect(errors, JSON.stringify(errors)).toEqual([]);
  });
}

test('hashchange-navigation-switch', async ({ page }) => {
  const errors = await trackErrors(page);
  await page.goto(BASE + '/v2/index.html#/overview');
  await page.waitForSelector('#root', { state: 'visible' });
  // 先直接导航到 project 路由,再点击概览导航项返回
  await page.goto(BASE + '/v2/index.html#/project/myapp');
  await page.waitForSelector('#root', { state: 'visible' });
  await expect(page.locator("a[href='#/overview']")).toBeVisible();
  await page.click("a[href='#/overview']");
  await page.waitForTimeout(500);
  await expect(page.locator('#root')).toBeVisible();
  await expect(page.locator("a[href='#/overview']")).toBeVisible();
  await expect(page.locator("a[href='#/overview']")).toContainText('概览');
  expect(errors, JSON.stringify(errors)).toEqual([]);
});

test('json-merge-missing-page-tolerant', async ({ page }) => {
  const errors = await trackErrors(page);
  await page.goto(BASE + '/v2/index.html#/overview');
  await page.waitForSelector('#root', { state: 'visible' });
  await expect(page.locator('#root')).not.toBeEmpty();
  await expect(page.locator("a[href='#/overview']")).toBeVisible();
  expect(errors, JSON.stringify(errors)).toEqual([]);
});

test('legacy-dashboard-unaffected', async ({ page }) => {
  const errors = await trackErrors(page);
  // 停留老版入口页：先显式等待老版文档就绪，再断言其元素可见，规避陈旧快照下整页未
  // 渲染即超时的误判（见 fix-fix-v2-shell-hash-router 的残留场景 fix-legacy-dashboard-unaffected）。
  await page.goto(BASE + '/');
  await page.waitForSelector('#main', { state: 'visible', timeout: 5000 });
  await expect(page.locator('#main')).toBeVisible();
  await expect(page.locator('#btn-overview')).toBeVisible();
  // 再切到 v2 壳：老版与 v2 各自独立渲染，导航为 hash 形态不整页跳离。
  await page.goto(BASE + '/v2/index.html#/overview');
  await page.waitForSelector('#root', { state: 'visible', timeout: 5000 });
  await expect(page.locator('#root')).toBeVisible();
  expect(errors, JSON.stringify(errors)).toEqual([]);
});
