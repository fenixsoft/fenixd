// PipelineView.tsx — SPEC 协作拓扑「管线视图」（add-spec-topology-bigscreen 4.3，
// improve-spec-topology-pipeline-view 3.1–3.3 时序化重排）。
//
// 手写 SVG + React 七阶段列布局（design D1：零图表库，确定性列坐标）：
// 左→右 需求/规划/开发/审查修复/测试验证/运维/交付；纵轴 = 真实时间线性映射
// （上→下 = 时间早→晚），同刻/时间重叠节点水平对齐（并行结构直接可读），
// 同列拥挤节点贪心行错开；左侧可折叠时间刻度列（复用协作时序 TICK_STEPS_S
// 档位与 fmtTick 文案格式）。PMEngine 状态转移（transitions）逐条渲染为带
// 时刻与状态名的小节点、按时间串成生命周期链（链置于规划列、纵坐标走同一
// 时间域）；dispatch 边自 dispatch_anchor 指向的转移节点出发（缺省回退
// PMEngine 主节点）。边着色——handoff 实线（青）、dispatch 自生命周期链出发
// （虚线）、retry 橙、approve 金；在飞（running）节点发光脉冲；失败/中止/弃
// 置着色（语义色经 runVisual.runDotColor/STATUS_HEX 单源投影）；fix-* 子
// SPEC run 节点带 🔧 角标；节点悬浮详情卡（角色/run_id/状态/LLM/耗时/成本/
// 重试）。点击节点回调 onSelect（联动高亮 + run 节点下钻由父层编排）。
// 生命周期小节点为纯展示（任务 3.2 仅定义渲染形态，不可点击/无悬浮）。

import { useMemo, useState } from 'react';
import type { CSSProperties, MouseEvent as ReactMouseEvent } from 'react';
import { statusMeta } from '@/services/dashboard';
import type { SpecTopology, TopologyEdgeType, TopologyNode, TopologyStage } from '@/services/dashboard';
import { fmtDuration } from '@/utils/duration';
import {
  fmtCost,
  fmtTick,
  midTrunc,
  parseTsMs,
  pickTickStep,
  runDotHex,
  runDotColor,
  STAGE_LABELS,
  STAGE_ORDER,
  STATUS_HEX,
} from './shared';

// ── 布局常量（确定性坐标，无布局引擎） ──
const COL_W = 190; // 列宽
const COL_GAP = 56; // 列间距（布边通道）
const NODE_H = 46; // 节点高
const NODE_GAP = 12; // 节点纵距
const HEADER_H = 64; // 列头高
const PAD = 16;
const TR_W = 150; // 生命周期小节点宽（规划列内左对齐）
const TR_H = 24; // 生命周期小节点高（design D5：~24px）
const TR_GAP = 8; // 生命周期小节点错行槽距（TR_H + 余量）
const MIN_SPAN_MS = 60_000; // 时间跨度下限（< 60s 按 60s 兜底，防零跨度除零）
const SPAN_PX_PER_S = 0.5; // 跨度线性最小高度系数（超长跨度防拥挤，design 风险 [400]）
const MAX_CONTENT_H = 24000; // 内容高渲染安全上限（浏览器 SVG 尺寸限制内，纵向滚动兜底）
const SCALE_W = 76; // 左侧时间刻度列宽

const SVG_W = PAD * 2 + COL_W * STAGE_ORDER.length + COL_GAP * (STAGE_ORDER.length - 1);
const TR_SLOT = TR_H + TR_GAP;

function nodeX(stage: TopologyStage): number {
  return PAD + STAGE_ORDER.indexOf(stage) * (COL_W + COL_GAP);
}

// ── 节点/边视觉单源（具名函数承载原嵌套三元，与 runDotColor 的单源具名
// 风格对齐——code-review item 3413bcfaf05a「禁止嵌套三元」） ──

/** 节点语义色调：run 按状态语义色单源投影；verify 绿；其余节点无色调（走蓝圆点）。 */
function nodeTone(kind: TopologyNode['kind'], status: string): string {
  if (kind === 'run') return runDotColor(status);
  if (kind === 'verify') return 'green';
  return '';
}

/** 节点边框色：选中高亮蓝优先；其次失败红/中止橙/弃置灰（runDotColor 同口径）；
 * 兜底取圆点色（特殊节点蓝）。 */
function nodeBorderColor(selected: boolean, tone: string, dot: string): string {
  if (selected) return '#40a9ff';
  if (tone === 'red') return STATUS_HEX.red;
  if (tone === 'orange') return STATUS_HEX.orange;
  if (tone === 'gray') return STATUS_HEX.gray;
  return dot;
}

/** 节点第二行文案：run 状态标签+耗时；verify 场景计数（无数据回退占位）；其余原标签。 */
function nodeSubLabel(n: TopologyNode): string {
  if (n.kind === 'run') {
    const status = n.status ?? '';
    return `${statusMeta(status).label || status || '—'}${
      n.duration_seconds != null ? ` · ${fmtDuration(n.duration_seconds)}` : ''
    }`;
  }
  if (n.kind === 'verify') {
    return n.total != null ? `共 ${n.total} · ✓${n.passed ?? '—'} ✗${n.failed ?? '—'}` : '验证轮次';
  }
  return n.label;
}

/** 边终点箭头 id：retry 橙、approve 金、其余默认青（与边线着色同口径）。 */
function edgeMarkerId(type: TopologyEdgeType): string {
  if (type === 'retry') return 'url(#topo-arrow-retry)';
  if (type === 'approve') return 'url(#topo-arrow-approve)';
  return 'url(#topo-arrow)';
}

// PMEngine 生命周期小节点（纯展示；id 与后端 dispatch_anchor 编号规则一致：
// verify 节点同款 <kind>:<序号> 风格，transitions[i] → tr:<i+1>）
interface TrNode {
  id: string;
  from: string;
  to: string;
  time: string;
}

interface TimeLayout {
  yByKey: Map<string, number>; // 真实节点 id → 纵坐标（列内错开后）
  trByKey: Map<string, number>; // tr:<n> → 纵坐标
  trNodes: TrNode[];
  ticks: { y: number; label: string }[];
  svgH: number;
  minT: number;
  spanS: number;
}

/** 真实时间纵轴布局（improve-spec-topology-pipeline-view 3.1，纯函数不触 DOM）。

- 时间域：全部可定位时刻节点（parseTsMs，含转移节点）的 min/max；跨度
  < 60s 按 60s 兜底（防零跨度除零）；无可定位时刻（归档骨架/空时刻）时
  t0 兜底 0，全部节点降级锚定 t0 行（不出现 NaN 坐标）；
- 纵坐标：y = HEADER_H + PAD + (t - t0) / span × contentH；contentH =
  max(节点数 × 行高, 跨度线性最小高度)，上限 MAX_CONTENT_H（纵向滚动兜底）；
- 同列拥挤节点：贪心行错开（泳道 assignRows 思路迁移到列内纵轴）——按时间
  纵坐标排序后逐个下移到前一节点底部之下，行偏移叠加在时间坐标上、不同列
  互不影响（他列同刻节点的水平对齐线不被覆盖）。
 */
function buildTimeLayout(data: SpecTopology): TimeLayout {
  const trNodes: TrNode[] = (data.transitions ?? []).map((t, i) => ({
    id: `tr:${i + 1}`,
    from: t.from,
    to: t.to,
    time: t.time,
  }));
  const times: number[] = [];
  for (const n of data.nodes) {
    const t = parseTsMs(n.time);
    if (t != null) times.push(t);
  }
  for (const tr of trNodes) {
    const t = parseTsMs(tr.time);
    if (t != null) times.push(t);
  }
  const minT = times.length ? Math.min(...times) : 0;
  const maxT = times.length ? Math.max(...times) : 0;
  const span = Math.max(maxT - minT, MIN_SPAN_MS);
  const slot = NODE_H + NODE_GAP;
  const nodeCount = Math.max(data.nodes.length + trNodes.length, 1);
  const contentH = Math.min(
    MAX_CONTENT_H,
    Math.max(nodeCount * slot, (span / 1000) * SPAN_PX_PER_S, 30),
  );
  const timeY = (ms: number) => HEADER_H + PAD + ((ms - minT) / span) * contentH;
  const anchorY = (s: string | undefined) => {
    const t = parseTsMs(s);
    // 无可定位时刻的节点降级锚定 t0 行（图不断链）
    return timeY(t != null ? t : minT);
  };

  // 列内贪心行错开（规划列与生命周期链共用一次级联，互不重叠）
  const yByKey = new Map<string, number>();
  const trByKey = new Map<string, number>();
  const perStage = new Map<TopologyStage, { key: string; isTr: boolean; y: number; i: number }[]>();
  data.nodes.forEach((n, i) => {
    const list = perStage.get(n.stage);
    const item = { key: n.id, isTr: false, y: anchorY(n.time), i };
    if (list) list.push(item);
    else perStage.set(n.stage, [item]);
  });
  trNodes.forEach((tr, i) => {
    const list = perStage.get('plan');
    const item = { key: tr.id, isTr: true, y: anchorY(tr.time), i };
    if (list) list.push(item);
    else perStage.set('plan', [item]);
  });
  let maxBottom = HEADER_H + PAD * 2 + NODE_H;
  perStage.forEach((items) => {
    const sorted = [...items].sort((a, b) => a.y - b.y || a.i - b.i);
    let nextFree = -Infinity;
    for (const it of sorted) {
      const step = it.isTr ? TR_SLOT : slot;
      const y = Math.max(it.y, nextFree);
      if (it.isTr) trByKey.set(it.key, y);
      else yByKey.set(it.key, y);
      nextFree = y + step;
      maxBottom = Math.max(maxBottom, y + (it.isTr ? TR_H : NODE_H));
    }
  });

  // 左侧时间刻度（复用协作时序 TICK_STEPS_S 档位与 fmtTick 文案格式）
  const spanS = span / 1000;
  const stepMs = pickTickStep(spanS) * 1000;
  const ticks: { y: number; label: string }[] = [];
  for (let ms = Math.ceil(minT / stepMs) * stepMs; ms <= minT + span; ms += stepMs) {
    ticks.push({ y: timeY(ms), label: fmtTick(ms, spanS) });
    if (ticks.length > 200) break; // 上限保护（档位选择下不可达）
  }

  return {
    yByKey,
    trByKey,
    trNodes,
    ticks,
    svgH: Math.max(maxBottom + PAD, HEADER_H + PAD * 2 + NODE_H),
    minT,
    spanS,
  };
}

export default function PipelineView({
  data,
  selectedId,
  onSelect,
}: {
  data: SpecTopology;
  selectedId: string | null;
  onSelect: (node: TopologyNode | null) => void;
}) {
  const [hover, setHover] = useState<TopologyNode | null>(null);
  const [hoverPos, setHoverPos] = useState<{ x: number; y: number }>({ x: 0, y: 0 });
  // 左侧时间刻度列折叠开关（design D4「可折叠时间刻度列」，默认展开）
  const [showScale, setShowScale] = useState(true);

  const byId = useMemo(() => new Map(data.nodes.map((n) => [n.id, n])), [data.nodes]);
  const layout = useMemo(() => buildTimeLayout(data), [data]);

  const nodeCenter = (n: TopologyNode): { x: number; y: number } | null => {
    const y = layout.yByKey.get(n.id);
    if (y == null) return null;
    return { x: nodeX(n.stage) + COL_W / 2, y: y + NODE_H / 2 };
  };

  // dispatch 边源点：目标 run 首节点带 dispatch_anchor 且对应转移节点在位时
  // 自该转移节点出发（字段缺省/链未渲染回退 PMEngine 主节点，图不断链）
  const dispatchSource = (targetId: string): { x: number; y: number } | null => {
    const target = byId.get(targetId);
    const anchor = target?.dispatch_anchor;
    if (anchor) {
      const trY = layout.trByKey.get(anchor);
      if (trY != null) {
        return { x: nodeX('plan') + 8 + TR_W / 2, y: trY + TR_H / 2 };
      }
    }
    const pm = byId.get('pm');
    return pm ? nodeCenter(pm) : null;
  };

  // 悬浮详情卡（桌面 mouseenter）；点击选中（run 节点下钻由父层 onSelect 编排）
  const handleEnter = (n: TopologyNode, e: ReactMouseEvent<SVGGElement>) => {
    setHover(n);
    const svg = e.currentTarget.ownerSVGElement;
    if (svg) {
      const rect = svg.getBoundingClientRect();
      setHoverPos({ x: e.clientX - rect.left + 14, y: e.clientY - rect.top + 10 });
    }
  };

  const stageCount = (s: TopologyStage) => data.nodes.filter((n) => n.stage === s).length;

  return (
    <div style={{ position: 'relative', display: 'flex', alignItems: 'flex-start', overflow: 'auto' }}>
      {/* 刻度列折叠开关（行为：展开/收起左侧时间刻度列，design D4） */}
      <button
        type="button"
        onClick={() => setShowScale((v) => !v)}
        title={showScale ? '收起时间刻度列' : '展开时间刻度列'}
        style={{
          position: 'absolute',
          left: 4,
          top: 4,
          zIndex: 30,
          border: '1px solid rgba(64, 169, 255, 0.45)',
          background: 'rgba(8, 18, 34, 0.9)',
          color: '#7f9cba',
          fontSize: 11,
          lineHeight: '18px',
          borderRadius: 4,
          padding: '0 7px',
          cursor: 'pointer',
        }}
      >
        {showScale ? '⇤ 刻度' : '⇥ 刻度'}
      </button>

      {/* 左侧时间刻度列（可折叠；与主图共享同一纵向坐标系） */}
      {showScale && (
        <svg width={SCALE_W} height={layout.svgH} style={{ flex: '0 0 auto', display: 'block' }}>
          <rect
            x={0}
            y={4}
            width={SCALE_W - 2}
            height={layout.svgH - 8}
            rx={10}
            fill="rgba(59, 110, 165, 0.06)"
            stroke="rgba(59, 110, 165, 0.25)"
          />
          <text x={SCALE_W / 2} y={32} textAnchor="middle" fill="#4f7196" fontSize={11}>
            时刻
          </text>
          {layout.ticks.map((t, i) => (
            <g key={`tick${i}`}>
              <line x1={SCALE_W - 10} y1={t.y} x2={SCALE_W - 4} y2={t.y} stroke="#33506f" strokeWidth={1} />
              <text x={SCALE_W - 13} y={t.y + 3.5} textAnchor="end" fill="#5b82a8" fontSize={10}>
                {t.label}
              </text>
            </g>
          ))}
        </svg>
      )}

      {/* 主图（随容器横向/纵向滚动；悬浮卡锚定本层） */}
      <div style={{ position: 'relative', flex: '0 0 auto' }}>
        <svg
          width={SVG_W}
          height={layout.svgH}
          style={{ minWidth: SVG_W, display: 'block' }}
          onMouseLeave={() => setHover(null)}
        >
          <defs>
            <filter id="topo-glow" x="-60%" y="-60%" width="220%" height="220%">
              <feGaussianBlur stdDeviation="4" result="blur" />
              <feMerge>
                <feMergeNode in="blur" />
                <feMergeNode in="SourceGraphic" />
              </feMerge>
            </filter>
            <marker id="topo-arrow" markerWidth="8" markerHeight="8" refX="7" refY="3" orient="auto">
              <path d="M0,0 L7,3 L0,6 Z" fill="#3b6ea5" />
            </marker>
            <marker id="topo-arrow-retry" markerWidth="8" markerHeight="8" refX="7" refY="3" orient="auto">
              <path d="M0,0 L7,3 L0,6 Z" fill="#fa8c16" />
            </marker>
            <marker id="topo-arrow-approve" markerWidth="8" markerHeight="8" refX="7" refY="3" orient="auto">
              <path d="M0,0 L7,3 L0,6 Z" fill="#fadb14" />
            </marker>
          </defs>

          {/* 列背景与列头 */}
          {STAGE_ORDER.map((s) => (
            <g key={s}>
              <rect
                x={nodeX(s) - 8}
                y={4}
                width={COL_W + 16}
                height={layout.svgH - 8}
                rx={10}
                fill="rgba(59, 110, 165, 0.10)"
                stroke="rgba(59, 110, 165, 0.35)"
              />
              <text x={nodeX(s) + COL_W / 2} y={32} textAnchor="middle" fill="#8fb8dd" fontSize={15} fontWeight={600}>
                {STAGE_LABELS[s]}
              </text>
              <text x={nodeX(s) + COL_W / 2} y={50} textAnchor="middle" fill="#4f7196" fontSize={11}>
                {stageCount(s)} 节点
              </text>
            </g>
          ))}

          {/* 边（先画，节点覆盖端点）：handoff/dispatch 青、retry 橙、approve 金。
              dispatch 边自 dispatch_anchor 指向的转移节点出发（缺省回退 pm 主节点） */}
          {data.edges.map((e, i) => {
            const a = byId.get(e.from);
            const b = byId.get(e.to);
            if (!a || !b) return null;
            const pa = e.type === 'dispatch' ? dispatchSource(b.id) : nodeCenter(a);
            const pb = nodeCenter(b);
            if (!pa || !pb) return null;
            const sameCol = pa.x === pb.x;
            const x1 = sameCol ? pa.x + COL_W / 2 + 6 : pa.x + (pb.x > pa.x ? COL_W / 2 : -COL_W / 2);
            const x2 = sameCol ? pb.x + COL_W / 2 + 6 : pb.x + (pb.x > pa.x ? -COL_W / 2 : COL_W / 2);
            const midX = (x1 + x2) / 2;
            const d = `M ${x1} ${pa.y} C ${midX} ${pa.y}, ${midX} ${pb.y}, ${x2} ${pb.y}`;
            const isRetry = e.type === 'retry';
            const isApprove = e.type === 'approve';
            return (
              <path
                key={`e${i}`}
                d={d}
                fill="none"
                stroke={isRetry ? '#fa8c16' : isApprove ? '#fadb14' : '#3b6ea5'}
                strokeWidth={isRetry || isApprove ? 1.6 : 1.1}
                strokeDasharray={e.type === 'dispatch' ? '5 3' : undefined}
                opacity={0.75}
                markerEnd={edgeMarkerId(e.type)}
              />
            );
          })}

          {/* PMEngine 生命周期节点链（transitions 非空才渲染；纯展示不可点击，
              任务 3.2 仅定义渲染形态）。链节点间细连线表达串联次序 */}
          {layout.trNodes.length > 1 && (
            <polyline
              points={layout.trNodes
                .map((tr) => {
                  const y = layout.trByKey.get(tr.id);
                  return y != null ? `${nodeX('plan') + 8 + TR_W / 2},${y + TR_H / 2}` : '';
                })
                .filter(Boolean)
                .join(' ')}
              fill="none"
              stroke="rgba(64, 169, 255, 0.30)"
              strokeWidth={1}
              strokeDasharray="2 4"
            />
          )}
          {layout.trNodes.map((tr) => {
            const y = layout.trByKey.get(tr.id);
            if (y == null) return null;
            return (
              <g key={tr.id} transform={`translate(${nodeX('plan') + 8}, ${y})`}>
                <rect
                  width={TR_W}
                  height={TR_H}
                  rx={6}
                  fill="rgba(10, 22, 40, 0.92)"
                  stroke="rgba(64, 169, 255, 0.45)"
                  strokeWidth={1}
                />
                <circle cx={9} cy={TR_H / 2} r={3} fill={STATUS_HEX.blue} />
                {/* design D5：标签为完整「→<目标状态>」，不做中段截断——
                    长状态名（implementing/implemented）截形互相难辨且违反
                    「节点显示目标状态名」契约（验证轮 BUG-01 修复） */}
                <text x={16} y={11} fill="#d6e7f7" fontSize={10} fontWeight={600}>
                  →{tr.to}
                </text>
                <text x={16} y={20.5} fill="#5b82a8" fontSize={8.5}>
                  {parseTsMs(tr.time) != null ? fmtTick(parseTsMs(tr.time)!, layout.spanS) : '—'}
                  {` · ${tr.from}`}
                </text>
              </g>
            );
          })}

          {/* 节点 */}
          {data.nodes.map((n) => {
            const y = layout.yByKey.get(n.id);
            if (y == null) return null;
            const status = n.status ?? '';
            const isRunning = n.kind === 'run' && (status === 'running' || status === 'empty');
            const tone = nodeTone(n.kind, status);
            // 着色：run 走状态语义色单源（失败红/中止橙/弃置灰）；verify 绿；特殊节点蓝
            const dot = n.kind === 'run' ? runDotHex(status) : n.kind === 'verify' ? STATUS_HEX.green : STATUS_HEX.blue;
            const border = nodeBorderColor(selectedId === n.id, tone, dot);
            return (
              <g
                key={n.id}
                transform={`translate(${nodeX(n.stage)}, ${y})`}
                style={{ cursor: 'pointer' }}
                onMouseEnter={(e) => handleEnter(n, e)}
                onClick={() => onSelect(n)}
              >
                <rect
                  width={COL_W}
                  height={NODE_H}
                  rx={8}
                  fill="rgba(10, 22, 40, 0.92)"
                  stroke={border}
                  strokeWidth={selectedId === n.id ? 2.2 : tone === 'red' || tone === 'orange' || isRunning ? 1.6 : 1}
                  filter={isRunning ? 'url(#topo-glow)' : undefined}
                >
                  {isRunning && (
                    <animate attributeName="stroke-opacity" values="1;0.35;1" dur="1.6s" repeatCount="indefinite" />
                  )}
                </rect>
                <circle cx={14} cy={NODE_H / 2} r={4.5} fill={dot} />
                {isRunning && (
                  <circle cx={14} cy={NODE_H / 2} r={4.5} fill={dot} opacity={0.5}>
                    <animate attributeName="r" values="4.5;7.5;4.5" dur="1.6s" repeatCount="indefinite" />
                  </circle>
                )}
                <text x={26} y={19} fill="#d6e7f7" fontSize={12.5} fontWeight={600}>
                  {n.kind === 'verify' ? '验证执行' : midTrunc(n.label, 11)}
                  {n.kind === 'run' && n.attempt != null && n.attempt > 1 ? ` ·a${n.attempt}` : ''}
                </text>
                <text x={26} y={35} fill="#7f9cba" fontSize={10.5}>
                  {nodeSubLabel(n)}
                </text>
                {n.fix && (
                  <>
                    <text x={COL_W - 16} y={20} fontSize={13} textAnchor="middle">
                      🔧
                    </text>
                    <text x={COL_W - 16} y={36} fontSize={9} textAnchor="middle" fill="#7f9cba">
                      fix
                    </text>
                  </>
                )}
              </g>
            );
          })}
        </svg>

        {/* 悬浮详情卡（HTML overlay；角色/run_id/状态/LLM/耗时/成本/重试） */}
        {hover && (
          <div style={{ ...hoverCardStyle, left: hoverPos.x, top: hoverPos.y }}>
            <div style={{ fontWeight: 700, marginBottom: 4 }}>
              {hover.kind === 'verify' ? '验证执行' : hover.label}
              {hover.fix ? ' 🔧' : ''}
            </div>
            {hover.run_id && <div style={hoverRowStyle}>run_id：{midTrunc(hover.run_id)}</div>}
            {hover.kind === 'run' && (
              <div style={hoverRowStyle}>状态：{statusMeta(hover.status ?? '').label}</div>
            )}
            {hover.kind === 'verify' && hover.total != null && (
              <div style={hoverRowStyle}>
                场景：共 {hover.total} · 通过 {hover.passed ?? '—'} · 失败 {hover.failed ?? '—'}
              </div>
            )}
            {hover.llm && <div style={hoverRowStyle}>LLM：{midTrunc(hover.llm)}</div>}
            {hover.duration_seconds != null && (
              <div style={hoverRowStyle}>耗时：{fmtDuration(hover.duration_seconds)}</div>
            )}
            {hover.cost_usd != null && <div style={hoverRowStyle}>成本：{fmtCost(hover.cost_usd)}</div>}
            {hover.kind === 'run' && hover.attempt != null && (
              <div style={hoverRowStyle}>
                重试：attempt {hover.attempt}
                {hover.transient_retry != null ? ` · 瞬态 r${hover.transient_retry}` : ''}
              </div>
            )}
            {hover.summary && (
              <div style={{ ...hoverRowStyle, maxWidth: 320, whiteSpace: 'normal' }}>
                摘要：{midTrunc(hover.summary, 120)}
              </div>
            )}
            <div style={{ marginTop: 4, color: '#5b82a8', fontSize: 11 }}>
              {hover.kind === 'run' ? '点击查看运行记录' : '点击选中，跨视图联动高亮'}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

const hoverCardStyle: CSSProperties = {
  position: 'absolute',
  zIndex: 20,
  pointerEvents: 'none',
  background: 'rgba(8, 18, 34, 0.97)',
  border: '1px solid rgba(64, 169, 255, 0.5)',
  borderRadius: 8,
  padding: '8px 10px',
  color: '#d6e7f7',
  fontSize: 12,
  lineHeight: 1.6,
  boxShadow: '0 6px 24px rgba(0, 0, 0, 0.55)',
  maxWidth: 380,
};

const hoverRowStyle: CSSProperties = { whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' };
