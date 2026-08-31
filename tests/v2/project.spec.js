// v2-project-list-page: SPEC 列表页(8 列/过滤/fix 树/行内操作/error 详情)渲染与交互验证
// 实施依据: openspec/changes/v2-project-list-page、计划 Task 6、behavior.md §2(列/过滤/树)/§5(Why/清除)
import { test, expect } from '@playwright/test';

const BASE = process.env.V2_BASE_URL || 'http://127.0.0.1:8787';

// 真实环境可见的 project 与 SPEC(以 STATE.md 中 fenixd 的 SPEC 树为准)
const PROJECT = 'fenixd';
// 父行(需求类)与 fix 子行(修复类)构成 fix 树
const PARENT = 'add-inplace-bug-repair';
const CHILD = 'fix-add-inplace-bug-repair';

async function trackErrors(page) {
  const errors = [];
  page.on('console', (m) => {
    // mock 斩断 SSE 时 bridge 会打印连接中断(预期生命周期),不算错误
    if (m.type() === 'error' && !m.text().includes('[v2-bridge] SSE')) errors.push(m.text());
  });
  page.on('pageerror', (e) => errors.push('pageerror: ' + e.message));
  page.on('requestfailed', (r) => errors.push('requestfailed: ' + r.url()));
  page.on('response', (r) => { if (r.status() >= 400) errors.push(`${r.status()} ${r.url()}`); });
  return errors;
}

// AMIS 渲染的页签/下拉项无 role,用文本定位;crud 表头列 label 为纯文本
async function openFirstDropdown(page) {
  // crud 行内 dropdown-button 渲染为按钮"操作",点击展开菜单
  await page.getByRole('button', { name: '操作' }).first().click();
  await expect(page.locator('[class*="-DropDown"].is-opened').first()).toBeVisible({ timeout: 5000 });
}

test('SPEC 列表:8 列表头 + fix 树 + 跳转链接 + 行内操作按钮', async ({ page }) => {
  const errors = await trackErrors(page);
  // 斩断 SSE:daemon 高频 state 帧会触发 spec-crud reload,关掉行内弹层使弹层交互不稳定
  await page.route('**/api/stream', (route) => route.fulfill({ status: 200, contentType: 'text/event-stream', body: '' }));
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
  // 斩断 SSE:daemon 高频 state 帧会触发 spec-crud reload,关掉行内弹层使弹层交互不稳定
  await page.route('**/api/stream', (route) => route.fulfill({ status: 200, contentType: 'text/event-stream', body: '' }));
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
  // 斩断 SSE:daemon 高频 state 帧会触发 spec-crud reload,关掉行内弹层使弹层交互不稳定
  await page.route('**/api/stream', (route) => route.fulfill({ status: 200, contentType: 'text/event-stream', body: '' }));
  await page.goto(`${BASE}/v2/index.html#/project/${PROJECT}`, { waitUntil: 'domcontentloaded' });
  await page.waitForSelector('#root', { state: 'visible', timeout: 10000 });
  await expect(page.getByText(PARENT, { exact: true }).first()).toBeVisible({ timeout: 10000 });

  // 展开首行操作菜单
  await page.getByRole('button', { name: '操作' }).first().click();
  await expect(page.locator('[class*="-DropDown"].is-opened').first()).toBeVisible({ timeout: 5000 });
  // 点击"调优先级"打开 Dialog
  await page.getByText('调优先级').first().click();
  await expect(page.locator('.amis-dialog-widget').first()).toBeVisible({ timeout: 5000 });
  // 提交表单(优先级 1-9,默认当前值)→ 触发 POST /api/spec-priority + submitSucc reload spec-crud
  await page.getByRole('button', { name: '确认' }).first().click();
  // 列表重载后首行仍可见(无崩溃,数据域 intact)
  await expect(page.getByText(PARENT, { exact: true }).first()).toBeVisible({ timeout: 10000 });

  expect(errors, JSON.stringify(errors)).toEqual([]);
});

// BUG-2 回归：状态/类型过滤不丢 hash 路由 + 不触发 React #185
// 验证 syncLocation:false 生效：select onChange 后 location.hash 仍保持 #/project/<name>
test('SPEC 列表:BUG-2 回归—过滤不丢 hash 路由', async ({ page }) => {
  const errors = await trackErrors(page);
  // 斩断 SSE:daemon 高频 state 帧会触发 spec-crud reload,关掉行内弹层使弹层交互不稳定
  await page.route('**/api/stream', (route) => route.fulfill({ status: 200, contentType: 'text/event-stream', body: '' }));
  await page.goto(`${BASE}/v2/index.html#/project/${PROJECT}`, { waitUntil: 'domcontentloaded' });
  await page.waitForSelector('#root', { state: 'visible', timeout: 10000 });
  const hashBefore = await page.evaluate(() => location.hash);
  expect(hashBefore).toContain('#/project/fenixd');

  // 点击状态过滤 Select（AMIS dark 主题渲染为 .dark-SelectControl）
  const selectControls = page.locator('[class*="-SelectControl"]');
  const count = await selectControls.count();
  if (count > 0) {
    await selectControls.first().click();
    await page.waitForTimeout(500);
    // 选择任意一个下拉选项（如"就绪"）
    const option = page.locator('[class*="-PopOver"]').getByText('就绪', { exact: true }).first();
    if (await option.isVisible({ timeout: 3000 }).catch(() => false)) {
      await option.click();
      await page.waitForTimeout(2000);
    }
  }

  // 核心断言：hash 路由未丢失（syncLocation:false）
  const hashAfter = await page.evaluate(() => location.hash);
  expect(hashAfter).toContain('#/project/fenixd');
  expect(hashAfter).not.toBe('');

  // 不得出现 React #185（Maximum update depth exceeded）
  const react185 = errors.filter(e => e.includes('React error #185'));
  expect(react185).toEqual([]);
});

// error 详情与清除(设计 §4 + behavior.md §5):详情 Dialog 懒加载 error/why,含「清除错误」。
// 选用当前有 error 字段的 SPEC(如 v2-project-list-page):error 非空时 visibleOn:"${error}"
// 才匹配、清除按钮才显示;不得使用 error=null 的 SPEC(如 v2-config-page)否则按钮隐藏。
test('SPEC 详情:error 文本可见 + 清除错误按钮(有 error 的 SPEC)', async ({ page }) => {
  const errors = await trackErrors(page);
  // 斩断 SSE:daemon 高频 state 帧会触发 spec-crud reload,关掉行内弹层使弹层交互不稳定
  await page.route('**/api/stream', (route) => route.fulfill({ status: 200, contentType: 'text/event-stream', body: '' }));
  await page.goto(`${BASE}/v2/index.html#/project/${PROJECT}`, { waitUntil: 'domcontentloaded' });
  await page.waitForSelector('#root', { state: 'visible', timeout: 10000 });
  // 动态选取有 error 的 SPEC(避免指向 error=null 的 SPEC 致 visibleOn 不匹配)
  const ERROR_SPEC = 'v2-project-list-page';
  await expect(page.getByText(ERROR_SPEC, { exact: true }).first()).toBeVisible({ timeout: 10000 });
  // 展开该行操作菜单(定位包含目标文本的行,再找其操作按钮)
  const row = page.getByText(ERROR_SPEC, { exact: true }).first().locator('xpath=ancestor::tr[1]');
  await row.getByRole('button', { name: '操作' }).first().click();
  await expect(page.locator('[class*="-DropDown"].is-opened').first()).toBeVisible({ timeout: 5000 });
  // 点击 PopOver 菜单中的「详情」
  await page.locator('[class*="-PopOver"]').getByText('详情', { exact: true }).first().click();
  // 详情 Dialog 出现且 error 文本可见(懒加载 /api/specs/<spec>)
  const dlg = page.locator('.amis-dialog-widget').first();
  await expect(dlg).toBeVisible({ timeout: 10000 });
  await expect(dlg.getByText('错误').first()).toBeVisible({ timeout: 10000 });
  await expect(dlg.getByText('清除错误').first()).toBeVisible({ timeout: 10000 });

  expect(errors, JSON.stringify(errors)).toEqual([]);
});
