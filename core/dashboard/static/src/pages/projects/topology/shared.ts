// shared.ts — SPEC 协作拓扑大屏共享常量与纯函数（add-spec-topology-bigscreen 4.x）。
//
// design D2：角色前缀映射以 core/agent_runner/run_files.py RUN_ID_AGENT_PREFIXES
// 为权威源（后端 topology.py 归列单点），本模块常量**仅服务前端渲染**（列头/
// 泳道标签中文与状态着色投影），跨语言不强行单源。状态语义色与角色标签经
// @/utils/runVisual 单源消费（与 SpecTimeline 同源，等价迁移背书）。

import { runDotColor, STATUS_HEX } from '@/utils/runVisual';
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

/** 大屏成本展示：null（全不可计价）显式「不可计价」，不渲染 $0.00 伪装可计价。 */
export function fmtCost(v: number | null | undefined): string {
  if (v == null) return '不可计价';
  if (v > 0 && v < 0.01) return `$${v.toFixed(3)}`;
  return `$${v.toFixed(2)}`;
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
