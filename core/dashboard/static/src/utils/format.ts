// Token 数值压缩格式单源（code-review item 8c25c9229577）：v2 overview 与
// v2 specDetail 两页原先各持逐字相同的本地副本、靠「口径同 overview.compactWan」
// 类注释互锚，修口径需两处同步，收敛到本模块（对齐 @/utils/duration 的抽单源先例）。
// 口径：万/亿进位；两处「提前升档」均为防自相矛盾的既定设计——9999.95 万提前
// 升「亿」防「10000.0万」，9.95K 档提前升「万」防「10.0K→1.0万」跳档反复
// （[9950, 10000) 显示「1.0万」与顶档提前升档对称，维持既有展示行为不变）。

export function compactWan(n: number): string {
  // 非有限值守卫（code-review item fbd89f365f90）：NaN 走完比较链落到
  // String(n) 输出「NaN」进 DOM，±Infinity 命中亿档输出「Infinity亿」；
  // 口径对齐 tokens.ts 的 fmtMillions（Number.isFinite 守卫统一回退 0）。
  const safe = Number.isFinite(n) ? n : 0;
  if (safe / 1e4 >= 9999.95) return (safe / 1e8).toFixed(1) + '亿';
  if (safe >= 1e4) return (safe / 1e4).toFixed(1) + '万';
  if (safe / 1e3 >= 9.95) return (safe / 1e4).toFixed(1) + '万';
  if (safe >= 1e3) return (safe / 1e3).toFixed(1) + 'K';
  return String(safe);
}
