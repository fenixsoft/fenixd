// runVisual.ts — run 可视化共享常量与纯函数（原 add-spec-topology-bigscreen
// 3.1，自 SpecTimeline.tsx **等价纯迁移**：状态语义色五分支（runDotColor）、
// 终态原因语气（reasonTone）、Agent 中文名与 run_id 前缀映射（AGENT_LABEL /
// RUN_ID_PREFIX_LABEL / agentLabel）、金额格式化（formatUsd）。迁移后
// SpecTimeline.tsx 渲染输出严格等价（tests/runVisual.test.mjs 纯函数单测
// 背书）；协作拓扑大屏已退役，SpecTimeline 为唯一消费方。
// 文案经 useIntl/intlText（i18n 修复轮 batch-C：本文件静态中文文案迁 i18n 目录）。
//
// batch-C 契约改造：原「零 import」约定解除——AGENT_LABEL / RUN_ID_PREFIX_LABEL /
// agentLabel 兜底 / arbiterOutcomeLabel / reasonTone 的中文文案改经 intlText
// 访问期取值（映射 getter 化 / 前缀表 label 位挂可枚举 getter），三语境行为
// （Umi 运行时真 intl / esbuild 走 @umijs/max 桩 / raw node 直载回落 zh 原文）
// 见 utils/intlText.ts 头注。导出形态不变：AGENT_LABEL 仍为 Record<string,string>
// 同键集映射、RUN_ID_PREFIX_LABEL 仍为 [prefix, label][] 元组数组，destructure
// / 索引读取与纯字符串元组同行为，runVisual.test.mjs 既有断言零改动兼容。
// 仍不引 react/antd（intlText 自身零 react/antd）。
import { intlText } from './intlText.ts';

// Agent 中文名（与设置页 Agent 模型角色中文名对应；implementer 沿用「开发」）。
// agent_type 为泛型 'agent' 或缺失时，按 run_id 前缀（RUN_ID_PREFIX_LABEL）判别。
export const AGENT_LABEL: Record<string, string> = {
  get implementer() {
    return intlText('utils.runVisual.agent.implementer');
  },
  get 'impl-ocr'() {
    return intlText('utils.runVisual.agent.implOcr');
  },
  get planner() {
    return intlText('utils.runVisual.agent.planner');
  },
  get 'planner-plan'() {
    return intlText('utils.runVisual.agent.plannerPlan');
  },
  get 'planner-judge'() {
    return intlText('utils.runVisual.agent.plannerJudge');
  },
  get 'spec-review'() {
    return intlText('utils.runVisual.agent.specReview');
  },
  get 'dispute-judge'() {
    return intlText('utils.runVisual.agent.disputeJudge');
  },
  // add-arbiter-quality-display：全局决策者车道（add-arbiter-lane）中文标签，
  // 消除时间轴「未知 Agent」
  get arbiter() {
    return intlText('utils.runVisual.agent.arbiter');
  },
  // 归档蒸馏车道（add-distill-run-artifacts 2.1 后端 run_files 前缀表已收录）
  // 中文标签，消除时间轴「未知 Agent」（2026-11-04 add-systemd-hosting 推送后
  // 两条蒸馏 run 实证）
  get 'knowledge-distiller'() {
    return intlText('utils.runVisual.agent.knowledgeDistiller');
  },
  get repair() {
    return intlText('utils.runVisual.agent.repair');
  },
  get verifier() {
    return intlText('utils.runVisual.agent.verifier');
  },
  get tester() {
    return intlText('utils.runVisual.agent.tester');
  },
  get administrator() {
    return intlText('utils.runVisual.agent.administrator');
  },
};

// run_id 前缀兜底。⚠️ 必须按完整前缀匹配（不能用 split('-')[0]）：spec-review- /
// dispute-judge- / planner-plan- 等是多段前缀，首段 'spec'/'dispute'/'planner'
// 无法唯一归属；长的排前面，首个命中即止（impl-ocr- 必须排在 impl- 之前，
// 否则被 impl- 先命中、车道节点标签退回「开发 Agent」）。
//
// batch-C：文案值改 msg id 引用（RUN_ID_PREFIX_MSGS），导出表 RUN_ID_PREFIX_LABEL
// 的 label 位经 Object.defineProperty 挂可枚举 getter（访问期 intlText 取文案），
// 前缀集合与顺序契约逐字节不变。
const RUN_ID_PREFIX_MSGS: [prefix: string, msgId: string][] = [
  ['planner-judge-', 'utils.runVisual.agent.plannerJudge'],
  ['planner-plan-', 'utils.runVisual.agent.plannerPlan'],
  // 裸 planner- 前缀兜底（后端唯一真源 run_files.py RUN_ID_AGENT_PREFIXES
  // ("planner-", "planner") 的前端镜像）：planner 车道 run 的 agent_type 泛型化
  // 为 'agent' 或缺失时（spec-review 前缀漂移先例），此前缺条目使
  // run_id=planner-<spec>-<ts> 全表落空、时间轴退「未知 Agent」。MUST 排在
  // planner-judge-/planner-plan- 之后（长的排前面，否则两车道被短前缀吞并）
  ['planner-', 'utils.runVisual.agent.planner'],
  ['dispute-judge-', 'utils.runVisual.agent.disputeJudge'],
  // add-arbiter-quality-display：arbiter- 前缀兜底（防 agent_type 泛型化
  // 退化——spec-review 前缀漂移事故先例）；与 admin-/dispute- 等前缀互不
  // 包含，顺序不敏感处插入
  ['arbiter-', 'utils.runVisual.agent.arbiter'],
  ['spec-review-', 'utils.runVisual.agent.specReview'],
  ['impl-ocr-', 'utils.runVisual.agent.implOcr'],
  ['impl-', 'utils.runVisual.agent.implementer'],
  ['repair-', 'utils.runVisual.agent.repair'],
  ['admin-', 'utils.runVisual.agent.administrator'],
  ['test-', 'utils.runVisual.agent.tester'],
  ['verify-', 'utils.runVisual.agent.verifier'],
  // 归档蒸馏车道前缀兜底（后端 run_files 表 add-distill-run-artifacts 2.1
  // 同名条目的前端镜像；与既有前缀无子串冲突，顺序不敏感处追加）
  ['knowledge-distiller-', 'utils.runVisual.agent.knowledgeDistiller'],
  // 以下五条对齐后端唯一真源 run_files.py RUN_ID_AGENT_PREFIXES（其注释
  // 口径「新增 run 前缀只改这里，别再复制一份」）此前缺的车道前缀，防
  // 「未知 Agent」退化回潮（本表 arbiter- / knowledge-distiller- 两次补条
  // 先例）。中文名取自既有代码命名（设置页 PromptsPanel AGENT_LABELS、
  // 「自进化」页签、maintenance_ledger 维护台账）；code-review- 与
  // impl-ocr-（实现期收尾审查）共用「代码审查」名。与既有前缀无子串冲突
  // （review- 与 spec-review- 在 startswith 语义下互不吞并），顺序不敏感处追加
  ['code-review-', 'utils.runVisual.agent.codeReview'],
  ['code-fix-', 'utils.runVisual.agent.codeFix'],
  ['review-', 'utils.runVisual.agent.selfReview'],
  ['evo-', 'utils.runVisual.agent.evolution'],
  ['maintenance-', 'utils.runVisual.agent.maintenance'],
];

export const RUN_ID_PREFIX_LABEL: [prefix: string, label: string][] = RUN_ID_PREFIX_MSGS.map(
  ([prefix, msgId]) => {
    const pair: [string, string] = [prefix, ''];
    // label 位（索引 1）挂可枚举 getter：destructure `[prefix, label]`（数组
    // 迭代器按索引读）与 `pair[1]` 直读均触发访问期取值；enumerable 保持
    // 元组位可见性。访问器描述符与值描述符互斥，不携 writable。
    Object.defineProperty(pair, 1, {
      get: () => intlText(msgId),
      enumerable: true,
      configurable: true,
    });
    return pair;
  },
);

export function agentLabel(item: { agent_type?: string; run_id?: string }): string {
  const t = (item.agent_type || '').toLowerCase();
  // 泛型 'agent' 视同缺失（后端未识别出类型），继续走 run_id 前缀判别
  if (t && t !== 'agent' && AGENT_LABEL[t]) return AGENT_LABEL[t];
  const rid = (item.run_id || '').toLowerCase();
  for (const [prefix, label] of RUN_ID_PREFIX_LABEL) {
    if (rid.startsWith(prefix)) return label;
  }
  return AGENT_LABEL[t] || intlText('utils.runVisual.agent.unknown');
}

/** arbiter 台账处置结论的呈现标签（add-arbiter-quality-display 任务 2.1）。
 *
 * disposition（框架自主处置）→「自主处置」；escalation（升级人工）→
 * 「升级人工」；其余/未知 kind 原样透出（不掩盖未知形态）。渲染层单源
 * 消费，MUST NOT 在组件内内联重复该映射。 */
export function arbiterOutcomeLabel(kind: string): string {
  if (kind === 'disposition') return intlText('utils.runVisual.disposition');
  if (kind === 'escalation') return intlText('utils.runVisual.escalation');
  return kind;
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
  if (st === 'gate-blocked') return { tone: 'danger', prefix: intlText('utils.runVisual.reason.gateBlocked') };
  if (st === 'error') return { tone: 'danger', prefix: intlText('utils.runVisual.reason.error') };
  if (st === 'superseded') return { tone: 'secondary', prefix: intlText('utils.runVisual.reason.superseded') };
  return { tone: 'warning', prefix: intlText('utils.runVisual.reason.aborted') };
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
  // 非有限值守卫（code-review item 8477b895353e）：NaN/Infinity 会经 toFixed
  // 渲染「$NaN/$Infinity」字面量到时间轴，守卫口径对齐 fmtMillions，统一回退 0。
  const safe = Number.isFinite(v) ? v : 0;
  if (safe > 0 && safe < 0.01) return `$${safe.toFixed(3)}`;
  return `$${safe.toFixed(2)}`;
}
