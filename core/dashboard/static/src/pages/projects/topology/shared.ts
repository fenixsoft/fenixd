// shared.ts — SPEC 协作拓扑大屏共享常量与纯函数（add-spec-topology-bigscreen 4.x）。
//
// design D2：角色前缀映射以 core/agent_runner/run_files.py RUN_ID_AGENT_PREFIXES
// 为权威源（后端 topology.py 归列单点），本模块常量**仅服务前端渲染**（列头/
// 泳道标签中文与状态着色投影），跨语言不强行单源。状态语义色与角色标签经
// @/utils/runVisual 单源消费（与 SpecTimeline 同源，等价迁移背书）。

import { formatUsd, runDotColor, STATUS_HEX } from '@/utils/runVisual';
import type { TopologyLane, TopologyStage } from '@/services/dashboard';

// 语义色名 → 十六进制投影消费方需同时判定分支（失败红/中止橙/弃置灰），
// 与 STATUS_HEX 一并经本模块再导出，视图层不重复 import 两个来源。
export { runDotColor, STATUS_HEX };

// 七阶段列（管线视图列序；中文与后端 STAGE_LABELS 同文案）
export const STAGE_ORDER: TopologyStage[] = [
  'demand',
  'plan',
  'dev',
  'review',
  'test',
  'ops',
  'delivery',
];

export const STAGE_LABELS: Record<TopologyStage, string> = {
  demand: '需求',
  plan: '规划',
  dev: '开发',
  review: '审查/修复',
  test: '测试/验证',
  ops: '运维',
  delivery: '交付',
};

// 八泳道（协作时序视图行序；交付终点不单设泳道——以 PMEngine 泳道 pushed
// 刻度收尾呈现，specs/topology-bigscreen-ui 泳道 Requirement）
export const LANE_ORDER: TopologyLane[] = [
  'user',
  'pm',
  'demand',
  'plan',
  'dev',
  'review',
  'test',
  'ops',
];

export const LANE_LABELS: Record<TopologyLane, string> = {
  user: '用户',
  pm: 'PMEngine',
  demand: '需求评审',
  plan: '规划',
  dev: '开发',
  review: '审查/修复',
  test: '测试/验证',
  ops: '运维',
};

/** 状态语义色 → 深色大屏 SVG 十六进制（runDotColor 五分支单源投影）。 */
export function runDotHex(status: string): string {
  return STATUS_HEX[runDotColor(status)] ?? STATUS_HEX.green;
}

/** 大屏成本展示：null（全不可计价）显式「不可计价」，不渲染 $0.00 伪装可计价。
 * 金额口径（两位/三位小数、非有限值守卫）单源复用 runVisual.formatUsd，
 * 不再内联 toFixed 分支（code-review item cff901c50e19：两份实现已守卫漂移）。 */
export function fmtCost(v: number | null | undefined): string {
  if (v == null) return '不可计价';
  return formatUsd(v);
}

/** ISO 时刻 → epoch ms；无效/缺失返回 null（泳道时间轴跳过无时刻节点）。 */
export function parseTsMs(s: string | undefined | null): number | null {
  if (!s) return null;
  const t = Date.parse(s);
  return Number.isFinite(t) ? t : null;
}

/** 长文本中段截断（run_id/摘要展示；保留头尾锚点可辨识）。 */
export function midTrunc(s: string, max = 28): string {
  if (s.length <= max) return s;
  const head = Math.ceil((max - 1) / 2);
  const tail = Math.floor((max - 1) / 2);
  return `${s.slice(0, head)}…${s.slice(-tail)}`;
}

// ── 时间刻度（协作时序/管线视图共用；improve-spec-topology-pipeline-view 3.1
//    自 SwimlaneView 迁入本模块单源，两视图复用同档位与文案格式） ─────────────

// 时间刻度自适应档位（秒）：目标 ~8 条刻度，就近取整到分钟/小时档
export const TICK_STEPS_S = [
  60, 2 * 60, 5 * 60, 10 * 60, 15 * 60, 30 * 60, 3600, 2 * 3600, 6 * 3600, 12 * 3600, 24 * 3600,
];

export function pickTickStep(spanS: number): number {
  for (const s of TICK_STEPS_S) {
    if (spanS / s <= 10) return s;
  }
  return TICK_STEPS_S[TICK_STEPS_S.length - 1];
}

export function fmtTick(ms: number, spanS: number): string {
  const d = new Date(ms);
  const hh = `${String(d.getHours()).padStart(2, '0')}`;
  const mm = `${String(d.getMinutes()).padStart(2, '0')}`;
  if (spanS <= 2 * 3600) return `${hh}:${mm}`;
  const day = `${String(d.getMonth() + 1).padStart(2, '0')}/${String(d.getDate()).padStart(2, '0')}`;
  return spanS <= 48 * 3600 ? `${day} ${hh}:${mm}` : day;
}
