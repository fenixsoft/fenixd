// 日期时间展示格式化单源（code-review item 13ec66ff34fe）：ArchitectureTab
// 生成时间、RegressionTab 执行时间（fmtExecTime）与 SpecTimeline 时间轴节点
// （组件内 fmtTime）原先各自维护逐字相同的实现（dayjs 解析 + isValid 判定
// 回退原文 + 'YYYY-MM-DD HH:mm:ss' 固定格式），仅函数名不同，改格式口径
// （时区标注/本地化）或修解析缺陷需三点人肉同步，收敛到本模块（仿
// utils/duration.ts 先例，对齐 @/utils/tokens 的抽单源先例）。
// 口径：快照为 UTC ISO，dayjs 按本地时区解析渲染（RegressionTab 头注
// 409fad9381a1：toLocaleString 输出随浏览器 locale 变化，与仓库其他页面的
// YYYY-MM-DD HH:mm:ss 口径不齐）；空值（null/undefined/空串）回退 fallback
// 占位符；解析失败回退原文（dayjs 解析失败返回 Invalid Date 而非抛异常，
// isValid 显式判后回退）。

import dayjs from 'dayjs';

export function fmtDateTime(iso?: string | null, fallback = '—') {
  if (!iso) return fallback;
  const d = dayjs(iso);
  return d.isValid() ? d.format('YYYY-MM-DD HH:mm:ss') : iso;
}
