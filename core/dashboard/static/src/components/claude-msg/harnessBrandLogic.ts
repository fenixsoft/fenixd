// 品牌解析纯逻辑（add-harness-brand-projection 1.1）——无 React 依赖，
// node --test（Node ≥22.18 原生 type-stripping）可直载 .ts 源做回退链
// 三分支单测（tests/harnessBrand.test.mjs）。React 侧组件装配见
// HarnessBrand.tsx（.tsx 无法被 node 原生 loader 识别，JSX 装配层由构建
// 与类型检查验证——与仓库既有「纯函数 .ts 直测 + 组件 .tsx 构建验证」
// 分层同款，先例 toolGrouping.ts / listFilters.ts）。

// 回退链三分支（spec「回退链」Requirement）：
// - default：run meta 无 harness 字段（存量 run）→ claude 品牌，行为零变化；
// - registered：harness 值命中注册表（claude/dsh）→ 对应注册品牌；
// - fallback：未注册值（如 `pi`）→ 首字母徽标（圆形底 + 大写首字母），不抛错。
export type HarnessResolution =
  | { kind: 'default'; name: 'claude' }
  | { kind: 'registered'; name: string }
  | { kind: 'fallback'; name: string; letter: string };

// 已注册图标品牌的 harness 集（组件装配表见 HarnessBrand.tsx）
const REGISTERED_HARNESSES = new Set(['claude', 'dsh']);

// context 缺省品牌名（= Claude 品牌，spec「缺省品牌等于现状」Scenario：
// 未注入 Provider 的使用点渲染结果与改造前一致）
export const DEFAULT_BRAND_NAME = 'Claude';

export function resolveHarness(harness?: string | null): HarnessResolution {
  const raw = typeof harness === 'string' ? harness.trim() : '';
  // 无字段/空值 → 缺省 claude（存量 run 与指标行缺键路径共用此回退）
  if (!raw) {
    return { kind: 'default', name: 'claude' };
  }
  // 注册表命中判定做大小写归一；命中名归一小写（与写侧 adapter.name 小写
  // 约定一致），标签显示经品牌装配表取注册名
  const normalized = raw.toLowerCase();
  if (REGISTERED_HARNESSES.has(normalized)) {
    return { kind: 'registered', name: normalized };
  }
  // 未知值 → 首字母徽标：大写首码点（'pi' → 'P'），标签保留原值展示
  const letter = (raw.charAt(0) || '?').toUpperCase();
  return { kind: 'fallback', name: raw, letter };
}
