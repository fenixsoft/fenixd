// embedMount.ts — 嵌入挂载启动参数单点（add-dashboard-embed-mode 1.1）。
//
// dsh 面板桥（dsh-plugins add-dsh-dashboard-bridge）把本前端以 iframe 嵌进
// dsh web 主面板：宿主按 `/fenix-dashboard/` 前缀反代到 daemon :8787，客户端
// 深链形态 `<prefix>/?embed=1&apiBase=<prefix>#<route>`。两参数均承载在
// location.search（位于 hash 之前，hash 路由导航不改 search），本模块在首次
// 使用时一次性解析并惰性缓存——文档生命周期内 search 不变，无需监听。
//
// - apiBase：API/流路径前缀（缺省 ''）。经 `withApiBase()` 供 services 层
//   单点前缀化（request() fetch、STREAM_URL、architectureDiagramUrl），
//   缺省时恒等返回、产出 URL 与现状逐字节一致。
// - embed：`embed=1` 时进入嵌入形态（`isEmbedMode()`），app.tsx 运行时布局
//   配置据此隐藏 ProLayout 全局侧栏与全局顶栏。
//
// 两参数独立解析、可组合、互不干扰。零 import：node 测试环境无 location，
// 经 `_setEmbedSearchParamsForTest()` 注血后生效（沿用 etagCache.test.mjs
// 的 type-stripping 直载先例）。

/** 解析结果（模块级惰性缓存，首次访问 location.search 时钉住）。 */
interface EmbedMountConfig {
  apiBase: string;
  embed: boolean;
}

let cached: EmbedMountConfig | null = null;
// 测试注入口覆盖值：非 null 时以此代替 location.search 解析（生产恒为 null）。
let injectedSearch: string | null = null;

function readSearch(): string {
  if (injectedSearch !== null) return injectedSearch;
  // node/SSR 环境无 location：按无参数处理（= 现状缺省行为）。
  const loc = (globalThis as { location?: { search?: string } }).location;
  return typeof loc?.search === 'string' ? loc.search : '';
}

// 安全约束：apiBase 拼进全部 fetch URL/STREAM_URL/iframe src（写请求载荷含
// apikey 等敏感配置），只接受宿主注入的反代路径前缀——以单个 '/' 开头且次字
// 符不为 '/' 或 '\'（协议相对 `//host`、`/\host` 会被 URL 解析当 authority 接
// 管全部 API 流量）；其余形态（含 scheme 的绝对 URL、裸相对路径）一律回退 ''
// 恒等缺省，同源行为不受影响。
const SAFE_API_BASE = /^\/(?![\/\\])[^\\]*$/;

function sanitizeApiBase(raw: string): string {
  return SAFE_API_BASE.test(raw) ? raw : '';
}

function parseEmbedMountConfig(search: string): EmbedMountConfig {
  const params = new URLSearchParams(search);
  return {
    apiBase: sanitizeApiBase(params.get('apiBase') ?? ''),
    embed: params.get('embed') === '1',
  };
}

function embedMountConfig(): EmbedMountConfig {
  if (!cached) cached = parseEmbedMountConfig(readSearch());
  return cached;
}

/** API/流路径前缀化单点：拼上 `apiBase` 查询参数（缺省 '' 时恒等返回）。
 *  斜杠归一：base 去尾部斜杠；path 缺头斜杠时补齐（`withApiBase('api/x')`
 *  亦得 `<base>/api/x`）。缺省（无 apiBase）时逐字节恒等，不得改动 path。 */
export function withApiBase(path: string): string {
  const base = embedMountConfig().apiBase.replace(/\/+$/, '');
  if (!base) return path;
  if (!path.startsWith('/')) return `${base}/${path}`;
  return `${base}${path}`;
}

/** 是否处于嵌入形态（location.search 含 `embed=1`）。 */
export function isEmbedMode(): boolean {
  return embedMountConfig().embed;
}

/** 测试注入口（生产零调用）：注入 search 覆盖值并清空惰性缓存，使后续
 *  `withApiBase`/`isEmbedMode` 以注入值重新解析；传 null 恢复读
 *  location.search。注血须先于依赖 import 期求值的常量（如 services 层
 *  STREAM_URL）——即先注血后动态 import。 */
export function _setEmbedSearchParamsForTest(search: string | null): void {
  injectedSearch = search;
  cached = null;
}
