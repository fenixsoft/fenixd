// codeFixGuidance.ts — code-fix blocked 终态的人类可读原因与处置指引（纯逻辑，
// 零 React 依赖，供 CodeFixProgressCard 渲染）。
// 文案经 useIntl（i18n 修复轮 batch-P：本文件静态中文文案迁 i18n 目录）。
//
// 背景（2026-09-25 用户反馈）：blocked 时界面此前只标「已阻塞」+ 英文 reason
// 原码透传（「原因：wip_overlap_at_select」），处置指引埋在 current 长句里，
// 用户看不出该做什么。本模块把 reason 码收敛为「人类可读原因 + 如何处理」
// 双段文案，blocked 时在进度卡内独立成行醒目渲染。
//
// i18n 注记（batch-P）：本模块无 React 上下文（被 CodeFixProgressCard 在
// 渲染期调用），文案经 getIntl() 渲染期求值（先例：utils/format.ts——调用期
// 判别，极端早调用回退 zh 目录查表不抛错）；BLOCKED_REASONS 表内只存 intl
// 目录键。原 node --test 直载单测因 '@umijs/max' 运行时依赖退役，改由
// codeFixGuidance.test.mjs 源码扫描 + zh 目录交叉钉接线（钉 intl id 而非中文串）。
//
// 键与 core/code_fix.py 全部 blocked 写入点的 reason 同源盘点（2026-09-25）：
//   disabled / failed_batch_retained / failed_batch_maxed / wip_gate_blocked /
//   wip_overlap_at_select / regression_contract_missing / regression_section_missing /
//   zero_progress_paused
// 后端新增 reason 的漂移由 blockedReasonInfo 的「宁严勿松」回退兜底
// （显示原码 + 需人工排查，不静默、不给误导性指引）。

import { getIntl } from '@umijs/max';
import zhCN from '../../../locales/zh-CN';

export interface BlockedReasonInfo {
  /** 人类可读原因（一行内说清发生了什么） */
  label: string;
  /** 处置指引（明确告诉用户下一步做什么；自愈等待类说明「无需处理」） */
  guidance: string;
}

// 渲染期取文案：getIntl 挂载后恒就绪；极端早调用（无 intl 上下文）回退
// zh 目录查表（zh-CN.ts 为唯一中文源，不复制文案），再兜底原键不抛错。
const t = (id: string): string => {
  try {
    return getIntl().formatMessage({ id });
  } catch {
    return (zhCN as Record<string, string>)[id] ?? id;
  }
};

// 后端已知 blocked reason → 原因 + 处置指引的 intl 目录键。文案口径与
// code_fix.py 各写入点的 current 保持同义（backend 改文案时同步这里与目录）。
const BLOCKED_REASONS: Record<string, { labelId: string; guidanceId: string }> = {
  wip_overlap_at_select: {
    labelId: 'projects.codeFixBlocked.wipOverlapAtSelect.label',
    guidanceId: 'projects.codeFixBlocked.wipOverlapAtSelect.guidance',
  },
  wip_gate_blocked: {
    labelId: 'projects.codeFixBlocked.wipGateBlocked.label',
    guidanceId: 'projects.codeFixBlocked.wipGateBlocked.guidance',
  },
  disabled: {
    labelId: 'projects.codeFixBlocked.disabled.label',
    guidanceId: 'projects.codeFixBlocked.disabled.guidance',
  },
  failed_batch_retained: {
    labelId: 'projects.codeFixBlocked.failedBatchRetained.label',
    guidanceId: 'projects.codeFixBlocked.failedBatchRetained.guidance',
  },
  failed_batch_maxed: {
    labelId: 'projects.codeFixBlocked.failedBatchMaxed.label',
    guidanceId: 'projects.codeFixBlocked.failedBatchMaxed.guidance',
  },
  regression_contract_missing: {
    labelId: 'projects.codeFixBlocked.regressionContractMissing.label',
    guidanceId: 'projects.codeFixBlocked.regressionContractMissing.guidance',
  },
  regression_section_missing: {
    labelId: 'projects.codeFixBlocked.regressionSectionMissing.label',
    guidanceId: 'projects.codeFixBlocked.regressionSectionMissing.guidance',
  },
  zero_progress_paused: {
    labelId: 'projects.codeFixBlocked.zeroProgressPaused.label',
    guidanceId: 'projects.codeFixBlocked.zeroProgressPaused.guidance',
  },
};

// 自愈等待类 reason（后端语义：链收敛的正常等待，下一审查轮到来自动重试/
// 边界重试，对应 BLOCKED_REASONS 中 guidance 为「无需处理」的条目）。集合与
// 指引文案同在本文件同点维护（code-review item 5400cd0de2c3）：后端新增自愈
// 类 blocked reason 只需同步这里两处，不再需要另改渲染组件。
const SELFHEAL_WAIT_REASONS: ReadonlySet<string> = new Set([
  'wip_gate_blocked',
  'failed_batch_retained',
]);

/**
 * 是否自愈等待类 blocked reason（渲染方据此呈现中性等待态而非红色故障）。
 * 未知/空 reason 返回 false（宁严勿松，按需人工样式回退，漂移不静默）。
 */
export function isSelfhealWait(reason: string | null | undefined): boolean {
  return reason !== null && reason !== undefined && reason !== '' && SELFHEAL_WAIT_REASONS.has(reason);
}

/**
 * 是否已知 blocked reason：非空且命中 BLOCKED_REASONS 表。blockedReasonInfo
 * 与 blockedReasonDisplay 共用的已知性判定（口径改动只改这一处）。
 * hasOwnProperty 排除 Object.prototype 继承键（constructor/toString 等），
 * 避免未知 reason 误入「已知」分支后取不到 label/guidance。
 */
function isKnownReason(reason: string | null | undefined): reason is string {
  return (
    reason !== null &&
    reason !== undefined &&
    reason !== '' &&
    Object.prototype.hasOwnProperty.call(BLOCKED_REASONS, reason)
  );
}

/**
 * reason → 展示信息；未知 reason 宁严勿松回退（原码 + 需人工排查），
 * 与 isSelfhealWait 对未知/空 reason 判 false 的「漂移不静默」口径一致。
 */
export function blockedReasonInfo(reason: string | null | undefined): BlockedReasonInfo {
  if (isKnownReason(reason)) {
    const ids = BLOCKED_REASONS[reason];
    return { label: t(ids.labelId), guidance: t(ids.guidanceId) };
  }
  return {
    label: reason || t('projects.codeFixBlocked.unknownLabel'),
    guidance: t('projects.codeFixBlocked.unknownGuidance'),
  };
}

/**
 * 原因行的完整展示文案：人类可读 label 带上原码括注（取证口径不丢）；
 * 未知 reason 原样回显（此时 label 即原码，不重复括注）。
 */
export function blockedReasonDisplay(reason: string | null | undefined): string {
  const known = isKnownReason(reason);
  if (!reason) {
    return t('projects.codeFixBlocked.unknownLabel');
  }
  return known ? `${t(BLOCKED_REASONS[reason].labelId)}（${reason}）` : reason;
}
