// shared.ts — 指挥中心四屏共享纯助手（add-command-center 4.x）。
//
// node --test 原生 type-stripping 直载（tests/commandCenter.test.mjs）：
// 仅可擦除 TS 语法（类型注解/type-only import），禁 enum/namespace/运行时
// 装饰器；不 import react/antd（保持纯函数零依赖，单测不拉组件依赖图）。

// 深色大屏配色（IOC 风格，与协作图谱/拓扑大屏同一色系）
export const BG = '#0a1628';
export const PANEL_BORDER = 'rgba(59, 110, 165, 0.4)';
export const TEXT_MAIN = '#d6e7f7';
export const TEXT_SUB = '#7f9cba';

// null 指标占位：分母零/不可计价/数据缺口一律「—」（MUST NOT 显示 0——0 与
// 「口径不可得」语义不同，specs「验收与红线」节）；数值原样字符串化（0 保留）。
export function fmtMetric(v: number | null | undefined): string {
  if (v === null || v === undefined) return '—';
  return String(v);
}

// 比率格式化：null/undefined → 「—」；数值 → 百分比（1 位小数，0 → 0.0%）。
export function fmtRate(v: number | null | undefined): string {
  if (v === null || v === undefined) return '—';
  return `${(v * 100).toFixed(1)}%`;
}

// 成本格式化：null/undefined → 「—」；数值 → $ 千分位两位小数。
export function fmtUsd(v: number | null | undefined): string {
  if (v === null || v === undefined) return '—';
  return `$${v.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

// tokens 格式化：null/undefined → 「—」；数值千分位。
export function fmtTokens(v: number | null | undefined): string {
  if (v === null || v === undefined) return '—';
  return v.toLocaleString('en-US');
}

// 耗时格式化：秒 → 紧凑可读时长（<1m 取整秒；<1h 分秒；否则时分）；null → 「—」。
export function fmtDurationSeconds(v: number | null | undefined): string {
  if (v === null || v === undefined) return '—';
  if (v < 60) return `${Math.round(v)}s`;
  // 先对总秒数取整再拆分：浮点秒下「floor 取分 + round 余秒」会让 59.5~60
  // 区间的余秒进成 60 且不向分钟进位（输出「59m60s」越界文案）。
  const t = Math.round(v);
  const m = Math.floor(t / 60);
  const s = t % 60;
  if (m < 60) return s ? `${m}m${s}s` : `${m}m`;
  const h = Math.floor(m / 60);
  const rm = m % 60;
  return rm ? `${h}h${rm}m` : `${h}h`;
}

// ISO 时间 → 本地短格式（MM-DD HH:mm）；null/undefined → 「—」；解析失败
// 原样回退（脏形态不抛错挂屏）。
export function fmtShortTs(ts: string | null | undefined): string {
  if (!ts) return '—';
  const d = new Date(ts);
  if (Number.isNaN(d.getTime())) return ts;
  const p = (n: number) => String(n).padStart(2, '0');
  return `${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`;
}

// 车道状态 → 徽标（working 绿「运行中」/ idle 灰「空闲」；纯静态色，无动画）。
export function laneBadge(status: string): { text: string; color: string } {
  return status === 'working'
    ? { text: '运行中', color: '#52c41a' }
    : { text: '空闲', color: '#5b708c' };
}

// 台账 run 结果 → 徽标（classify_run 口径中文标签；未知值原样透出防丢信息）。
export function outcomeBadge(outcome: string | null | undefined): { text: string; color: string } {
  switch (outcome) {
    case 'done':
      return { text: '成功', color: '#52c41a' };
    case 'error':
      return { text: '失败', color: '#ff4d4f' };
    case 'running':
      return { text: '运行中', color: '#40a9ff' };
    case 'interrupted':
      return { text: '已中断', color: '#fa8c16' };
    case 'cancelled':
      return { text: '已取消', color: '#fa8c16' };
    case 'superseded':
      return { text: '已取代', color: '#7f9cba' };
    case 'frozen-terminated':
      return { text: '冻结终止', color: '#7f9cba' };
    case 'gate-blocked':
      return { text: '门禁拦截', color: '#fa8c16' };
    case 'stale':
      return { text: '失联', color: '#7f9cba' };
    case 'empty':
      return { text: '空产物', color: '#7f9cba' };
    default:
      return { text: outcome || '—', color: '#7f9cba' };
  }
}

// 严重度 → 徽标（收件箱卡；未知值原样透出）。
export function severityBadge(sev: string | null | undefined): { text: string; color: string } {
  switch (sev) {
    case 'critical':
      return { text: '严重', color: '#ff4d4f' };
    case 'major':
      return { text: '重要', color: '#fa8c16' };
    case 'minor':
      return { text: '次要', color: '#40a9ff' };
    default:
      return { text: sev || '未知', color: '#7f9cba' };
  }
}

// 14 日柱点 sparkline 分桶：计数值 → 相对高度百分比（最大值归一到 0-100；
// 全零 → 全零高度；负数/非有限输入按 0 计）。返回长度与输入一致的数组，
// 渲染端逐条画静态矩形（无动画属性）。
export function sparklineHeights(activity: number[]): number[] {
  const counts = activity.map((n) => (Number.isFinite(n) && n > 0 ? n : 0));
  const max = Math.max(0, ...counts);
  if (!max) return counts.map(() => 0);
  return counts.map((n) => Math.round((n / max) * 100));
}

// choices 选项破坏性判定：注册表 destructive 标志单源；历史快照缺字段时按
// 已知不可逆选项 id 回退保底（与 useAlertAdjudication.choiceNeedsConfirm
// 同一口径，收件箱屏独立判定不做选择状态耦合）。
const KNOWN_IRREVERSIBLE_CHOICE_IDS = ['abandon', 'skip_review_gate', 'delete_untracked_stray'];

export function isDestructiveChoice(
  choice: { id: string; destructive?: boolean } | null | undefined,
): boolean {
  if (!choice) return false;
  return (
    choice.destructive === true ||
    (choice.destructive === undefined && KNOWN_IRREVERSIBLE_CHOICE_IDS.includes(choice.id))
  );
}

// 交付流水线五列标签（列 key 与后端 PIPELINE_COLUMNS 一致；未知 key 原样透出）。
export const PIPELINE_COLUMN_LABELS: Record<string, string> = {
  drafted: '需求评审',
  ready: '待实现',
  implementing: '实现中',
  verifying: '验证中',
  pushed: '已推送',
};

export function columnLabel(key: string): string {
  return PIPELINE_COLUMN_LABELS[key] ?? key;
}

// 花名册泳道中文标签（组织网格卡主标题；花名册外/未知 lane 原样透出）。
export const LANE_LABELS: Record<string, string> = {
  planner: '需求规划',
  'spec-review': '需求评审',
  implementer: '实现',
  'code-fix': '修复',
  'code-review': '代码评审',
  judge: '裁决',
  testing: '测试',
  administrator: '运维管理',
  'self-review': '自审',
  scan: '扫描',
  ocr: 'OCR 识别',
};

export function laneLabel(lane: string): string {
  return LANE_LABELS[lane] ?? lane;
}
