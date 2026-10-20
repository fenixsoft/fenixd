// 百分比帮助函数单源（code-review item 0ccf867a0bdb / d7d303f389f6）：
// overview 页 IntroduceRow 与 ProjectCards 原先各自维护逐字相同的实现，
// 修口径（舍入方向/除零守卫）需两处同步，收敛到本模块
// （对齐 @/utils/duration 的抽单源先例）。

export function pct(done: number, total: number): number {
  // 非有限值（NaN/±Infinity）回 0、结果钳下限（code-review item 9b5f4f881c7f）：
  // 与 @/utils/duration 的防御口径看齐，异常数据不透传 NaN/负百分比到展示层。
  if (!Number.isFinite(done) || !Number.isFinite(total) || total <= 0) return 0;
  // 上限同钳 100（code-review item 551fbf47beec）：done > total（数据异常或
  // 统计口径错位）时不向展示层透传超过 100 的百分比，与 tokens.ts 命中率的
  // [0, 100] 钳制口径对齐。
  return Math.min(100, Math.max(0, Math.round((done / total) * 100)));
}
