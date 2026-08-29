import { test, expect } from '@playwright/test';
test('SSE 桥收到 hello 帧并广播(桥组件注册于壳级)', async ({ page }) => {
  await page.goto('/v2/index.html#/overview');
  // 行为规格 §0:hello 帧 {type:'hello', cid} 到达即广播 sse:hello
  await page.waitForFunction(() => window.BridgeTest?.lastEvent?.type === 'hello', null, { timeout: 10000 });
  const evt = await page.evaluate(() => window.BridgeTest.lastEvent);
  expect(evt.cid).toBeTruthy();
});
