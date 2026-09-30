// 百分比帮助函数单源（code-review item 0ccf867a0bdb / d7d303f389f6）：
// overview 页 IntroduceRow 与 ProjectCards 原先各自维护逐字相同的实现，
// 修口径（舍入方向/除零守卫）需两处同步，收敛到本模块
// （对齐 @/utils/duration 的抽单源先例）。

export function pct(done: number, total: number): number {
  return total > 0 ? Math.round((done / total) * 100) : 0;
}
