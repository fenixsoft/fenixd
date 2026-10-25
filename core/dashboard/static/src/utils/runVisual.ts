// runVisual.ts — run 可视化共享常量与纯函数（add-spec-topology-bigscreen 3.1）。
//
// 自 SpecTimeline.tsx **等价纯迁移**：状态语义色五分支（runDotColor）、终态
// 原因语气（reasonTone）、Agent 中文名与 run_id 前缀映射（AGENT_LABEL /
// RUN_ID_PREFIX_LABEL / agentLabel）、金额格式化（formatUsd）。迁移后
// SpecTimeline.tsx 渲染输出严格等价（tests/runVisual.test.mjs 纯函数单测
// 背书，specs/topology-bigscreen-ui「SpecTimeline 等价迁移」Scenario）；
// SPEC 协作拓扑大屏（PipelineView/SwimlaneView）消费同一常量单源，两处
// 着色/角色口径永不漂移。
//
// 零 import：node 测试环境（node:test 直载，先例 embedMount.test.mjs）无
// 构建链，本模块保持纯函数 + 常量、不引任何依赖。

// Agent 中文名（与设置页 Agent 模型角色中文名对应；implementer 沿用「开发」）。
// agent_type 为泛型 'agent' 或缺失时，按 run_id 前缀（RUN_ID_PREFIX_LABEL）判别。
export const AGENT_LABEL: Record<string, string> = {
  implementer: '开发 Agent',
  'impl-ocr': '代码审查 Agent',
  planner: '规划 Agent',
  'planner-plan': '生成场景 Agent',
  'planner-judge': '判定结果 Agent',
  'spec-review': '需求评审 Agent',
  'dispute-judge': '争议裁决 Agent',
  repair: '修复 Agent',
  verifier: '验证 Agent',
  tester: '测试 Agent',
  administrator: '运维 Agent',
};

// run_id 前缀兜底。⚠️ 必须按完整前缀匹配（不能用 split('-')[0]）：spec-review- /
// dispute-judge- / planner-plan- 等是多段前缀，首段 'spec'/'dispute'/'planner'
// 无法唯一归属；长的排前面，首个命中即止（impl-ocr- 必须排在 impl- 之前，
// 否则被 impl- 先命中、车道节点标签退回「开发 Agent」）。
export const RUN_ID_PREFIX_LABEL: [prefix: string, label: string][] = [
  ['planner-judge-', '判定结果 Agent'],
  ['planner-plan-', '生成场景 Agent'],
  ['dispute-judge-', '争议裁决 Agent'],
  ['spec-review-', '需求评审 Agent'],
  ['impl-ocr-', '代码审查 Agent'],
  ['impl-', '开发 Agent'],
  ['repair-', '修复 Agent'],
  ['admin-', '运维 Agent'],
  ['test-', '测试 Agent'],
  ['verify-', '验证 Agent'],
];

export function agentLabel(item: { agent_type?: string; run_id?: string }): string {
  const t = (item.agent_type || '').toLowerCase();
  // 泛型 'agent' 视同缺失（后端未识别出类型），继续走 run_id 前缀判别
  if (t && t !== 'agent' && AGENT_LABEL[t]) return AGENT_LABEL[t];
  const rid = (item.run_id || '').toLowerCase();
  for (const [prefix, label] of RUN_ID_PREFIX_LABEL) {
    if (rid.startsWith(prefix)) return label;
  }
  return AGENT_LABEL[t] || '未知 Agent';
}

/** run 终态原因行的呈现（add-timeline-gate-failure-display D5）：语气 + 前缀。
 *
 * 门禁拒绝（gate-blocked）与 error 同为失败（danger 红，前缀区分「门禁拒绝：」与
 * 「失败原因：」——一眼分清「产物门拒绝」与「运行崩了」）；superseded 是被弃置的
 * 中间产物（secondary + 「原地重试：」，失败归因由紧随其后的 gate-blocked 节点承担）；
 * 其余中止类（interrupted/cancelled）橙色 warning。未知状态落 warning/中止原因，
 * 与抽取前行为一致。映射单一真源，渲染处 MUST NOT 再内联重复该条件链。 */
export function reasonTone(
  st: string,
): { tone: 'danger' | 'warning' | 'secondary'; prefix: string } {
  if (st === 'gate-blocked') return { tone: 'danger', prefix: '门禁拒绝：' };
  if (st === 'error') return { tone: 'danger', prefix: '失败原因：' };
  if (st === 'superseded') return { tone: 'secondary', prefix: '原地重试：' };
  return { tone: 'warning', prefix: '中止原因：' };
}

/** run 状态语义色五分支（时间轴圆点着色单源；以具名函数承载 SpecTimeline 内
 * 原 if/else 链——code-review item 7471b4865219「禁止嵌套三元」先例）：
 * error/gate-blocked 红、interrupted/cancelled 橙、stale 灰、running/empty 蓝、
 * 其余（done 等成功终态与未知状态）绿兜底。返回值域与 antd Timeline 圆点
 * 色名一致，时间轴渲染等价；大屏 SVG 经 STATUS_HEX 投影为十六进制。 */
export function runDotColor(status: string): string {
  const st = status || '';
  // 门禁拒绝（add-timeline-gate-failure-display D5）：产物硬门失败终止本次
  // attempt 的独立终态，语义等同 error（失败）——不并入失败分支会落入绿色
  // 兜底，重现「门禁连续拒绝显示成一串顺利收工绿点」的误导
  const isFailed = st === 'error' || st === 'gate-blocked';
  // interrupted/cancelled：已终结但非崩溃（daemon 停机/启动清扫补写/人工取消），
  // 橙色区别于 error 红
  const isAborted = st === 'interrupted' || st === 'cancelled';
  // stale（fix-retry-orphan-active-runs）：弃置/断尾——灰色区别于 running 蓝 /
  // error 红；未知 status 行为不变（绿兜底）
  if (isFailed) return 'red';
  if (isAborted) return 'orange';
  if (st === 'stale') return 'gray';
  if (st === 'running' || st === 'empty') return 'blue';
  return 'green';
}

// 语义色名 → 深色大屏 SVG 十六进制投影（runDotColor 值域的等价映射）：
// 红/橙/蓝/绿对齐 antd preset（时间轴 Tag 同色系），灰取深底可读的中性灰
// （antd Timeline 'gray' 预设在暗底过亮刺眼，语义同为「弃置/中性」）。
export const STATUS_HEX: Record<string, string> = {
  red: '#ff4d4f',
  orange: '#fa8c16',
  gray: '#8c8c8c',
  blue: '#1677ff',
  green: '#52c41a',
};

// add-model-billing-cost-display（design D5）：金额格式化——统一 $x.xx；
// < $0.01 显示三位小数（$0.001），避免小额全零。仅展示口径，不做入账四舍五入。
// （自 SpecTimeline.tsx 等价迁入；SpecTimeline 以 re-export 保持 detail.tsx
// 既有 import 路径零改动）
export function formatUsd(v: number): string {
  if (v > 0 && v < 0.01) return `$${v.toFixed(3)}`;
  return `$${v.toFixed(2)}`;
}
