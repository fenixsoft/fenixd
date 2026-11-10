// projectHomeShared.ts — 项目首页页签纯函数（add-project-home-tab）
//
// 零依赖、无 JSX（node --test 直测形态，对齐 listFilters.ts 先例）：
// URL `path` 参数解析、路径拆解、面包屑段、相对时间与字节量展示文案。
// 合法性（containment）不在纯函数层负责——由后端 400/404 兜底。

/** URL `path` 参数归一化：按 '/' 拆段并剔除空段后重组——消化首尾斜杠与
 *  连续斜杠（'/core//dashboard/' → 'core/dashboard'）；null/空串回根目录
 *  空串。不触浏览器 URL（解码已由 URLSearchParams 完成）。 */
export function parseHomePath(raw: string | null | undefined): string {
  return (raw || '').split('/').filter(Boolean).join('/');
}

/** 路径拆解：末段与其父目录（'core/scheduler.py' → {dir:'core',
 *  name:'scheduler.py'}；无斜杠 → {dir:'', name:<原串>}）。入参须已经
 *  parseHomePath 归一化。 */
export function splitHomePath(p: string): { dir: string; name: string } {
  const i = p.lastIndexOf('/');
  return i >= 0 ? { dir: p.slice(0, i), name: p.slice(i + 1) } : { dir: '', name: p };
}

/** 面包屑段数组（不含根节点）：'core/dashboard' → ['core','dashboard']；
 *  根目录为空数组。 */
export function homeCrumbs(p: string): string[] {
  return p ? p.split('/').filter(Boolean) : [];
}

/** 相对时间文案（spec「如『2 小时前』」；秒/分/时/天/周/月/年七档，原型
 *  出现过「N 周前」档）。非法时间串与未来时间（时钟偏移）回退「刚刚」/
 *  「—」。数值部分由调用方以 tabular-nums 展示。 */
export function formatRelativeTime(iso: string, now: number = Date.now()): string {
  const t = Date.parse(iso);
  if (Number.isNaN(t)) return '—';
  const s = Math.max(0, Math.floor((now - t) / 1000));
  if (s < 60) return '刚刚';
  const m = Math.floor(s / 60);
  if (m < 60) return `${m} 分钟前`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h} 小时前`;
  const d = Math.floor(h / 24);
  if (d < 7) return `${d} 天前`;
  if (d < 30) return `${Math.floor(d / 7)} 周前`;
  const mo = Math.floor(d / 30);
  if (mo < 12) return `${mo} 个月前`;
  return `${Math.max(1, Math.floor(d / 365))} 年前`;
}

/** 字节量展示文案：<1 KiB 原样 B；KiB 档一位小数；MiB 档两位小数。 */
export function formatBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / (1024 * 1024)).toFixed(2)} MB`;
}
