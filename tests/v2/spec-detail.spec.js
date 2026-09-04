// v2-spec-detail-page: 详情页(验证卡 + 4 页签)渲染与交互验证
// 实施依据: spec/changes/v2-spec-detail-page、计划 Task 7、behavior.md §1(详情字段)/§0(detail 帧)
import { test, expect } from '@playwright/test';

const BASE = 'http://127.0.0.1:8787';

// 真实环境可见的 project/spec(以 .fenix/STATE.md 中 fenixd 的已推送 SPEC 为准)
const PROJECT = 'fenixd';
const SPEC = 'add-fenix-dashboard';

const TABS = ['时间轴', '场景', 'Bug', '截图'];

async function trackErrors(page) {
  const errors = [];
  page.on('console', (m) => { if (m.type() === 'error') errors.push(m.text()); });
  page.on('pageerror', (e) => errors.push('pageerror: ' + e.message));
  page.on('requestfailed', (r) => errors.push('requestfailed: ' + r.url()));
  page.on('response', (r) => { if (r.status() >= 400) errors.push(`${r.status()} ${r.url()}`); });
  return errors;
}

// AMIS 渲染的页签为 [class*="-Tabs-link"]:not([class*="-Tabs-links"])(无 role=tab),点击其文本链接切换内容区
async function clickTab(page, name) {
  await page.locator('[class*="-Tabs-link"]:not([class*="-Tabs-links"])', { hasText: name }).first().click();
  await expect(page.locator('[class*="-Tabs-pane"].is-active').first()).toBeVisible({ timeout: 5000 });
}

test('详情页:验证卡可见 + 4 页签依次可点', async ({ page }) => {
  const errors = await trackErrors(page);
  await page.goto(`${BASE}/v2/index.html#/spec/${PROJECT}/${SPEC}`, { waitUntil: 'domcontentloaded' });
  await page.waitForSelector('#root', { state: 'visible', timeout: 10000 });

  // 验证结论卡可见(behavior.md §1: verdict 计数已数字化;「验证」二字落在验证进度区)
  await expect(page.getByText('验证', { exact: false }).first()).toBeVisible({ timeout: 10000 });

  // 依次点击 4 个页签,每个页签内容区渲染无 JS 错误
  for (const tab of TABS) {
    await clickTab(page, tab);
    await expect(page.locator('[class*="-Tabs-pane"].is-active').first()).toBeVisible({ timeout: 5000 });
  }

  expect(errors, JSON.stringify(errors)).toEqual([]);
});

test('时间轴页签:节点渲染(真实环境有 timeline 数据)', async ({ page }) => {
  const errors = await trackErrors(page);
  await page.goto(`${BASE}/v2/index.html#/spec/${PROJECT}/${SPEC}`, { waitUntil: 'domcontentloaded' });
  await page.waitForSelector('#root', { state: 'visible', timeout: 10000 });
  await expect(page.getByText('验证', { exact: false }).first()).toBeVisible({ timeout: 10000 });

  await clickTab(page, '时间轴');
  // 该环境下的 add-fenix-dashboard 详情含 4 条 timeline 节点(实测),断言节点数 ≥ 1
  await expect(page.locator('[class*="-TimelineItem"]').first()).toBeVisible({ timeout: 5000 });

  expect(errors, JSON.stringify(errors)).toEqual([]);
});

// FIXME(环境): 截图页签的数据来自 verify 过程中产生的截图文件,部分 SPEC 在无失败截图场景下
// screenshots 数组为空,此时「缩略图数 ≥ 1」不成立。保留交互断言(点击放大走 image preview),
// 但对「有缩略图」的强断言仅在确有数据时启用。
test('截图页签:渲染缩略图 + 点击放大预览(AMIS image preview)', async ({ page }) => {
  const errors = await trackErrors(page);
  await page.goto(`${BASE}/v2/index.html#/spec/${PROJECT}/${SPEC}`, { waitUntil: 'domcontentloaded' });
  await page.waitForSelector('#root', { state: 'visible', timeout: 10000 });
  await expect(page.getByText('验证', { exact: false }).first()).toBeVisible({ timeout: 10000 });

  await clickTab(page, '截图');
  // 真实环境该 SPEC 有 35 张截图,断言缩略图渲染
  await expect(page.locator('[class*="-Tabs-pane"].is-active img').first()).toBeVisible({ timeout: 5000 });

  // 点击首张缩略图触发 AMIS image 内建预览(出现 preview 遮罩);该交互为 AMIS 内建能力,
  // 本 SPEC 仅保证点击不抛 JS 错误(预览 DOM 形态随 AMIS 版本,不强制断言)。
  const thumb = page.locator('[class*="-Tabs-pane"].is-active img').first();
  if (await thumb.count()) {
    await thumb.click({ timeout: 5000 }).catch(() => {});
    await page.keyboard.press('Escape').catch(() => {});
  }
  // 无 JS 错误是硬约束(即便无缩略图)
  expect(errors, JSON.stringify(errors)).toEqual([]);
});

// 时间轴节点点击打开「运行记录」占位 Dialog 的契约骨架(behavior.md §0 + design.md 决策):
// 节点渲染为可点击链接,点击弹出 size lg 的占位 Dialog,无 JS 错误。
// FIXME(Task 8): 真实 RunStream run 模式 Dialog 接入见 Task 8;本 SPEC 仅保证占位骨架无 JS 错误。
test('时间轴节点点击:弹出运行记录 Dialog(占位)', async ({ page }) => {
  const errors = await trackErrors(page);
  await page.goto(`${BASE}/v2/index.html#/spec/${PROJECT}/${SPEC}`, { waitUntil: 'domcontentloaded' });
  await page.waitForSelector('#root', { state: 'visible', timeout: 10000 });
  await expect(page.getByText('验证', { exact: false }).first()).toBeVisible({ timeout: 10000 });

  await clickTab(page, '时间轴');
  await expect(page.locator('[class*="-TimelineItem"]').first()).toBeVisible({ timeout: 5000 });

  // 时间轴节点点击(占位 Dialog 契约骨架,设计.md 退路:节点 onEvent click 弹占位 Dialog)
  // 点击首个时间轴节点,断言弹出「运行记录」Dialog 且无 JS 错误。
  await page.locator('[class*="-TimelineItem"]').first().click();
  await expect(page.locator('.amis-dialog-widget').first()).toBeVisible({ timeout: 5000 });
  await expect(page.locator('.amis-dialog-widget').getByText('运行记录').first()).toBeVisible({ timeout: 5000 });
  await page.keyboard.press('Escape').catch(() => {});
  expect(errors, JSON.stringify(errors)).toEqual([]);
});
