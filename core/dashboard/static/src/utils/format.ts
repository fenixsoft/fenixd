// Token 数值压缩格式单源（code-review item 8c25c9229577）：v2 overview 与
// v2 specDetail 两页原先各持逐字相同的本地副本、靠「口径同 overview.compactWan」
// 类注释互锚，修口径需两处同步，收敛到本模块（对齐 @/utils/duration 的抽单源先例）。
// 口径：万/亿进位；两处「提前升档」均为防自相矛盾的既定设计——9999.95 万提前
// 升「亿」防「10000.0万」，9.95K 档提前升「万」防「10.0K→1.0万」跳档反复
// （[9950, 10000) 显示「1.0万」与顶档提前升档对称，维持既有展示行为不变）。
//
// add-framework-i18n-zh-en 3.5：单位词随界面语言取值——zh 档「万/亿」（口径
// 逐字不变），en 档 K/M/B（千进制进位）。经 getIntl() 调用期判别（非组件
// 上下文；本模块零测试直载、零 esbuild 测试链消费，可安全 import '@umijs/max'），
// 渲染期求值，语言切换即时生效。
import { getIntl } from '@umijs/max';

function isEnLocale(): boolean {
  try {
    return (getIntl().locale || '').startsWith('en');
  } catch {
    // intl 上下文未就绪（极端早调用）按 zh 缺省口径回退，不抛错
    return false;
  }
}

export function compactWan(n: number): string {
  // 非有限值守卫（code-review item fbd89f365f90）：NaN 走完比较链落到
  // String(n) 输出「NaN」进 DOM，±Infinity 命中亿档输出「Infinity亿」；
  // 口径对齐 tokens.ts 的 fmtMillions（Number.isFinite 守卫统一回退 0）。
  const safe = Number.isFinite(n) ? n : 0;
  if (isEnLocale()) {
    // en 档纯千进制（K/M/B），防跳档提前升档与 zh 同构（[999950, 1e6) 显
    // 「1.0M」、[9.9995e8, 1e9) 显「1.0B」）
    if (safe / 1e6 >= 999.95) return (safe / 1e9).toFixed(1) + 'B';
    if (safe >= 1e6) return (safe / 1e6).toFixed(1) + 'M';
    if (safe / 1e3 >= 999.95) return (safe / 1e6).toFixed(1) + 'M';
    if (safe >= 1e3) return (safe / 1e3).toFixed(1) + 'K';
    return String(safe);
  }
  if (safe / 1e4 >= 9999.95) return (safe / 1e8).toFixed(1) + '亿';
  if (safe >= 1e4) return (safe / 1e4).toFixed(1) + '万';
  if (safe / 1e3 >= 9.95) return (safe / 1e4).toFixed(1) + '万';
  if (safe >= 1e3) return (safe / 1e3).toFixed(1) + 'K';
  return String(safe);
}
