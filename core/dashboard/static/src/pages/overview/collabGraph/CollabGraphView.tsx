// CollabGraphView.tsx — 角色固定就位协作图谱（add-collab-graph-bigscreen 3.3）。
//
// 手写 SVG + React（零图表库依赖，specs「overview 入口与脱壳大屏路由」红线）：
// 8 个角色节点按 SDLC 流向固定就位（蛇形两行确定性坐标——上行 用户→PMEngine→
// 需求评审→规划，下行 开发→审查/修复→测试/验证→运维，规划→开发纵向衔接，
// 无力导向算法），两次进入节点位置完全一致，仅大小/边宽/脉动随数据变化
// （specs「角色固定就位图谱」Scenario「固定就位可预期」）。
//
// 数据映射（specs 同 Requirement）：
// - 节点大小映射累计时长（实现裁量取一，全屏一致；成本以文字随节点标注）；
// - 在飞角色发光脉冲（SVG <animate>；状态语义色经 @/utils/runVisual 单源）；
// - 边宽映射交接次数（weight，同一线性映射函数），marker 箭头给方向指示；
// - 点击节点/边打开下钻明细面板（recent_runs 直接渲染，含项目/SPEC/时间/
//   状态），条目可跳转对应 SPEC 单 SPEC 协作拓扑大屏；归档条目标注
//   「明细已归档清理」且不可跳转。

import { useMemo, useState } from 'react';
import { history } from '@umijs/max';
import { Button, Drawer, Empty, Table, Tag, Tooltip } from 'antd';
import type { CollabEdge, CollabGraphData, CollabRoleNode, CollabRunEntry } from '@/services/dashboard';
import { fmtCost, runDotHex } from '@/pages/projects/topology/shared';
import { fmtDuration } from '@/utils/duration';

// 深色大屏配色（与单 SPEC 拓扑大屏同一 IOC 色系）
const BG = '#0a1628';
const TEXT_MAIN = '#d6e7f7';
const TEXT_SUB = '#7f9cba';
const NODE_FILL = '#132c4d';
const NODE_STROKE = '#3b6ea5';
const EDGE_STROKE = 'rgba(64, 169, 255, 0.5)';
const EDGE_STROKE_ACTIVE = '#40a9ff';
const INFLIGHT_STROKE = '#36cfc9';

// 固定就位坐标（viewBox 1440×620；蛇形两行，SDLC 流向确定）。
// ⚠️ 坐标为模块级常量：MUST NOT 依赖数据/窗口尺寸，保证跨日汇报可比对。
const ROLE_POS: Record<string, { x: number; y: number }> = {
  user: { x: 140, y: 150 },
  pm: { x: 380, y: 150 },
  demand: { x: 620, y: 150 },
  plan: { x: 860, y: 150 },
  dev: { x: 860, y: 430 },
  review: { x: 620, y: 430 },
  test: { x: 380, y: 430 },
  ops: { x: 140, y: 430 },
};

type Selection =
  | { kind: 'role'; node: CollabRoleNode }
  | { kind: 'edge'; edge: CollabEdge }
  | null;

/** 节点半径：累计时长 → 面积感映射（sqrt），零数据取最小半径。同一映射
 * 函数全屏一致，两次进入仅随数据变化。 */
function roleRadius(durationSeconds: number, maxDuration: number): number {
  if (maxDuration <= 0) return 22;
  const ratio = Math.max(0, durationSeconds) / maxDuration;
  return 22 + 30 * Math.sqrt(ratio);
}

/** 边宽：weight → 同一线性映射（specs Scenario「边宽随交接次数变化」——
 * 同一映射函数下 weight 大者显著宽）。 */
function edgeWidth(weight: number, maxWeight: number): number {
  if (maxWeight <= 0) return 2;
  return 2 + 6 * (Math.max(0, weight) / maxWeight);
}

/** 圆边界裁剪：中心连线按两端半径内缩（箭头额外留 12px）。 */
function trimmedLine(a: { x: number; y: number }, ra: number, b: { x: number; y: number }, rb: number) {
  const dx = b.x - a.x;
  const dy = b.y - a.y;
  const len = Math.sqrt(dx * dx + dy * dy) || 1;
  const ux = dx / len;
  const uy = dy / len;
  return {
    x1: a.x + ux * (ra + 4),
    y1: a.y + uy * (ra + 4),
    x2: b.x - ux * (rb + 12),
    y2: b.y - uy * (rb + 12),
  };
}

/** 下钻明细表（角色节点 / 交接边共用）：recent_runs 直接渲染，零二次请求
 * （specs「跨项目角色图谱聚合端点」——明细随聚合内嵌下发）。 */
function DrilldownTable({ entries }: { entries: CollabRunEntry[] }) {
  if (!entries.length) {
    return <Empty description="暂无交接明细" style={{ padding: 24 }} />;
  }
  return (
    <Table
      size="small"
      rowKey={(_, i) => String(i)}
      pagination={{ pageSize: 8, hideOnSinglePage: true }}
      dataSource={entries.map((e, i) => ({ ...e, key: i }))}
      columns={[
        { title: '项目', dataIndex: 'project', width: 120 },
        {
          title: 'SPEC',
          dataIndex: 'spec',
          ellipsis: true,
          render: (v: string) => <span style={{ fontFamily: 'monospace' }}>{v}</span>,
        },
        { title: '时间', dataIndex: 'time', width: 190 },
        {
          title: '状态',
          dataIndex: 'status',
          width: 110,
          render: (v: string) => (
            <Tag color={runDotHex(v)} style={{ marginInlineEnd: 0 }}>
              {v || '—'}
            </Tag>
          ),
        },
        {
          title: '操作',
          width: 130,
          render: (_, r: CollabRunEntry) =>
            r.archived ? (
              <Tooltip title="明细已归档清理，不可跳转单 SPEC 大屏">
                <Tag style={{ marginInlineEnd: 0 }}>明细已归档清理</Tag>
              </Tooltip>
            ) : (
              <Button
                size="small"
                type="link"
                onClick={() =>
                  history.push(
                    `/projects/${encodeURIComponent(r.project)}/${encodeURIComponent(r.spec)}/topology`,
                  )
                }
              >
                单 SPEC 大屏
              </Button>
            ),
        },
      ]}
    />
  );
}

export default function CollabGraphView({ data }: { data: CollabGraphData }) {
  const [selection, setSelection] = useState<Selection>(null);

  const roles = data.roles;
  const edges = data.edges;

  const maxDuration = useMemo(
    () => Math.max(0, ...roles.map((r) => r.duration_seconds)),
    [roles],
  );
  const maxWeight = useMemo(() => Math.max(0, ...edges.map((e) => e.weight)), [edges]);

  const selectedRole = selection?.kind === 'role' ? selection.node : null;
  const selectedEdge = selection?.kind === 'edge' ? selection.edge : null;
  const isSelectedRole = (id: string) => selectedRole?.id === id;
  const isSelectedEdge = (e: CollabEdge) =>
    !!selectedEdge && selectedEdge.from === e.from && selectedEdge.to === e.to;

  return (
    <div>
      <svg
        viewBox="0 0 1440 620"
        style={{ width: '100%', display: 'block', background: `radial-gradient(900px 420px at 50% 0%, rgba(59, 110, 165, 0.18), transparent), ${BG}`, borderRadius: 12 }}
        role="img"
        aria-label="跨项目角色协作图谱"
      >
        <defs>
          {/* 箭头随 strokeWidth 缩放（markerUnits 缺省），边宽即方向强弱 */}
          <marker id="cg-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="4.5" markerHeight="4.5" orient="auto-start-reverse">
            <path d="M 0 0 L 10 5 L 0 10 z" fill={EDGE_STROKE} />
          </marker>
          <marker id="cg-arrow-active" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="4.5" markerHeight="4.5" orient="auto-start-reverse">
            <path d="M 0 0 L 10 5 L 0 10 z" fill={EDGE_STROKE_ACTIVE} />
          </marker>
        </defs>

        {/* 边层（先画边后画节点，节点盖住线端） */}
        {edges.map((e) => {
          const a = ROLE_POS[e.from];
          const b = ROLE_POS[e.to];
          if (!a || !b) return null;
          const { x1, y1, x2, y2 } = trimmedLine(a, 24, b, 24);
          const active = isSelectedEdge(e);
          return (
            <g key={`${e.from}->${e.to}`} onClick={() => setSelection({ kind: 'edge', edge: e })} style={{ cursor: 'pointer' }}>
              <line
                x1={x1}
                y1={y1}
                x2={x2}
                y2={y2}
                stroke={active ? EDGE_STROKE_ACTIVE : EDGE_STROKE}
                strokeWidth={edgeWidth(e.weight, maxWeight)}
                markerEnd={active ? 'url(#cg-arrow-active)' : 'url(#cg-arrow)'}
              />
              {/* 加宽透明命中区，便于点击细边 */}
              <line x1={x1} y1={y1} x2={x2} y2={y2} stroke="transparent" strokeWidth={16} />
              <text
                x={(x1 + x2) / 2}
                y={(y1 + y2) / 2 - 6}
                textAnchor="middle"
                fontSize={12}
                fill={active ? EDGE_STROKE_ACTIVE : TEXT_SUB}
                style={{ pointerEvents: 'none', userSelect: 'none' }}
              >
                ×{e.weight}
              </text>
            </g>
          );
        })}

        {/* 节点层（固定就位） */}
        {roles.map((r) => {
          const pos = ROLE_POS[r.id];
          if (!pos) return null;
          const radius = roleRadius(r.duration_seconds, maxDuration);
          const selected = isSelectedRole(r.id);
          return (
            <g
              key={r.id}
              onClick={() => setSelection({ kind: 'role', node: r })}
              style={{ cursor: 'pointer' }}
            >
              {r.in_flight && (
                <circle cx={pos.x} cy={pos.y} r={radius + 6} fill="none" stroke={INFLIGHT_STROKE} strokeWidth={2}>
                  <animate attributeName="r" values={`${radius + 2};${radius + 14};${radius + 2}`} dur="1.8s" repeatCount="indefinite" />
                  <animate attributeName="opacity" values="0.9;0.15;0.9" dur="1.8s" repeatCount="indefinite" />
                </circle>
              )}
              <circle
                cx={pos.x}
                cy={pos.y}
                r={radius}
                fill={NODE_FILL}
                stroke={r.in_flight ? INFLIGHT_STROKE : NODE_STROKE}
                strokeWidth={selected ? 3 : 1.5}
              />
              <text x={pos.x} y={pos.y + 5} textAnchor="middle" fontSize={14} fontWeight={700} fill={TEXT_MAIN} style={{ pointerEvents: 'none', userSelect: 'none' }}>
                {r.run_count}
              </text>
              <text x={pos.x} y={pos.y + radius + 20} textAnchor="middle" fontSize={15} fontWeight={700} fill={TEXT_MAIN} style={{ pointerEvents: 'none', userSelect: 'none' }}>
                {r.label}
              </text>
              <text x={pos.x} y={pos.y + radius + 38} textAnchor="middle" fontSize={11} fill={TEXT_SUB} style={{ pointerEvents: 'none', userSelect: 'none' }}>
                {r.run_count} run · {fmtCost(r.cost_usd)} · {fmtDuration(r.duration_seconds)}
                {r.in_flight ? ` · 在飞 ${r.running}` : ''}
              </text>
            </g>
          );
        })}
      </svg>

      <Drawer
        title={
          selectedRole
            ? `角色下钻：${selectedRole.label}`
            : selectedEdge
              ? `交接下钻：${selectedEdge.from} → ${selectedEdge.to}（${selectedEdge.weight} 次）`
              : ''
        }
        open={selection !== null}
        onClose={() => setSelection(null)}
        width={720}
        destroyOnClose
      >
        {selectedRole && (
          <>
            <div style={{ marginBottom: 12, color: TEXT_SUB }}>
              累计 {selectedRole.run_count} run · 成本 {fmtCost(selectedRole.cost_usd)} · 时长{' '}
              {fmtDuration(selectedRole.duration_seconds)}
              {selectedRole.in_flight ? ` · 在飞 ${selectedRole.running}` : ''}
            </div>
            <DrilldownTable entries={selectedRole.recent_runs} />
          </>
        )}
        {selectedEdge && <DrilldownTable entries={selectedEdge.recent_runs} />}
      </Drawer>
    </div>
  );
}
