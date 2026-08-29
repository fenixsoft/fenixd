// v2-run-stream-modal: 运行记录实时流弹窗(run 模式)接入验证
// 实施依据: openspec/changes/v2-run-stream-modal、计划 Task 8、behavior.md §3(全协议)/§4(admin 状态机)
import { test, expect } from '@playwright/test';

const BASE = process.env.V2_BASE_URL || 'http://127.0.0.1:8787';

// 实时渲染测试用有 finished run 的 SPEC(v2-config-page 的 impl/planner-judge run 为 done)
const PROJECT_DONE = 'fenixd';
const SPEC_DONE   = 'v2-config-page';

// DELETE watch 断言用有 live (running) run 的 SPEC(v2-config-page 当前 planner-plan run 为 running)
const PROJECT_LIVE = 'fenixd';
const SPEC_LIVE    = 'v2-config-page';

async function trackErrors(page) {
  const errors = [];
  page.on('console', (m) => { if (m.type() === 'error') errors.push(m.text()); });
  page.on('pageerror', (e) => errors.push('pageerror: ' + e.message));
  page.on('requestfailed', (r) => errors.push('requestfailed: ' + r.url()));
  page.on('response', (r) => { if (r.status() >= 400) errors.push(`${r.status()} ${r.url()}`); });
  return errors;
}

async function openRunDialog(page, project, spec, nodeIdx) {
  await page.goto(`${BASE}/v2/index.html#/spec/${project}/${spec}`, { waitUntil: 'domcontentloaded' });
  await page.waitForSelector('#root', { state: 'visible', timeout: 10000 });
  // 等待 spec detail 渲染(Tabs 出现)——部分 SPEC 无 verdict 卡,用 Tabs 作为就绪信号
  await page.waitForSelector('.dark-Tabs-link', { state: 'visible', timeout: 10000 });
  await page.locator('.dark-Tabs-link', { hasText: '时间轴' }).first().click();
  await expect(page.locator('.dark-Tabs-pane.is-active').first()).toBeVisible({ timeout: 5000 });
  // nodeIdx: 时间轴中 kind==='run' 的节点才有 run_id;默认取第一个 run 节点(通常 index 2)
  const idx = typeof nodeIdx === 'number' ? nodeIdx : 2;
  const runNode = page.locator('.dark-TimelineItem').nth(idx);
  await expect(runNode).toBeVisible({ timeout: 5000 });
  await runNode.click();
  await expect(page.locator('.amis-dialog-widget').first()).toBeVisible({ timeout: 5000 });
}

// 事件流渲染: 时间轴 run 节点点击 → Dialog 可见且事件流内容非空
test('运行记录弹窗: 打开即拉取尾部并渲染事件流', async ({ page }) => {
  const errors = await trackErrors(page);
  // nodeIdx=3: v2-config-page timeline 中 planner-judge run(done)
  await openRunDialog(page, PROJECT_DONE, SPEC_DONE, 3);
  const dlg = page.locator('.amis-dialog-widget').first();
  await expect(dlg).toBeVisible({ timeout: 10000 });

  // RunStream 组件渲染出事件节点(每条事件一个 .rs-event)
  await expect(dlg.locator('.rs-event').first()).toBeVisible({ timeout: 10000 });
  const count = await dlg.locator('.rs-event').count();
  expect(count, `期望渲染出事件流,实际 .rs-event 数=${count}`).toBeGreaterThan(0);

  expect(errors, JSON.stringify(errors)).toEqual([]);
});

// 关闭退订: live run 弹窗关闭 → DELETE /api/runs/<id>/watch?cid= 被发出
// behavior.md §3:live run→POST watch(弹窗打开);关闭→DELETE watch(弹窗关闭)
test('运行记录弹窗(live run): 关闭即退订 DELETE watch', async ({ page }) => {
  // 拦截 DELETE watch 请求;断言其被发出(超时 15s 覆盖开弹窗 + 关闭)
  const deleteWatchPromise = page.waitForRequest((req) =>
    req.method() === 'DELETE' && /\/api\/runs\/[^/]+\/watch/.test(req.url()), { timeout: 15000 });

  await openRunDialog(page, PROJECT_LIVE, SPEC_LIVE, 7);
  await expect(page.locator('.amis-dialog-widget').first()).toBeVisible({ timeout: 10000 });

  // 关闭弹窗(X 按钮;AMIS 6.13.0 dialog closeOnEsc 可能不生效)
  await page.locator('.dark-Modal-close').first().click();
  await page.waitForTimeout(500);
  // 对话框关闭
  await expect(page.locator('.amis-dialog-widget').first()).toBeHidden({ timeout: 5000 });

  // DELETE watch 必须已被发出
  await deleteWatchPromise;
});
