// 品牌解析纯逻辑（add-harness-brand-projection 1.1）——无 React 依赖，
// node --test（Node ≥22.18 原生 type-stripping）可直载 .ts 源做回退链
// 三分支单测（tests/harnessBrand.test.mjs）。React 侧组件装配见
// HarnessBrand.tsx（.tsx 无法被 node 原生 loader 识别，JSX 装配层由构建
// 与类型检查验证——与仓库既有「纯函数 .ts 直测 + 组件 .tsx 构建验证」
// 分层同款，先例 toolGrouping.ts / listFilters.ts）。

// 回退链三分支（spec「回退链」Requirement；2026-10-29 用户定稿：缺省分支
// claude → 中性品牌——run meta 无 harness 字段不再冒充 Claude，装配层映射
// 中性「AI Assistant」+「AI」首字母徽标）：
// - default：run meta 无 harness 字段（存量 run）→ 中性（name 字段省略，
//   中性品牌非注册品牌、无小写标识语义）；
// - registered：harness 值命中注册表（claude/dsh）→ 对应注册品牌；
// - fallback：未注册值（如 `pi`）→ 首字母徽标（圆形底 + 大写首字母），不抛错。
export type HarnessResolution =
  | { kind: 'default' }
  | { kind: 'registered'; name: string }
  | { kind: 'fallback'; name: string; letter: string };

// 已注册图标品牌的 harness 名单（单源：HarnessBrand.tsx 品牌装配表的
// 键集由 RegisteredHarnessName 类型约束，新增注册品牌漏配装配表时
// 编译期即报错，不再依赖人工同步两处）
export const REGISTERED_HARNESS_NAMES = ['claude', 'dsh'] as const;

export type RegisteredHarnessName = (typeof REGISTERED_HARNESS_NAMES)[number];

const REGISTERED_HARNESSES: ReadonlySet<string> = new Set(REGISTERED_HARNESS_NAMES);

// context 缺省品牌名（= Claude 品牌，spec「缺省品牌等于现状」Scenario：
// SessionPanel 等 claude 专用车道未注入 Provider，渲染结果与改造前一致；
// 注意与 resolveHarness 缺省分支的中性品牌无关——那是 run 视图注入点的
// meta 缺失路径，2026-10-29 起映射中性「AI Assistant」）
export const DEFAULT_BRAND_NAME = 'Claude';

export function resolveHarness(harness?: string | null): HarnessResolution {
  const raw = typeof harness === 'string' ? harness.trim() : '';
  // 无字段/空值 → 中性缺省（存量 run 与指标行缺键路径共用此回退；不再
  // 假定 claude——无 meta 的 run 可能来自任何 harness）
  if (!raw) {
    return { kind: 'default' };
  }
  // 注册表命中判定做大小写归一；命中名归一小写（与写侧 adapter.name 小写
  // 约定一致），标签显示经品牌装配表取注册名
  const normalized = raw.toLowerCase();
  if (REGISTERED_HARNESSES.has(normalized)) {
    return { kind: 'registered', name: normalized };
  }
  // 未知值 → 首字母徽标：大写首码点（'pi' → 'P'），标签保留原值展示
  const letter = raw.charAt(0).toUpperCase();
  return { kind: 'fallback', name: raw, letter };
}
