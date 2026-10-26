// SwimlaneView.tsx — SPEC 协作拓扑「协作时序视图」（add-spec-topology-bigscreen 4.4）。
//
// 手写 SVG + React 八泳道时序（design D1：零图表库；坐标=真实时间线性映射）：
// 行 = 用户/PMEngine/需求评审/规划/开发/审查修复/测试验证/运维，横轴 = 真实
// 时间。run 为色块（宽度=耗时、同泳道并行按行错开），PMEngine 泳道含派发
// 标记（▾，来自 dispatch 边）与状态转移刻度（竖线 + 状态短标），用户泳道含
// 人工动作标记；跨泳道箭头 = handoff 交接；在飞 run 色块右端虚线尾迹（延伸
// 至时间轴右端）。交付终点不单设泳道——以 PMEngine 泳道 pushed 转移刻度收尾。
// 时间刻度自适应（分钟/小时档）；内容宽随跨度线性伸缩，容器横向滚动（泳道
// 标签列固定在左侧始终可见）。

import { useMemo } from 'react';
import { statusMeta } from '@/services/dashboard';
import type { SpecTopology, TopologyEdge, TopologyNode } from '@/services/dashboard';
import { fmtDuration } from '@/utils/duration';
import {
  LANE_LABELS,
  LANE_ORDER,
  midTrunc,
  parseTsMs,
  runDotHex,
  fmtTick,
  pickTickStep,
  STATUS_HEX,
} from './shared';

const LANE_H = 64; // 泳道行高
const ROW_H = 18; // 泳道内并行错行行高
const LABEL_W = 96; // 左侧泳道标签列宽（固定，不随滚动）
const PAD_X = 20; // 时间轴左右内边距
const HEADER_H = 34; // 刻度头高
const MIN_CONTENT_W = 720; // 内容最小宽（短跨度不压缩到不可读）

// 泳道内并行错行：按开始时间排序后做「行占用区间」贪心分配（重叠块换行）
function assignRows(items: { start: number; end: number }[]): number[] {
  const order = items
    .map((it, i) => ({ i, start: it.start, end: it.end }))
    .sort((a, b) => a.start - b.start || a.end - b.end);
  const rowEnds: number[] = [];
  const rows = new Array(items.length).fill(0);
  for (const it of order) {
    let placed = false;
    for (let r = 0; r < rowEnds.length; r++) {
      if (it.start >= rowEnds[r]) {
        rows[it.i] = r;
        rowEnds[r] = it.end;
        placed = true;
        break;
      }
    }
    if (!placed) {
      rows[it.i] = rowEnds.length;
      rowEnds.push(it.end);
    }
  }
  return rows;
}

/** 色块着色（具名函数承载原嵌套三元，与 runDotColor 单源具名风格对齐——
 * code-review item 3413bcfaf05a「禁止嵌套三元」）：run 按状态语义色单源
 * 投影；verify 绿；特殊节点蓝（与 PipelineView 圆点同口径）。 */
function blockColor(n: TopologyNode): string {
  if (n.kind === 'run') return runDotHex(n.status ?? '');
  if (n.kind === 'verify') return STATUS_HEX.green;
  return STATUS_HEX.blue;
}

export default function SwimlaneView({
  data,
  selectedId,
  onSelect,
}: {
  data: SpecTopology;
  selectedId: string | null;
  onSelect: (node: TopologyNode | null) => void;
}) {
  const model = useMemo(() => buildModel(data), [data]);
  if (!model) {
    return (
      <div style={{ color: '#7f9cba', padding: 24 }}>暂无可定位时刻的节点，无法渲染时序。</div>
    );
  }

  const { t0, t1, contentW, x, blocks, marks, arrows } = model;
  const svgH = HEADER_H + LANE_ORDER.length * LANE_H + 12;

  return (
    <div style={{ display: 'flex', alignItems: 'stretch', overflowX: 'auto' }}>
      {/* 泳道标签列（固定宽度，随外层滚动保持可见） */}
      <svg width={LABEL_W} height={svgH} style={{ flex: '0 0 auto', display: 'block' }}>
        {LANE_ORDER.map((lane, li) => (
          <g key={lane}>
            <rect
              x={0}
              y={HEADER_H + li * LANE_H}
              width={LABEL_W - 2}
              height={LANE_H - 2}
              fill="rgba(59, 110, 165, 0.12)"
              stroke="rgba(59, 110, 165, 0.30)"
            />
            <text
              x={LABEL_W / 2}
              y={HEADER_H + li * LANE_H + LANE_H / 2 + 4}
              textAnchor="middle"
              fill="#8fb8dd"
              fontSize={12.5}
              fontWeight={600}
            >
              {LANE_LABELS[lane]}
            </text>
          </g>
        ))}
      </svg>

      {/* 时间区（随容器横向滚动） */}
      <svg width={contentW} height={svgH} style={{ display: 'block' }}>
        {/* 泳道底 + 刻度 */}
        {LANE_ORDER.map((_, li) => (
          <rect
            key={li}
            x={0}
            y={HEADER_H + li * LANE_H}
            width={contentW}
            height={LANE_H - 2}
            fill={li % 2 ? 'rgba(59, 110, 165, 0.06)' : 'rgba(59, 110, 165, 0.12)'}
            stroke="rgba(59, 110, 165, 0.30)"
          />
        ))}
        {model.ticks.map((tk) => (
          <g key={tk.ms}>
            <line x1={tk.x} y1={HEADER_H - 6} x2={tk.x} y2={svgH - 8} stroke="rgba(143, 184, 221, 0.25)" strokeDasharray="2 4" />
            <text x={tk.x} y={20} textAnchor="middle" fill="#6f93b8" fontSize={10.5}>
              {tk.label}
            </text>
          </g>
        ))}

        {/* 跨泳道交接箭头（画在色块下层） */}
        {arrows.map((a, i) => (
          <path
            key={`a${i}`}
            d={a.d}
            fill="none"
            stroke="rgba(143, 184, 221, 0.65)"
            strokeWidth={1}
            markerEnd="url(#lane-arrow)"
          />
        ))}
        <defs>
          <marker id="lane-arrow" markerWidth="7" markerHeight="7" refX="6" refY="2.5" orient="auto">
            <path d="M0,0 L6,2.5 L0,5 Z" fill="rgba(143, 184, 221, 0.8)" />
          </marker>
        </defs>

        {/* PMEngine 泳道：派发标记 + 状态转移刻度（含 pushed 终点收尾） */}
        {marks.map((m, i) => (
          <g key={`m${i}`}>
            <line
              x1={m.x}
              y1={HEADER_H + 1 * LANE_H + 8}
              x2={m.x}
              y2={HEADER_H + 1 * LANE_H + LANE_H - 12}
              stroke={m.pushed ? STATUS_HEX.green : 'rgba(143, 184, 221, 0.8)'}
              strokeWidth={m.pushed ? 2 : 1}
            />
            <text
              x={m.x}
              y={HEADER_H + LANE_H - 4}
              textAnchor="middle"
              fill={m.pushed ? STATUS_HEX.green : '#6f93b8'}
              fontSize={9}
            >
              {m.pushed ? `pushed ▸ ${m.label}` : midTrunc(m.label, 6)}
            </text>
          </g>
        ))}

        {/* 用户泳道人工动作标记 */}
        {model.userMarks.map((m, i) => (
          <g key={`u${i}`}>
            <circle cx={m.x} cy={HEADER_H + LANE_H / 2} r={5} fill={STATUS_HEX.blue} />
            <text x={m.x} y={HEADER_H + LANE_H / 2 - 10} textAnchor="middle" fill="#8fb8dd" fontSize={9.5}>
              {m.label}
            </text>
          </g>
        ))}

        {/* run/verify 色块（宽度=耗时、并行错行；在飞右端虚线尾迹） */}
        {blocks.map((b) => {
          const w = Math.max(b.w, 4);
          const isSel = selectedId === b.node.id;
          const running = b.node.kind === 'run' && (b.node.status === 'running' || b.node.status === 'empty');
          return (
            <g
              key={b.node.id}
              style={{ cursor: 'pointer' }}
              onClick={() => onSelect(b.node)}
            >
              <title>
                {b.node.label}
                {b.node.status ? ` · ${statusMeta(b.node.status).label}` : ''}
                {b.node.duration_seconds != null ? ` · ${fmtDuration(b.node.duration_seconds)}` : ''}
              </title>
              <rect
                x={b.x}
                y={HEADER_H + b.laneIdx * LANE_H + 8 + b.row * ROW_H}
                width={w}
                height={ROW_H - 6}
                rx={4}
                fill={b.color}
                opacity={isSel ? 1 : 0.82}
                stroke={isSel ? '#40a9ff' : 'rgba(214, 231, 247, 0.45)'}
                strokeWidth={isSel ? 2 : 0.8}
              />
              {running && (
                <line
                  x1={b.x + w}
                  y1={HEADER_H + b.laneIdx * LANE_H + 8 + b.row * ROW_H + (ROW_H - 6) / 2}
                  x2={contentW - PAD_X}
                  y2={HEADER_H + b.laneIdx * LANE_H + 8 + b.row * ROW_H + (ROW_H - 6) / 2}
                  stroke={b.color}
                  strokeWidth={1.2}
                  strokeDasharray="4 4"
                  opacity={0.7}
                >
                  <animate attributeName="stroke-dashoffset" values="0;8" dur="1s" repeatCount="indefinite" />
                </line>
              )}
              {w > 56 && (
                <text
                  x={b.x + 4}
                  y={HEADER_H + b.laneIdx * LANE_H + 8 + b.row * ROW_H + 12}
                  fill="#0a1628"
                  fontSize={9}
                  fontWeight={600}
                >
                  {midTrunc(b.node.kind === 'verify' ? '验证执行' : b.node.label, Math.floor(w / 7))}
                </text>
              )}
            </g>
          );
        })}
      </svg>
    </div>
  );
}

// ── 数据 → 坐标模型（纯函数；便于单测与复用） ──

interface Block {
  node: TopologyNode;
  laneIdx: number;
  row: number;
  x: number;
  w: number;
  color: string;
}

interface Mark {
  x: number;
  label: string;
  pushed: boolean;
}

interface SwimModel {
  t0: number;
  t1: number;
  spanS: number;
  contentW: number;
  x: (ms: number) => number;
  ticks: { ms: number; x: number; label: string }[];
  blocks: Block[];
  marks: Mark[];
  userMarks: { x: number; label: string }[];
  arrows: { d: string }[];
}

function buildModel(data: SpecTopology): SwimModel | null {
  // 有效时刻节点集（泳道与时间轴只覆盖可定位节点；全缺失 → 显式空态）
  const timed = data.nodes
    .map((n) => ({ n, ms: parseTsMs(n.time) }))
    .filter((p): p is { n: TopologyNode; ms: number } => p.ms != null);
  if (!timed.length) return null;

  // run/verify 色块节点（lane 归属：run 按 lane 字段；verify 固定 test 泳道）
  const laneNodes = timed.filter(
    (p) => (p.n.kind === 'run' && p.n.lane) || p.n.kind === 'verify',
  );
  // 时间域纳入 transitions/user_actions 的可定位时刻与色块 end 的 30s 最小延伸，
  // 否则越界时刻的标记/色块经 x(ms) 线性映射后会落在可视区外被 SVG 视口裁剪
  const markTimes = [
    ...data.transitions.map((tr) => parseTsMs(tr.time)),
    ...(data.user_actions ?? []).map((a) => parseTsMs(a.time)),
  ].filter((ms): ms is number => ms != null);

  let t0 = Math.min(...timed.map((p) => p.ms), ...markTimes);
  let t1 = Math.max(
    ...timed.map((p) => {
      const dur = p.n.duration_seconds;
      const end = dur != null ? p.ms + dur * 1000 : p.ms;
      return end;
    }),
    ...markTimes,
    // 与下方色块 end = start + max(dur, 30s) 保持一致，避免末端色块越过右缘被裁剪
    ...laneNodes.map((p) => p.ms + Math.max(p.n.duration_seconds ?? 0, 30) * 1000),
  );
  if (t1 <= t0) t1 = t0 + 60_000; // 全零跨度给最小可视区间

  const spanS = (t1 - t0) / 1000;
  // 内容宽随跨度线性伸缩：目标 1 分钟 ≈ 14px（自适应档：短跨度密、长跨度疏），
  // 不设上限 → 长跨度横向滚动（泳道标签固定左列保持可见）
  const plotW = Math.max(MIN_CONTENT_W - LABEL_W, (t1 - t0) / 60000 * 14);
  const contentW = plotW + PAD_X * 2;
  const x = (ms: number) => PAD_X + ((ms - t0) / (t1 - t0)) * plotW;

  // 刻度
  const stepMs = pickTickStep(spanS) * 1000;
  const ticks: { ms: number; x: number; label: string }[] = [];
  for (let ms = Math.ceil(t0 / stepMs) * stepMs; ms <= t1; ms += stepMs) {
    ticks.push({ ms, x: x(ms), label: fmtTick(ms, spanS) });
  }

  // run/verify 色块
  const perLane = new Map<string, { node: TopologyNode; start: number; end: number }[]>();
  for (const { n, ms } of laneNodes) {
    const lane = n.kind === 'verify' ? 'test' : (n.lane as string);
    const dur = n.duration_seconds ?? 0;
    const list = perLane.get(lane);
    const item = { node: n, start: ms, end: ms + Math.max(dur, 30) * 1000 };
    if (list) list.push(item);
    else perLane.set(lane, [item]);
  }
  const blocks: Block[] = [];
  for (const [lane, items] of perLane) {
    const laneIdx = LANE_ORDER.indexOf(lane as never);
    if (laneIdx < 0) continue;
    const rows = assignRows(items);
    items.forEach((it, i) => {
      const n = it.node;
      const color = blockColor(n);
      blocks.push({
        node: n,
        laneIdx,
        row: rows[i],
        x: x(it.start),
        w: Math.max(((it.end - it.start) / (t1 - t0)) * plotW, 4),
        color,
      });
    });
  }

  // PMEngine 泳道标记：状态转移刻度（pushed 绿色加粗收尾）
  const marks: Mark[] = [];
  for (const tr of data.transitions) {
    const ms = parseTsMs(tr.time);
    if (ms == null) continue;
    marks.push({ x: x(ms), label: `${tr.from}→${tr.to}`, pushed: tr.to === 'pushed' });
  }

  // 用户泳道人工动作标记
  const userMarks: { x: number; label: string }[] = [];
  for (const a of data.user_actions ?? []) {
    const ms = parseTsMs(a.time);
    if (ms == null) continue;
    userMarks.push({ x: x(ms), label: a.action });
  }

  // 跨泳道交接箭头：handoff 边两端均可定位时画肘形折线（源块右端 → 目标块左端）
  const posById = new Map<string, { x1: number; x2: number; y: number }>();
  for (const b of blocks) {
    const y = HEADER_H + b.laneIdx * LANE_H + 8 + b.row * ROW_H + (ROW_H - 6) / 2;
    posById.set(b.node.id, { x1: b.x, x2: b.x + Math.max(b.w, 4), y });
  }
  const arrows: { d: string }[] = [];
  for (const e of data.edges as TopologyEdge[]) {
    if (e.type !== 'handoff') continue;
    const a = posById.get(e.from);
    const b = posById.get(e.to);
    if (!a || !b) continue;
    const midX = (a.x2 + b.x1) / 2;
    arrows.push({
      d: `M ${a.x2} ${a.y} L ${midX} ${a.y} L ${midX} ${b.y} L ${b.x1 - 2} ${b.y}`,
    });
  }

  return { t0, t1, spanS, contentW, x, ticks, blocks, marks, userMarks, arrows };
}
