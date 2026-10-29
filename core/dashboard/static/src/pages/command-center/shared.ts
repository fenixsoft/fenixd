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
  // [fenix-ignore:712fbb46dbbd] 现行实现已将取整提前到秒级判断之前（59.5~60 取整得 60 后进位输出 1m），所述秒级输出 60s 的问题不存在。
  // 先对总秒数取整再判进位：59.5~60 区间 round 后得 60，若按秒级输出即「60s」
  // 不向分钟进位（v=60 才是「1m」）；分秒拆分同理会让余秒进成 60 出「59m60s」。
  // 取整提到分支前统一做，逐级判进位则边界自然收敛。
  const t = Math.round(v);
  if (t < 60) return `${t}s`;
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
// 已知不可逆选项 id 回退保底。该回退清单为唯一权威单源（code-review item
// 3a6a2d1bc5f7）：useAlertAdjudication.choiceNeedsConfirm import 此常量判定，
// 两侧不得再各自维护副本；本模块零 react/antd 依赖，node --test 直载不受
// 影响，收件箱屏独立判定不做选择状态耦合。
export const KNOWN_IRREVERSIBLE_CHOICE_IDS = ['abandon', 'skip_review_gate', 'delete_untracked_stray'];

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
// 2026-10-28 随五线重划补齐编制内新贵：planner-plan 场景生成 /
// planner-judge 场景验证 / verifier 验证 / evolution 自改进；self-review
// 按用户定稿口径改「自省」；judge 改「质量裁决」。testing（tester）与
// scan 已取消出卡（后端 ROSTER 同步移除），标签随删。
export const LANE_LABELS: Record<string, string> = {
  planner: '需求规划',
  'spec-review': '需求评审',
  'planner-plan': '场景生成',
  'planner-judge': '场景验证',
  implementer: '实现',
  'code-fix': '修复',
  verifier: '验证',
  judge: '质量裁决',
  'code-review': '代码评审',
  'self-review': '自省',
  administrator: '运维管理',
  evolution: '自改进',
  ocr: 'OCR 识别',
};

export function laneLabel(lane: string): string {
  return LANE_LABELS[lane] ?? lane;
}

// ── Agent 卡派生色/字体（2026-10-28 LaneCard 重设计定稿）──────────────────
// 与上方大屏四色单源同族的弱色变体，集中管理（组件内不散落硬编码色值）。
// 注意：图标组件映射因 antd import 红线不放本文件（见 OrgGrid.tsx LANE_ICONS）。
export const FONT_MONO = "ui-monospace, 'SF Mono', Menlo, Consolas, monospace";
export const CARD_BG = 'rgba(10, 30, 56, 0.55)';
export const CARD_BG_HOVER = 'rgba(16, 42, 78, 0.65)';
export const CARD_BORDER_BRIGHT = 'rgba(94, 150, 210, 0.7)';
export const ACCENT = '#40a9ff';
export const GREEN = '#52c41a';
export const GREEN_DIM_BG = 'rgba(82, 196, 26, 0.12)';
// 活动行 spec 条目 hover 提亮（2026-10-29 多 spec 列表可点击行；同族绿弱底）
export const GREEN_DIM_BG_HOVER = 'rgba(82, 196, 26, 0.2)';
// 图标徽章恒彩（2026-10-28 用户定稿：不随 working/idle 变灰，统一蓝系）
export const AVATAR_BG =
  'linear-gradient(135deg, rgba(64, 169, 255, 0.16), rgba(64, 169, 255, 0.05))';
export const AVATAR_BORDER = 'rgba(64, 169, 255, 0.25)';
export const REST_BORDER = 'rgba(91, 112, 140, 0.35)';
export const METRIC_DIVIDER = 'rgba(59, 110, 165, 0.25)';
// 连接线描边（2026-10-29 用户定稿加深：PANEL_BORDER 0.4 alpha 在纯黑底上
// 偏浅看不清，提亮提饱和与 hover 边框同族）
export const LINK_STROKE = 'rgba(94, 150, 210, 0.75)';

// 时间窗（2026-10-28 时间下拉「今日/7 日/全量」）：窗口约束车道卡三格
// （run/成功率/成本）与产品团队汇总的运行/成本口径；需求数量（活跃 SPEC）
// 与 14 日 sparkline 不随窗变。与后端 ORG_WINDOWS 值域一致。
export type TimeWindow = 'today' | '7d' | 'all';

export const TIME_WINDOW_OPTIONS: { label: string; value: TimeWindow }[] = [
  { label: '今日', value: 'today' },
  { label: '7 日', value: '7d' },
  { label: '全量', value: 'all' },
];

export function windowLabels(w: TimeWindow): {
  run: string;
  rate: string;
  cost: string;
  teamSpecs: string;
  teamRuns: string;
  teamDuration: string;
  teamCost: string;
} {
  switch (w) {
    case 'today':
      return {
        run: '今日实例数',
        rate: '今日成功率',
        cost: '今日成本',
        teamSpecs: '需求数量 · 今日',
        teamRuns: 'Agent 实例数 · 今日',
        teamDuration: '运行时长 · 今日',
        teamCost: '总成本 · 今日',
      };
    case 'all':
      return {
        run: '全量实例数',
        rate: '全量成功率',
        cost: '全量成本',
        teamSpecs: '需求数量 · 全量',
        teamRuns: 'Agent 实例数 · 全量',
        teamDuration: '运行时长 · 全量',
        teamCost: '总成本 · 全量',
      };
    default:
      return {
        run: '7 日实例数',
        rate: '7 日成功率',
        cost: '成本 · 7 日',
        teamSpecs: '需求数量 · 7 日',
        teamRuns: 'Agent 实例数 · 7 日',
        teamDuration: '运行时长 · 7 日',
        teamCost: '总成本 · 7 日',
      };
  }
}
// 活动行状态三分（2026-10-28 设计 §3.2；2026-10-29 多 spec 并行滚动显示改
// 列表口径）：working+在飞归属 → specs 列表（点击 spec 名开运行记录弹窗）；
// working 无归属 → 「执行中」；idle（含未知状态，与 laneBadge 非 working
// 即 idle 口径同源）→ 待命。脏元素（缺 spec/run_id）防御性剔除——后端已
// 过滤，此处兜底 UI 不出死行。纯函数零依赖，node --test 直测。
export interface AttributableRun {
  project: string;
  spec: string;
  run_id: string;
}

export type ActivityLineState =
  | { kind: 'specs'; items: AttributableRun[] }
  | { kind: 'running' }
  | { kind: 'rest' };

export function activityLineState(card: {
  status: string;
  // 可选 + undefined 均容忍（旧后端缺键；读侧逐层兜底，同 dashboard.ts）
  attributables?: AttributableRun[] | null;
  // 旧字段兜底（2026-10-29）：后端进程未重启时 attributables 缺键，回退旧
  // attributable 单条仅显名字（run_id 置空 → 渲染端不可点开运行记录）
  attributable?: { project: string; spec: string } | null;
}): ActivityLineState {
  if (card.status === 'working') {
    const items = (card.attributables ?? []).filter((a) => !!a && !!a.spec && !!a.run_id);
    if (items.length) {
      return { kind: 'specs', items };
    }
    const legacy = card.attributable;
    if (legacy && legacy.spec) {
      return {
        kind: 'specs',
        items: [{ project: legacy.project, spec: legacy.spec, run_id: '' }],
      };
    }
    return { kind: 'running' };
  }
  return { kind: 'rest' };
}
