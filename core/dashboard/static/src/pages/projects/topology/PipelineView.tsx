// PipelineView.tsx — SPEC 协作拓扑「管线视图」（add-spec-topology-bigscreen 4.3）。
//
// 手写 SVG + React 七阶段列布局（design D1：零图表库，确定性列坐标）：
// 左→右 需求/规划/开发/审查修复/测试验证/运维/交付，同角色多轮同列按时间
// 自上而下重复；用户/fenix-new 为需求列入口节点、PMEngine 为规划列调度节点；
// 边着色——handoff 实线（青）、dispatch 自 PMEngine 出发（虚线）、retry 橙、
// approve 金；在飞（running）节点发光脉冲；失败/门禁拒绝红、中止橙、弃置
// 中性灰（语义色经 runVisual.runDotColor/STATUS_HEX 单源投影）；fix-* 子
// SPEC run 节点带 🔧 角标；节点悬浮详情卡（角色/run_id/状态/LLM/耗时/成本/
// 重试）。点击节点回调 onSelect（联动高亮 + run 节点下钻由父层编排）。

import { useMemo, useState } from 'react';
import type { CSSProperties, MouseEvent as ReactMouseEvent } from 'react';
import { statusMeta } from '@/services/dashboard';
import type { SpecTopology, TopologyNode, TopologyStage } from '@/services/dashboard';
import { fmtDuration } from '@/utils/duration';
import { fmtCost, midTrunc, runDotHex, runDotColor, STAGE_LABELS, STAGE_ORDER, STATUS_HEX } from './shared';

// ── 布局常量（确定性坐标，无布局引擎） ──
const COL_W = 190; // 列宽
const COL_GAP = 56; // 列间距（布边通道）
const NODE_H = 46; // 节点高
const NODE_GAP = 12; // 节点纵距
const HEADER_H = 64; // 列头高
const PAD = 16;

const SVG_W = PAD * 2 + COL_W * STAGE_ORDER.length + COL_GAP * (STAGE_ORDER.length - 1);

function nodeX(stage: TopologyStage): number {
  return PAD + STAGE_ORDER.indexOf(stage) * (COL_W + COL_GAP);
}

interface ColumnLayout {
  yByKey: Map<string, number>;
  svgH: number;
}

/** 列内纵向布局：同列节点按 time 自上而下（同刻稳定按数据序），产出每节点
 * 纵坐标与 SVG 总高。纯函数（不触 DOM），列头/背景共用同一坐标系。 */
function layoutColumns(nodes: TopologyNode[]): ColumnLayout {
  const perStage = new Map<TopologyStage, TopologyNode[]>();
  for (const n of nodes) {
    const list = perStage.get(n.stage);
    if (list) list.push(n);
    else perStage.set(n.stage, [n]);
  }
  const yByKey = new Map<string, number>();
  let maxBottom = HEADER_H + PAD * 2 + NODE_H;
  for (const [stage, list] of perStage) {
    const stable = [...list].sort((a, b) =>
      String(a.time ?? '').localeCompare(String(b.time ?? '')),
    );
    stable.forEach((n, i) => {
      const y = HEADER_H + PAD + i * (NODE_H + NODE_GAP);
      yByKey.set(n.id, y);
      maxBottom = Math.max(maxBottom, y + NODE_H);
    });
    void stage;
  }
  return { yByKey, svgH: maxBottom + PAD };
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

  const byId = useMemo(() => new Map(data.nodes.map((n) => [n.id, n])), [data.nodes]);
  const layout = useMemo(() => layoutColumns(data.nodes), [data.nodes]);

  const nodeCenter = (n: TopologyNode): { x: number; y: number } | null => {
    const y = layout.yByKey.get(n.id);
    if (y == null) return null;
    return { x: nodeX(n.stage) + COL_W / 2, y: y + NODE_H / 2 };
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
    <div style={{ position: 'relative', overflowX: 'auto' }}>
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

        {/* 边（先画，节点覆盖端点）：handoff/dispatch 青、retry 橙、approve 金 */}
        {data.edges.map((e, i) => {
          const a = byId.get(e.from);
          const b = byId.get(e.to);
          if (!a || !b) return null;
          const pa = nodeCenter(a);
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
              markerEnd={
                isRetry
                  ? 'url(#topo-arrow-retry)'
                  : isApprove
                    ? 'url(#topo-arrow-approve)'
                    : 'url(#topo-arrow)'
              }
            />
          );
        })}

        {/* 节点 */}
        {data.nodes.map((n) => {
          const y = layout.yByKey.get(n.id);
          if (y == null) return null;
          const status = n.status ?? '';
          const isRunning = n.kind === 'run' && (status === 'running' || status === 'empty');
          const tone = n.kind === 'run' ? runDotColor(status) : n.kind === 'verify' ? 'green' : '';
          // 着色：run 走状态语义色单源（失败红/中止橙/弃置灰）；verify 绿；特殊节点蓝
          const dot = n.kind === 'run' ? runDotHex(status) : n.kind === 'verify' ? STATUS_HEX.green : STATUS_HEX.blue;
          const border =
            selectedId === n.id
              ? '#40a9ff'
              : tone === 'red'
                ? STATUS_HEX.red
                : tone === 'orange'
                  ? STATUS_HEX.orange
                  : tone === 'gray'
                    ? STATUS_HEX.gray
                    : dot;
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
                {n.kind === 'run'
                  ? `${statusMeta(status).label || status || '—'}${n.duration_seconds != null ? ` · ${fmtDuration(n.duration_seconds)}` : ''}`
                  : n.kind === 'verify'
                    ? n.total != null
                      ? `共 ${n.total} · ✓${n.passed ?? '—'} ✗${n.failed ?? '—'}`
                      : '验证轮次'
                    : n.time
                      ? n.label
                      : n.label}
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
