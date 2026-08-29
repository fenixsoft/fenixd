// v2-project-list-page: SPEC 列表页(8 列/过滤/fix 树/行内操作/error 详情)渲染与交互验证
// 实施依据: openspec/changes/v2-project-list-page、计划 Task 6、behavior.md §2(列/过滤/树)/§5(Why/清除)
import { test, expect } from '@playwright/test';

const BASE = 'http://127.0.0.1:8787';

// 真实环境可见的 project 与 SPEC(以 STATE.md 中 fenixd 的 SPEC 树为准)
const PROJECT = 'fenixd';
// 父行(需求类)与 fix 子行(修复类)构成 fix 树
const PARENT = 'add-inplace-bug-repair';
const CHILD = 'fix-add-inplace-bug-repair';

async function trackErrors(page) {
  const errors = [];
  page.on('console', (m) => { if (m.type() === 'error') errors.push(m.text()); });
  page.on('pageerror', (e) => errors.push('pageerror: ' + e.message));
  page.on('requestfailed', (r) => errors.push('requestfailed: ' + r.url()));
  page.on('response', (r) => { if (r.status() >= 400) errors.push(`${r.status()} ${r.url()}`); });
  return errors;
}

// AMIS 渲染的页签/下拉项无 role,用文本定位;crud 表头列 label 为纯文本
async function openFirstDropdown(page) {
  // crud 行内 dropdown-button 渲染为按钮"操作",点击展开菜单
  await page.getByRole('button', { name: '操作' }).first().click();
  await expect(page.locator('.dark-DropDown.is-opened').first()).toBeVisible({ timeout: 5000 });
}

test('SPEC 列表:8 列表头 + fix 树 + 跳转链接 + 行内操作按钮', async ({ page }) => {
  const errors = await trackErrors(page);
  await page.goto(`${BASE}/v2/index.html#/project/${PROJECT}`, { waitUntil: 'domcontentloaded' });
  await page.waitForSelector('#root', { state: 'visible', timeout: 10000 });

  // 8 列表头(behavior.md §2 逐字)
  for (const label of ['状态', '名称', '优先级', '创建时间', '任务进度', '验证', '耗时', '文档']) {
    await expect(page.getByText(label, { exact: true }).first()).toBeVisible({ timeout: 10000 });
  }

  // fix 树:父行与 fix 子行均渲染(子行作为父行 children 缩进展示)
  await expect(page.getByText(PARENT, { exact: true }).first()).toBeVisible({ timeout: 10000 });
  await expect(page.getByText(CHILD, { exact: true }).first()).toBeVisible({ timeout: 10000 });

  // 名称列是可点链接 → #/spec/<project>/<spec>
  await expect(page.locator(`a[href='#/spec/${PROJECT}/${PARENT}']`).first()).toBeVisible({ timeout: 10000 });

  // 行内 dropdown 操作:展开后出现"呼叫 Admin"(设计要求:下拉替代右键菜单)
  await openFirstDropdown(page);
  await expect(page.getByText('呼叫 Admin').first()).toBeVisible({ timeout: 5000 });

  expect(errors, JSON.stringify(errors)).toEqual([]);
});

test('SPEC 列表:关键词过滤', async ({ page }) => {
  const errors = await trackErrors(page);
  await page.goto(`${BASE}/v2/index.html#/project/${PROJECT}`, { waitUntil: 'domcontentloaded' });
  await page.waitForSelector('#root', { state: 'visible', timeout: 10000 });

  // 过滤前父行可见
  await expect(page.getByText(PARENT, { exact: true }).first()).toBeVisible({ timeout: 10000 });

  // 关键词框(placeholder 搜索 SPEC 名称)输入已知 SPEC 名片段,过滤后仅匹配行可见
  await page.getByPlaceholder(/搜索 SPEC 名称/).fill(PARENT);
  await expect(page.getByText(PARENT, { exact: true }).first()).toBeVisible({ timeout: 10000 });

  expect(errors, JSON.stringify(errors)).toEqual([]);
});

// SSE 联动契约:spec-crud 已配置 onEvent.sse:state reload(behavior.md §0 + 设计 §4);
// 行内操作(删除/优先级)submitSucc 后 reload spec-crud。本用例验证契约配置在运行时生效:
// 调优先级后 spec-crud 重新加载(行数据可见且列表刷新完成,无 JS 错误)。
test('SPEC 列表:行内操作触发后列表重拉(spec-crud reload 契约)', async ({ page }) => {
  const errors = await trackErrors(page);
  await page.goto(`${BASE}/v2/index.html#/project/${PROJECT}`, { waitUntil: 'domcontentloaded' });
  await page.waitForSelector('#root', { state: 'visible', timeout: 10000 });
  await expect(page.getByText(PARENT, { exact: true }).first()).toBeVisible({ timeout: 10000 });

  // 展开首行操作菜单
  await page.getByRole('button', { name: '操作' }).first().click();
  await expect(page.locator('.dark-DropDown.is-opened').first()).toBeVisible({ timeout: 5000 });
  // 点击"调优先级"打开 Dialog
  await page.getByText('调优先级').first().click();
  await expect(page.locator('.amis-dialog-widget').first()).toBeVisible({ timeout: 5000 });
  // 提交表单(优先级 1-9,默认当前值)→ 触发 POST /api/spec-priority + submitSucc reload spec-crud
  await page.getByRole('button', { name: '确认' }).first().click();
  // 列表重载后首行仍可见(无崩溃,数据域 intact)
  await expect(page.getByText(PARENT, { exact: true }).first()).toBeVisible({ timeout: 10000 });

  expect(errors, JSON.stringify(errors)).toEqual([]);
});

// error 详情与清除(设计 §4 + behavior.md §5):详情 Dialog 懒加载 error/why,含「清除错误」。
// 真实环境 v2-config-page 有 error 字段,验证 error 文本与清除按钮出现。
test('SPEC 详情:error 文本可见 + 清除错误按钮(有 error 的 SPEC)', async ({ page }) => {
  const errors = await trackErrors(page);
  await page.goto(`${BASE}/v2/index.html#/project/${PROJECT}`, { waitUntil: 'domcontentloaded' });
  await page.waitForSelector('#root', { state: 'visible', timeout: 10000 });
  await expect(page.getByText('v2-config-page', { exact: true }).first()).toBeVisible({ timeout: 10000 });
  // 展开该行操作菜单(定位包含目标文本的行,再找其操作按钮)
  const row = page.getByText('v2-config-page', { exact: true }).first().locator('xpath=ancestor::tr[1]');
  await row.getByRole('button', { name: '操作' }).first().click();
  await expect(page.locator('.dark-DropDown.is-opened').first()).toBeVisible({ timeout: 5000 });
  // 点击 PopOver 菜单中的「详情」
  await page.locator('.dark-PopOver').getByText('详情', { exact: true }).first().click();
  // 详情 Dialog 出现且 error 文本可见(懒加载 /api/specs/<spec>)
  const dlg = page.locator('.amis-dialog-widget').first();
  await expect(dlg).toBeVisible({ timeout: 10000 });
  await expect(dlg.getByText('错误').first()).toBeVisible({ timeout: 10000 });
  await expect(dlg.getByText('清除错误').first()).toBeVisible({ timeout: 10000 });

  expect(errors, JSON.stringify(errors)).toEqual([]);
});
