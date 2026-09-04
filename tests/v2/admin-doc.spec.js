// v2-admin-doc-modals: Admin 处置弹窗接线 + SPEC 文档弹窗验证
// 实施依据: spec/changes/v2-admin-doc-modals、计划 Task 9、behavior.md §1(spec-doc 404 语义) / §4(等待态)
import { test, expect } from '@playwright/test';

const BASE = process.env.V2_BASE_URL || 'http://127.0.0.1:8787';

// 真实环境可见的 project 与 SPEC(以 .fenix/STATE.md 中 fenixd 的 SPEC 树为准)
const PROJECT = 'fenixd';
// 有文档的 SPEC(proposal 存在,behavior.md §1:200 + found:true)
const DOC_SPEC = 'v2-config-page';
// 不在 .fenix/STATE.md 的 spec(behavior.md §1:404 而非 found:false)→ 走「未找到文档」分支
const NO_DOC_SPEC = 'definitely-not-a-real-spec-xyz';

async function trackErrors(page) {
  const errors = [];
  page.on('console', (m) => {
    if (m.type() !== 'error') return;
    // spec-doc 404 分支预期报错(行为 §1 不在 .fenix/STATE.md 返回 404)→ 不计入错误
    if (m.text().includes('spec-doc') || m.text().includes('spec not found')) return;
    if (m.text().startsWith('Failed to load resource') && m.text().includes('spec-doc')) return;
    errors.push(m.text());
  });
  page.on('pageerror', (e) => errors.push('pageerror: ' + e.message));
  page.on('response', (r) => {
    if (r.url().includes('/api/spec-doc') && r.status() === 404) return; // 预期 404 分支
    if (r.status() >= 500) errors.push(`${r.status()} ${r.url()}`);
  });
  return errors;
}

// 在 SPEC 列表中展开某行「操作」下拉
async function openRowDropdown(page, specName) {
  const row = page.getByText(specName, { exact: true }).first().locator('xpath=ancestor::tr[1]');
  await row.getByRole('button', { name: '操作' }).first().click();
  await expect(page.locator('[class*="-DropDown"].is-opened').first()).toBeVisible({ timeout: 5000 });
}

test('文档弹窗:有文档 SPEC 渲染「需求背景」页签内容(非空)', async ({ page }) => {
  const errors = await trackErrors(page);
  await page.goto(`${BASE}/v2/index.html#/project/${PROJECT}`, { waitUntil: 'domcontentloaded' });
  await page.waitForSelector('#root', { state: 'visible', timeout: 10000 });
  await expect(page.getByText(DOC_SPEC, { exact: true }).first()).toBeVisible({ timeout: 10000 });

  // 点击「文档」列按钮(行为 §2:第 8 列文档链接 → 文档弹窗)
  await page.getByRole('button', { name: '文档' }).first().click();
  const dlg = page.locator('.amis-dialog-widget').first();
  await expect(dlg).toBeVisible({ timeout: 10000 });

  // 三个页签出现:需求背景/设计/任务清单
  await expect(dlg.getByText('需求背景', { exact: true }).first()).toBeVisible({ timeout: 5000 });
  await expect(dlg.getByText('设计', { exact: true }).first()).toBeVisible({ timeout: 5000 });
  await expect(dlg.getByText('任务清单', { exact: true }).first()).toBeVisible({ timeout: 5000 });

  // 「需求背景」为默认页签,内容非空(懒加载 /api/spec-doc?doc=proposal)
  await expect(dlg.locator('.doc-body').first()).toBeVisible({ timeout: 10000 });
  const bodyText = await dlg.locator('.doc-body').first().innerText();
  expect(bodyText.trim().length).toBeGreaterThan(0);

  expect(errors, JSON.stringify(errors)).toEqual([]);
});

test('文档弹窗:不存在的 spec 走 404 分支显示「未找到文档」', async ({ page }) => {
  const errors = await trackErrors(page);
  // 模拟 behavior.md §1:spec-doc 对不在 .fenix/STATE.md 的 spec 返回 404(非 found:false)。
  // 将所有 spec-doc 请求改写为 404,验证 404 分支渲染「未找到文档」。
  await page.route('**/api/spec-doc**', (route) =>
    route.fulfill({ status: 404, contentType: 'application/json', body: '{"error":"spec not found"}' }));

  await page.goto(`${BASE}/v2/index.html#/project/${PROJECT}`, { waitUntil: 'domcontentloaded' });
  await page.waitForSelector('#root', { state: 'visible', timeout: 10000 });
  await expect(page.getByText(DOC_SPEC, { exact: true }).first()).toBeVisible({ timeout: 10000 });

  // 点击「文档」列按钮打开弹窗(请求被改写为 404)
  await page.getByRole('button', { name: '文档' }).first().click();
  const dlg = page.locator('.amis-dialog-widget').first();
  await expect(dlg).toBeVisible({ timeout: 10000 });

  // 404 分支:显示「未找到文档」而非报错白板
  await expect(dlg.getByText('未找到文档', { exact: true }).first()).toBeVisible({ timeout: 10000 });

  // 404 由 spec-doc 端点返回是预期行为(behavior.md §1:不在 .fenix/STATE.md → 404)
  // SDK 会触发 console error「接口报错:...」,浏览器也会报「Failed to load resource: 404」
  // 这些都是 404 分支的正常错误,不计入测试失败
  const filtered = errors.filter(e =>
    !e.includes('接口报错') && !e.includes('Failed to load resource'));
  expect(filtered, JSON.stringify(filtered)).toEqual([]);
});

test('Admin 处置弹窗:点击「呼叫 Admin」进入等待态,关闭时 DELETE watch', async ({ page }) => {
  const errors = await trackErrors(page);

  // 拦截 watch 注销请求(page.on('request') 可靠捕获 DELETE)。
  // 同时 mock watch POST/DELETE 避免真实后端依赖;
  // page.on('request') 同步置位 deleteWatchCalled, page.route mock 避免 404。
  let deleteWatchCalled = false;
  page.on('request', (req) => {
    if (req.url().includes('/api/runs/') && req.url().includes('/watch') && req.method() === 'DELETE') {
      deleteWatchCalled = true;
    }
  });
  await page.route('**/api/runs/**/watch**', (route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: '{"ok":true}' }));
  await page.route('**/api/runs/**/watch?**', (route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: '{"ok":true}' }));
  // 拦截 admin invoke 与活动解析,避免真实呼叫框架 agent(仅接线冒烟)。
  // /api/specs/<spec> 首调延迟 600ms 返回已 resolved 的 admin_run_id:
  //   打开瞬间进入 WAITING(状态行「等待 Administrator 开始处置」,可断言),
  //   延迟后解析出 admin_run_id → RESOLVED 并注册 watch(behavior.md §4)。
  await page.route('**/api/spec-admin-invoke**', (route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: '{"ok":true,"project":"fenixd","spec":"v2-config-page","created":true}' }));
  let firstResolve = true;
  await page.route('**/api/specs/v2-config-page**', (route) => {
    const body = '{"name":"v2-config-page","status":"implementing","admin_activities":[{"id":"a1","status":"resolved","result":"resolved","admin_run_id":"admin-run-001"}]}';
    if (firstResolve) { firstResolve = false; return new Promise((res) => setTimeout(() => res(route.fulfill({ status: 200, contentType: 'application/json', body })), 600)); }
    return route.fulfill({ status: 200, contentType: 'application/json', body });
  });
  // run 尾部:live(运行中)→ watch 注册后保持,等待关闭弹窗时统一清理(DELETE)
  // 使用 status:"running" 而非 "done",否则 bootRun 会立即调 unsubscribe 注销 watch
  await page.route('**/api/runs/admin-run-001**', (route) =>
    route.fulfill({ status: 200, contentType: 'application/json',
      body: '{"run_id":"admin-run-001","exists":true,"status":"running","events":[],"total_events":0}' }));
  // SSE 未真实连接时 cid 为 null → watch 不注册(behavior.md §0:cid 必须来自 hello 帧)。
  // 测试注入 cid,使 admin RESOLVED 后真实 POST watch,关闭时才能断言 DELETE watch。
  await page.addInitScript(() => { window.Bridge = window.Bridge || {}; window.Bridge.cid = 'test-cid-123'; });

  await page.goto(`${BASE}/v2/index.html#/project/${PROJECT}`, { waitUntil: 'domcontentloaded' });
  await page.waitForSelector('#root', { state: 'visible', timeout: 10000 });
  await expect(page.getByText('v2-config-page', { exact: true }).first()).toBeVisible({ timeout: 10000 });

  // 展开操作菜单 → 点击「呼叫 Admin」
  await openRowDropdown(page, 'v2-config-page');
  await page.getByText('呼叫 Admin').first().click();

  // 弹窗出现且渲染 run-stream 组件(等待态由行为 §4 状态机驱动)
  const dlg = page.locator('.amis-dialog-widget').first();
  await expect(dlg).toBeVisible({ timeout: 10000 });
  // run-stream 挂载点出现(rs-status 状态行 + rs-stream 事件流容器)
  await expect(dlg.locator('.rs-status').first()).toBeVisible({ timeout: 10000 });

  // 等待态文案:状态行显示「等待 Administrator 开始处置」(behavior.md §4 WAITING 状态)
  // 状态机解析出 admin_run_id 后切 RESOLVED 并注册 watch(本测试拦截返回已 resolved)
  await expect(dlg.locator('.rs-status').first()).toContainText('等待', { timeout: 10000 });

  // 关闭弹窗 → onEvent.close 调 dispose() → DELETE watch 被发出(page.route 拦截断言)
  // 使用 取消 按钮(AMIS Dialog footer) 或 Escape 键关闭
  await dlg.getByRole('button', { name: '取消' }).first().click({ timeout: 5000 }).catch(async () => {
    await page.keyboard.press('Escape');
  });
  await expect(dlg).toBeHidden({ timeout: 5000 });
  expect(deleteWatchCalled, '关闭弹窗时应发出 DELETE watch 请求').toBe(true);

  expect(errors, JSON.stringify(errors)).toEqual([]);
});
