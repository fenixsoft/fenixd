// HarnessBrand — 对话组件品牌投影 context（add-harness-brand-projection 1.1）。
//
// claude-msg 组件族不再字面耦合 'Claude'：消息头标签与头像图标经
// useHarnessBrand() 取得品牌值（{ name, Logo }），由 run 视图层
// （RunRecordModal / AdminRunModal）按 run meta 的 harness 字段经
// HarnessBrandProvider 外部投影注入。context 缺省值 = Claude 品牌——
// 未注入 Provider 的使用点（自由会话 SessionPanel 等 claude 专用车道）
// 行为与改造前逐字一致（spec「缺省品牌等于现状」）。
//
// 回退链（design Decision 3）：无 harness 字段 → claude；未注册值 →
// 首字母徽标（圆形底 + 大写首字母），不抛错白屏。三分支判定逻辑在
// harnessBrandLogic.ts（node --test 直测），本文件只做 React 装配。
import { createContext, useContext, useMemo, type ComponentType, type ReactNode } from 'react';

import ClaudeLogo from './ClaudeLogo';
import DshLogo from './DshLogo';
import { DEFAULT_BRAND_NAME, resolveHarness } from './harnessBrandLogic';

export type HarnessBrandValue = {
  name: string;
  Logo: ComponentType<{ className?: string }>;
};

// 首字母徽标（未知 harness 回退）：内联小组件，不依赖图标资产。
// 工厂闭包捕获 harness 名与首字母（每未注册值一个品牌实例）。
function makeInitialLetterBrand(name: string, letter: string): HarnessBrandValue {
  const InitialLetterBadge = ({ className = 'w-5 h-5' }: { className?: string }) => (
    <div
      aria-label={name}
      className={`flex h-full w-full items-center justify-center rounded-full bg-gray-500 text-sm font-medium text-white ${className}`}
    >
      {letter}
    </div>
  );
  InitialLetterBadge.displayName = `HarnessInitialBadge(${name})`;
  return { name, Logo: InitialLetterBadge };
}

// 品牌注册表：harness 名 → 品牌值。claude 缺省（label 保持 'Claude' 与
// 现状一致）；dsh 用官方鲸鱼图标（DshLogo.tsx）。
const CLAUDE_BRAND: HarnessBrandValue = { name: DEFAULT_BRAND_NAME, Logo: ClaudeLogo };
const DSH_BRAND: HarnessBrandValue = { name: 'dsh', Logo: DshLogo };

function brandForHarness(harness?: string | null): HarnessBrandValue {
  const resolution = resolveHarness(harness);
  if (resolution.kind === 'registered') {
    if (resolution.name === 'dsh') {
      return DSH_BRAND;
    }
    return CLAUDE_BRAND;
  }
  if (resolution.kind === 'fallback') {
    return makeInitialLetterBrand(resolution.name, resolution.letter);
  }
  return CLAUDE_BRAND;
}

// context 缺省值 = Claude 品牌（未注入 Provider 即现状行为）
const HarnessBrandContext = createContext<HarnessBrandValue>(CLAUDE_BRAND);

export function useHarnessBrand(): HarnessBrandValue {
  return useContext(HarnessBrandContext);
}

// run 视图注入点：harness 取自 run meta（runs.py 透出的 run_metrics 旁路行
// harness 键），缺失/未知值由 brandForHarness 走回退链。
export function HarnessBrandProvider({
  harness,
  children,
}: {
  harness?: string | null;
  children: ReactNode;
}) {
  const brand = useMemo(() => brandForHarness(harness), [harness]);
  return <HarnessBrandContext.Provider value={brand}>{children}</HarnessBrandContext.Provider>;
}
