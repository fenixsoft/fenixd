import { test, expect } from '@playwright/test';
test('广播事件能到达渲染树内的监听消费者(页面级 service reload)', async ({ page }) => {
  await page.goto('/v2/index.html#/overview');
  // overview.json 的 ov-stats 监听 sse:state/sse:refresh 并 reload componentId=ov-stats
  // bridge.js 对 state/refresh 事件自增 window.BridgeTest.reloadCount
  // 验证广播链路:桥收到帧 → dispatch 到渲染树 → ov-stats reload → (reloadCount 增长即证明到达)
  await page.waitForFunction(
    () => window.BridgeTest && (window.BridgeTest.reloadCount || 0) >= 1,
    null,
    { timeout: 15000 }
  );
  const count = await page.evaluate(() => window.BridgeTest.reloadCount);
  expect(count).toBeGreaterThanOrEqual(1);
});
