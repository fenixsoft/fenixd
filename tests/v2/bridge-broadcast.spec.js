import { test, expect } from '@playwright/test';
test('广播事件能到达渲染树内的监听消费者(壳级探针)', async ({ page }) => {
  await page.goto('/v2/index.html#/overview');
  // 桥组件在壳级挂载,监听 sse:refresh 并通过 window.Bridge._broadcastProbe.received 标记
  // (overview 页因 app 路由 404 预存问题无法渲染页级探针,改在壳级验证广播链路)
  // watcher.py 1s 扫描会自然产生 refresh 帧(behavior.md §0),15s 内必到
  await page.waitForFunction(
    () => window.Bridge && window.Bridge._broadcastProbe && window.Bridge._broadcastProbe.received === true,
    null,
    { timeout: 15000 }
  );
  const ok = await page.evaluate(() => window.Bridge._broadcastProbe.received);
  expect(ok).toBeTruthy();
});
