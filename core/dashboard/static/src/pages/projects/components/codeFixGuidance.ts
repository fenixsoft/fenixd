// codeFixGuidance.ts — code-fix blocked 终态的人类可读原因与处置指引（纯逻辑，
// 零 React 依赖，供 CodeFixProgressCard 渲染与 node --test 直载单测）。
//
// 背景（2026-09-25 用户反馈）：blocked 时界面此前只标「已阻塞」+ 英文 reason
// 原码透传（「原因：wip_overlap_at_select」），处置指引埋在 current 长句里，
// 用户看不出该做什么。本模块把 reason 码收敛为「人类可读原因 + 如何处理」
// 双段文案，blocked 时在进度卡内独立成行醒目渲染。
//
// 键与 core/code_fix.py 全部 blocked 写入点的 reason 同源盘点（2026-09-25）：
//   disabled / failed_batch_retained / failed_batch_maxed / wip_gate_blocked /
//   wip_overlap_at_select / regression_contract_missing / regression_section_missing
// 后端新增 reason 的漂移由 blockedReasonInfo 的「宁严勿松」回退兜底
// （显示原码 + 需人工排查，不静默、不给误导性指引）。

export interface BlockedReasonInfo {
  /** 人类可读原因（一行内说清发生了什么） */
  label: string;
  /** 处置指引（明确告诉用户下一步做什么；自愈等待类说明「无需处理」） */
  guidance: string;
}

// 后端已知 blocked reason → 原因 + 处置指引。文案口径与 code_fix.py 各写入
// 点的 current 保持同义（backend 改文案时同步这里）。
const BLOCKED_REASONS: Record<string, BlockedReasonInfo> = {
  wip_overlap_at_select: {
    label: '主树有未提交改动与本批待修文件重叠，整批已推迟',
    guidance: '把主树这些文件的改动提交或 stash，下一轮选批自动恢复',
  },
  wip_gate_blocked: {
    label: '本批修复结果合回主树时被未提交改动阻断，已入延迟台账',
    guidance: '无需处理：占用解除后自动重试合回',
  },
  disabled: {
    label: '自动修复总开关已关闭，链已终止',
    guidance: '在设置页重新打开「自动修复」开关后重新触发',
  },
  failed_batch_retained: {
    label: 'open 条目均已跳过（链内跳过/预算内失败）',
    guidance: '无需处理：下轮审查自动重试',
  },
  failed_batch_maxed: {
    label: '部分条目已达自动重试上限，仍失败',
    guidance: '需人工：手工修复或在代码审查条目中忽略这些发现',
  },
  regression_contract_missing: {
    label: 'verify.yaml 回归契约缺失，链无法投批',
    guidance: '先起草 verify.yaml 契约（含 regression 段）',
  },
  regression_section_missing: {
    label: 'verify.yaml 缺 regression 段，链无法投批',
    guidance: '在 verify.yaml 中补写 regression 段',
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
  return reason != null && reason !== '' && SELFHEAL_WAIT_REASONS.has(reason);
}

/**
 * reason → 展示信息；未知 reason 宁严勿松回退（原码 + 需人工排查），
 * 与 isSelfhealWait 对未知/空 reason 判 false 的「漂移不静默」口径一致。
 */
export function blockedReasonInfo(reason: string | null | undefined): BlockedReasonInfo {
  // hasOwnProperty 排除 Object.prototype 继承键（constructor/toString 等），
  // 避免未知 reason 误入「已知」分支后取不到 label/guidance。
  if (reason && Object.prototype.hasOwnProperty.call(BLOCKED_REASONS, reason)) {
    return BLOCKED_REASONS[reason];
  }
  return { label: reason || '未知原因', guidance: '需人工排查' };
}

/**
 * 原因行的完整展示文案：人类可读 label 带上原码括注（取证口径不丢）；
 * 未知 reason 原样回显（此时 label 即原码，不重复括注）。
 */
export function blockedReasonDisplay(reason: string | null | undefined): string {
  const known =
    reason != null &&
    reason !== '' &&
    Object.prototype.hasOwnProperty.call(BLOCKED_REASONS, reason);
  if (!reason) {
    return '未知原因';
  }
  return known ? `${BLOCKED_REASONS[reason].label}（${reason}）` : reason;
}
