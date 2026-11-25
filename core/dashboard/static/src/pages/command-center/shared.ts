// shared.ts — 指挥中心四屏共享纯助手（add-command-center 4.x）。
// 文案经 useIntl/intlText（i18n 修复轮 batch-C：本文件静态中文文案迁 i18n 目录）。
//
// node --test 原生 type-stripping 直载（tests/commandCenter.test.mjs）：
// 仅可擦除 TS 语法（类型注解/type-only import），禁 enum/namespace/运行时
// 装饰器；不 import react/antd（保持纯函数，单测不拉组件依赖图）。文案映射
// 走 intlText 访问期取值（batch-A shim：Umi 运行时真 intl / esbuild 走
// @umijs/max 桩 / raw node 直载回落 zh 目录原文，见 utils/intlText.ts 头注），
// 零 react/antd 依赖红线不破；映射表 getter 化，禁模块顶层求值。

// 页面配色（2026-11-04 用户指令「指挥中心黑改白 + 脱壳改内容区嵌入」改版）：
// 原 IOC 深蓝黑四色单源整体退役，单源改挂 theme.ts dsh 对齐常量表（DESIGN.md
// 配色红线同纪律——不另起色板；本模块只补弱底/描边等同族派生 alpha 档）。
// theme.ts 纯常量文件，零 react/antd 依赖红线不破；.ts 扩展导入走
// allowImportingTsExtensions 既有先例（mermaidInit.ts / embedMount.ts），
// node type-stripping 直载兼容。
// dashboard-dark-theme 4.2：本页色板消费改引 global.less 主题 CSS 变量（值源
// theme.ts 档位镜像：浅档与原常量逐字节一致、深档=D2 映射；var() 形态使切档
// 零 React 参与即时生效，徽标色 span style 直落 CSS 无 FastColor 解析风险）。
// theme.ts 仍为本页配色单源声明面（type-only 引用保持模块依赖关系可审计，
// 「配色单源挂 theme.ts」守卫随迁钉住）。
import type { ThemeScheme } from '../../theme.ts';
// embed 档判定单点（零依赖纯 TS，node 直载兼容——SCREEN_CHROME_OFFSET 双档）
import { isEmbedMode } from '../../utils/embedMount.ts';
import { intlText } from '../../utils/intlText.ts';

// 屏底/卡底：白底页面上数据卡=白底+细描边（同 overview 统计卡行豁免习语，
// 0.10 档描边承担卡感；包裹卡去边框规则不涉及本页——本页卡片均为数据卡）。
// 2026-11-06 用户指令：卡片框改 Bento 形态（CARD_FRAME_*），本值降级为非框
// 用途——sparkline 空点填充（OrgGrid）、流水线列头分隔线（PipelineBoard）。
export const BG = 'var(--fenix-bg-elevated)';
export const PANEL_BORDER = 'var(--fenix-border-secondary)';
export const TEXT_MAIN = 'var(--fenix-text)';
export const TEXT_SUB = 'var(--fenix-text-secondary)';

// ── Bento 磁贴边框（2026-11-06 用户指令「三个页签的卡片框都改为 bento 样式」；
// 值取自当日的 v2 域 token 表——该域 2026-11-07 已退役，独立存量）；圆角
// 固定 12px 见 DESIGN.md 通用条款（本页白底磁贴，不适用 settings 灰底准例）。
export const CARD_FRAME_BORDER = 'var(--fenix-hairline)';
export const CARD_FRAME_SHADOW =
  '0 1px 3px var(--fenix-tile-shadow-a), 0 1px 2px var(--fenix-tile-shadow-b)';

// null 指标占位：分母零/不可计价/数据缺口一律「—」（MUST NOT 显示 0——0 与
// 「口径不可得」语义不同，specs「验收与红线」节）；数值原样字符串化（0 保留）。
// 非有限值（NaN/Infinity）同归「—」占位，不透出 "NaN" 类文案（同 sparklineHeights 防护）。
export function fmtMetric(v: number | null | undefined): string {
  if (v === null || v === undefined || !Number.isFinite(v)) return '—';
  return String(v);
}

// 比率格式化：null/undefined/非有限 → 「—」；数值 → 百分比（1 位小数，0 → 0.0%）。
export function fmtRate(v: number | null | undefined): string {
  if (v === null || v === undefined || !Number.isFinite(v)) return '—';
  return `${(v * 100).toFixed(1)}%`;
}

// 成本格式化：null/undefined/非有限 → 「—」；数值 → $ 千分位两位小数。
export function fmtUsd(v: number | null | undefined): string {
  if (v === null || v === undefined || !Number.isFinite(v)) return '—';
  return `$${v.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

// tokens 格式化：null/undefined/非有限 → 「—」；数值千分位。
export function fmtTokens(v: number | null | undefined): string {
  if (v === null || v === undefined || !Number.isFinite(v)) return '—';
  return v.toLocaleString('en-US');
}

// 耗时格式化：秒 → 紧凑可读时长（<1m 取整秒；<1h 分秒；否则时分）；null/非有限 → 「—」。
export function fmtDurationSeconds(v: number | null | undefined): string {
  if (v === null || v === undefined || !Number.isFinite(v)) return '—';
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

// 徽标取色（dashboard-dark-theme 4.2）：语义色经主题 CSS 变量按档取值
// （浅档=theme.ts 常量值、深档=D2 映射；消费点均为 span style，CSS 直落）。
const BADGE_SUCCESS = 'var(--fenix-success)';
const BADGE_ERROR = 'var(--fenix-error)';
const BADGE_WARNING = 'var(--fenix-warning)';
const BADGE_LINK = 'var(--fenix-link)';
const BADGE_TERTIARY = 'var(--fenix-text-tertiary)';

// 车道状态 → 徽标（working 绿「运行中」/ idle 灰「空闲」；纯静态色，无动画）。
export function laneBadge(status: string): { text: string; color: string } {
  return status === 'working'
    ? { text: intlText('commandCenter.shared.laneWorking'), color: BADGE_SUCCESS }
    : { text: intlText('commandCenter.shared.laneIdle'), color: BADGE_TERTIARY };
}

// 台账 run 结果 → 徽标（classify_run 口径中文标签；未知值原样透出防丢信息）。
export function outcomeBadge(outcome: string | null | undefined): { text: string; color: string } {
  switch (outcome) {
    case 'done':
      return { text: intlText('commandCenter.shared.outcome.done'), color: BADGE_SUCCESS };
    case 'error':
      return { text: intlText('commandCenter.shared.outcome.error'), color: BADGE_ERROR };
    case 'running':
      return { text: intlText('commandCenter.shared.outcome.running'), color: BADGE_LINK };
    case 'interrupted':
      return { text: intlText('commandCenter.shared.outcome.interrupted'), color: BADGE_WARNING };
    case 'cancelled':
      return { text: intlText('commandCenter.shared.outcome.cancelled'), color: BADGE_WARNING };
    case 'superseded':
      return { text: intlText('commandCenter.shared.outcome.superseded'), color: BADGE_TERTIARY };
    case 'frozen-terminated':
      return {
        text: intlText('commandCenter.shared.outcome.frozenTerminated'),
        color: BADGE_TERTIARY,
      };
    case 'gate-blocked':
      return { text: intlText('commandCenter.shared.outcome.gateBlocked'), color: BADGE_WARNING };
    case 'stale':
      return { text: intlText('commandCenter.shared.outcome.stale'), color: BADGE_TERTIARY };
    case 'empty':
      return { text: intlText('commandCenter.shared.outcome.empty'), color: BADGE_TERTIARY };
    default:
      return { text: outcome || '—', color: BADGE_TERTIARY };
  }
}

// 严重度 → 徽标（收件箱卡；未知值原样透出）。
export function severityBadge(sev: string | null | undefined): { text: string; color: string } {
  switch (sev) {
    case 'critical':
      return { text: intlText('commandCenter.shared.severity.critical'), color: BADGE_ERROR };
    case 'major':
      return { text: intlText('commandCenter.shared.severity.major'), color: BADGE_WARNING };
    case 'minor':
      return { text: intlText('commandCenter.shared.severity.minor'), color: BADGE_LINK };
    default:
      return { text: sev || intlText('commandCenter.shared.severity.unknown'), color: BADGE_TERTIARY };
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
// 列名口径与 services.status.* 展示标签不同源（drafted=需求评审/ready=待实现
// 列语义 ≠ status.drafted=草稿/status.ready=就绪），独立 commandCenter.pipeline.
// column.* 键，batch-C 迁移时已核对避免同义双键混挂。
export const PIPELINE_COLUMN_LABELS: Record<string, string> = {
  get drafted() {
    return intlText('commandCenter.pipeline.column.drafted');
  },
  get ready() {
    return intlText('commandCenter.pipeline.column.ready');
  },
  get implementing() {
    return intlText('commandCenter.pipeline.column.implementing');
  },
  get verifying() {
    return intlText('commandCenter.pipeline.column.verifying');
  },
  get pushed() {
    return intlText('commandCenter.pipeline.column.pushed');
  },
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
  get planner() {
    return intlText('commandCenter.shared.lane.planner');
  },
  get 'spec-review'() {
    return intlText('commandCenter.shared.lane.specReview');
  },
  get 'planner-plan'() {
    return intlText('commandCenter.shared.lane.plannerPlan');
  },
  get 'planner-judge'() {
    return intlText('commandCenter.shared.lane.plannerJudge');
  },
  get implementer() {
    return intlText('commandCenter.shared.lane.implementer');
  },
  get 'code-fix'() {
    return intlText('commandCenter.shared.lane.codeFix');
  },
  get verifier() {
    return intlText('commandCenter.shared.lane.verifier');
  },
  get judge() {
    return intlText('commandCenter.shared.lane.judge');
  },
  get 'code-review'() {
    return intlText('commandCenter.shared.lane.codeReview');
  },
  get 'self-review'() {
    return intlText('commandCenter.shared.lane.selfReview');
  },
  get administrator() {
    return intlText('commandCenter.shared.lane.administrator');
  },
  get evolution() {
    return intlText('commandCenter.shared.lane.evolution');
  },
  // add-distill-run-artifacts 3.2：蒸馏车道收编运营线（后端 ROSTER 同步追加）
  get 'knowledge-distiller'() {
    return intlText('commandCenter.shared.lane.knowledgeDistiller');
  },
  get ocr() {
    return intlText('commandCenter.shared.lane.ocr');
  },
};

export function laneLabel(lane: string): string {
  return LANE_LABELS[lane] ?? lane;
}

// ── Agent 卡派生色/字体（2026-10-28 LaneCard 重设计定稿；2026-11-04 随页改
// 版整体换白底族）───────────────────────────────────────────────
// theme.ts 单源的弱底/描边同族派生档，集中管理（组件内不散落硬编码色值）。
// 注意：图标组件映射因 antd import 红线不放本文件（见 OrgGrid.tsx LANE_ICONS）。
export const FONT_MONO = "ui-monospace, 'SF Mono', Menlo, Consolas, monospace";
export const CARD_BG = 'var(--fenix-bg-elevated)';
export const ACCENT = 'var(--fenix-link)';
export const GREEN = 'var(--fenix-success)';
export const GREEN_DIM_BG = 'rgba(34, 197, 94, 0.10)';
// 活动行 spec 条目 hover 提亮（2026-10-29 多 spec 列表可点击行；同族绿弱底）
export const GREEN_DIM_BG_HOVER = 'rgba(34, 197, 94, 0.18)';
// 图标徽章恒彩（2026-10-28 用户定稿：不随 working/idle 变灰，统一蓝系）
export const AVATAR_BG =
  'linear-gradient(135deg, rgba(65, 118, 230, 0.12), rgba(65, 118, 230, 0.04))';
export const AVATAR_BORDER = 'rgba(65, 118, 230, 0.25)';
export const REST_BORDER = 'var(--fenix-border)';
export const METRIC_DIVIDER = 'var(--fenix-split)';
// 连接线描边（2026-11-04 用户指令）：灰色、比卡片描边（PANEL_BORDER=
// DSH_BORDER_SECONDARY 黑 0.10 alpha）深一档，白底上细线可读不抢主体
// （原深底蓝系定值随暗色域退役）
export const LINK_STROKE = 'var(--fenix-link-stroke)';

// Agent 卡最小宽度（2026-11-04 用户指令二改：卡宽随外部容器自适应——组织
// 图行左右各留 32px padding，剩余宽度按分区列均分给卡片，列宽下限 270px
// 无上限；CSS minmax(270px,1fr) 实现，禁脚本算宽）。单源常量+守卫测试
// （commandCenter.test.mjs），改值须同步复核团队卡 minWidth 560 与活动行/
// 页脚排布不溢出。
export const LANE_CARD_MIN_WIDTH = 270;

// 组织总览/交付流水线定高滚动容器的视口扣减值（unified-page-title-bar 页头
// 全站退役后重算，1920×1080 playwright 实拍校准）：
// standalone = ProLayout 顶栏 56 + 页面 padding-top 8 + 页签条 62 = 126
// （原 182 含 PageContainer 页头 56，随页头摘除扣减；旧值见 git 历史）；
// embed（dsh 面板桥 headerRender:false 无顶栏）= 统一标题栏行壳位 60 + 8 + 62
// = 130（2026-11-05 用户定调行壳位 embed 档 48→60，旧值 118 见 git 历史）。
// 壳层结构（顶栏/行壳位高/padding/页签条）任一变化须复核本值并重新实拍。
export const SCREEN_CHROME_OFFSET = isEmbedMode() ? 130 : 126;

// 时间窗（2026-10-28 时间下拉「今日/7 日/全量」）：窗口约束车道卡三格
// （run/成功率/成本）与产品团队汇总的运行/成本口径；需求数量（活跃 SPEC）
// 与 14 日 sparkline 不随窗变。与后端 ORG_WINDOWS 值域一致。
export type TimeWindow = 'today' | '7d' | 'all';

export const TIME_WINDOW_OPTIONS: { label: string; value: TimeWindow }[] = [
  {
    get label() {
      return intlText('commandCenter.shared.window.today');
    },
    value: 'today',
  },
  {
    get label() {
      return intlText('commandCenter.shared.window.7d');
    },
    value: '7d',
  },
  {
    get label() {
      return intlText('commandCenter.shared.window.all');
    },
    value: 'all',
  },
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
        run: intlText('commandCenter.shared.window.today.run'),
        rate: intlText('commandCenter.shared.window.today.rate'),
        cost: intlText('commandCenter.shared.window.today.cost'),
        teamSpecs: intlText('commandCenter.shared.window.today.teamSpecs'),
        teamRuns: intlText('commandCenter.shared.window.today.teamRuns'),
        teamDuration: intlText('commandCenter.shared.window.today.teamDuration'),
        teamCost: intlText('commandCenter.shared.window.today.teamCost'),
      };
    case 'all':
      return {
        run: intlText('commandCenter.shared.window.all.run'),
        rate: intlText('commandCenter.shared.window.all.rate'),
        cost: intlText('commandCenter.shared.window.all.cost'),
        teamSpecs: intlText('commandCenter.shared.window.all.teamSpecs'),
        teamRuns: intlText('commandCenter.shared.window.all.teamRuns'),
        teamDuration: intlText('commandCenter.shared.window.all.teamDuration'),
        teamCost: intlText('commandCenter.shared.window.all.teamCost'),
      };
    default:
      return {
        run: intlText('commandCenter.shared.window.7d.run'),
        rate: intlText('commandCenter.shared.window.7d.rate'),
        cost: intlText('commandCenter.shared.window.7d.cost'),
        teamSpecs: intlText('commandCenter.shared.window.7d.teamSpecs'),
        teamRuns: intlText('commandCenter.shared.window.7d.teamRuns'),
        teamDuration: intlText('commandCenter.shared.window.7d.teamDuration'),
        teamCost: intlText('commandCenter.shared.window.7d.teamCost'),
      };
  }
}
// 活动行状态三分（2026-10-28 设计 §3.2；2026-10-29 多 spec 并行滚动显示改
// 列表口径）：working+在飞归属 → specs 列表（点击 spec 名开运行记录弹窗）；
// working 无归属 → 「执行中」；idle（含未知状态，与 laneBadge 非 working
// 即 idle 口径同源）→ 待命。脏元素（缺 project/spec）防御性剔除——后端已
// 过滤，此处兜底 UI 不出死行。run_id 可空（add-command-center-verify-stats
// 1.3：在飞验证归属无 run 文件，空 run_id 条目保留、渲染端既有 legacy 空
// 路径显名不可点）；run 侧条目恒带值。纯函数零依赖，node --test 直测。
export interface AttributableRun {
  project: string;
  spec: string;
  run_id?: string;
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
    // 空 run_id 条目保留（在飞验证归属，add-command-center-verify-stats
    // 1.3）；渲染端按 run_id 缺失禁点，不弹运行记录
    // Array.isArray 守卫（同 isSpecInList/laneSpecRounds 口径）：非数组真值
    // 漂移按空处理，不抛 TypeError
    const items = (Array.isArray(card.attributables) ? card.attributables : []).filter(
      (a) => !!a && !!a.project && !!a.spec,
    );
    if (items.length) {
      return { kind: 'specs', items };
    }
    const legacy = card.attributable;
    // project 判空与主路径过滤口径对齐，脏数据不落 LaneCard 的 `undefined/spec`
    if (legacy && legacy.project && legacy.spec) {
      return {
        kind: 'specs',
        items: [{ project: legacy.project, spec: legacy.spec, run_id: '' }],
      };
    }
    return { kind: 'running' };
  }
  return { kind: 'rest' };
}

// ── spec 视图纯助手（add-command-center-spec-view 3.2）──────────────────
// 纯函数与派生色常量：零 react/antd import 红线不变，node --test 直测。

// 需求数量格可点击态派生色（ACCENT 同族弱底：hover 纯色提亮 + 选中态底色，
// 与车道卡 hover 口径同族——纯色切换无动画）
export const SPEC_CELL_HOVER_BG = 'rgba(65, 118, 230, 0.08)';
export const SPEC_CELL_SELECTED_BG = 'rgba(65, 118, 230, 0.14)';

// org summary.specs 条目（{project, spec}；created 排序由后端下发）
export interface SpecEntry {
  project: string;
  spec: string;
}

// spec 视图轮次行（seq 全史编号/inflight 在飞判定均由后端下发，前端零推导）
export interface SpecRound {
  seq: number;
  run_id: string;
  started_ts: string | null;
  inflight: boolean;
}

// spec-runs 车道（花名册全量出列：零 run 车道 rounds 为空数组）
export interface SpecRunsLane {
  lane: string;
  zone: string;
  rounds: SpecRound[];
}

// 轮次行 label 组装：`spec名 · 第N轮`（N=后端下发的全史 seq，前端零推导）
export function specRoundLabel(spec: string, seq: number): string {
  return intlText('commandCenter.shared.specRoundLabel', { spec, seq });
}

// 下拉条目显示：全部项目视图 `project/spec` 消歧（跨项目同名），单项目
// 视图只显 spec 名
export function specEntryLabel(entry: SpecEntry, allProjects: boolean): string {
  return allProjects ? `${entry.project}/${entry.spec}` : entry.spec;
}

// 选中态与 summary.specs 匹配判定：缺键兜底视为空名单（旧后端/新前端混跑
// 不异常）；project/spec 空值恒 false（深链脏参数防御）
export function isSpecInList(
  list: SpecEntry[] | null | undefined,
  project: string,
  spec: string,
): boolean {
  if (!project || !spec) return false;
  return (Array.isArray(list) ? list : []).some(
    (e) => !!e && e.project === project && e.spec === spec,
  );
}

// 下拉搜索框本地过滤：`project/spec` 拼接串包含匹配（大小写不敏感）；
// 缺键兜底空数组，脏元素（缺 project/spec，与 isSpecInList 空值防御同口径）剔除
export function filterSpecEntries(
  list: SpecEntry[] | null | undefined,
  query: string,
): SpecEntry[] {
  const src = (Array.isArray(list) ? list : []).filter((e) => !!e && !!e.project && !!e.spec);
  const q = (query || '').trim().toLowerCase();
  if (!q) return src;
  return src.filter((e) => `${e.project}/${e.spec}`.toLowerCase().includes(q));
}

// 车道轮次提取：spec-runs lanes → 指定 lane 的 rounds（缺卡/缺键/脏形态
// 兜底空数组 → 渲染端按「未运行」口径显示，零伪造）
export function laneSpecRounds(
  lanes: SpecRunsLane[] | null | undefined,
  lane: string,
): SpecRound[] {
  const hit = (Array.isArray(lanes) ? lanes : []).find((l) => !!l && l.lane === lane);
  return hit && Array.isArray(hit.rounds) ? hit.rounds : [];
}
