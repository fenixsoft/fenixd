// 时长展示格式化单源（code-review item f8307715a795）：spec 列表「耗时」列与
// spec 详情页（项目信息卡片/时间轴节点耗时）原先各自维护逐行相同的实现，
// 修格式口径需两处同步，收敛到本模块（对齐 @/utils/tokens 的抽单源先例）。
// 口径：秒/分/时三段进位，末段为零省略（59秒 / 1分1秒 / 1时0分5秒）。
// 文案经 useIntl/getIntl（i18n 修复轮 batch-A：本文件静态中文文案迁 i18n 目录）
// ——单位词经 utils/intlText.ts 渲染期取值（zh 秒/分/时，en s/m/h 紧凑形态）。
import { intlText } from './intlText.ts';

export function fmtDuration(sec?: number | null) {
  // 显式 null/undefined 判等（code-review item 95013c6683be）：意图为只排除
  // 「null 或 undefined」两种空值（0 等合法数值须保留展示），逐值显式比较。
  // 非有限值（NaN/±Infinity）一并回退空串（code-review item 0550d27895f6）：
  // Infinity 会穿透进位算术产出「Infinity时NaN分」串直接进 DOM。
  if (sec === null || sec === undefined || !Number.isFinite(sec)) return '';
  let s = Math.max(0, Math.round(sec));
  if (s < 60) return intlText('utils.duration.sec', { s });
  const m = Math.floor(s / 60);
  s %= 60;
  if (m < 60) return s ? intlText('utils.duration.min', { m }) + intlText('utils.duration.sec', { s }) : intlText('utils.duration.min', { m });
  return (
    intlText('utils.duration.hour', { h: Math.floor(m / 60) }) +
    intlText('utils.duration.min', { m: m % 60 }) +
    (s ? intlText('utils.duration.sec', { s }) : '')
  );
}
