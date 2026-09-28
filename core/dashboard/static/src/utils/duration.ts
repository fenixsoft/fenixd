// 时长展示格式化单源（code-review item f8307715a795）：spec 列表「耗时」列与
// spec 详情页（项目信息卡片/时间轴节点耗时）原先各自维护逐行相同的实现，
// 修格式口径需两处同步，收敛到本模块（对齐 @/utils/tokens 的抽单源先例）。
// 口径：秒/分/时三段进位，末段为零省略（59秒 / 1分1秒 / 1时0分5秒）。

export function fmtDuration(sec?: number | null) {
  // 显式 null/undefined 判等（code-review item 95013c6683be）：宽松相等被
  // 项目 lint 禁止，意图为「null 或 undefined」时逐值显式比较。
  if (sec === null || sec === undefined || Number.isNaN(sec)) return '';
  let s = Math.max(0, Math.round(sec));
  if (s < 60) return `${s}秒`;
  const m = Math.floor(s / 60);
  s %= 60;
  if (m < 60) return s ? `${m}分${s}秒` : `${m}分`;
  return `${Math.floor(m / 60)}时${m % 60}分${s ? `${s}秒` : ''}`;
}
