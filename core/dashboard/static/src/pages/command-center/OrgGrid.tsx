// OrgGrid.tsx — 指挥中心「组织总览」屏（add-command-center 4.1）。
//
// 部门分区标题 + 车道卡（花名册全量出卡，零 run 车道可见；花名册外观测
// lane 落「其他」分区——后端单点派生，本屏零推导）。卡片字段：状态徽标
// （working 绿点/idle 灰点，纯静态无动画）/今日 run/7 日成功率/14 日静态
// 柱点 sparkline/成本/最近活动时间。汇报线为静态 SVG 细线一次性渲染
// （禁动画——specs「静态渲染红线」）。working 且可归属 SPEC 的卡点击跳
// /projects/:name/:spec（不可得禁用点击）。

import { history } from '@umijs/max';
import { Alert } from 'antd';
import { commandCenterOrg } from '@/services/dashboard';
import type { CommandCenterLaneCard, CommandCenterOrg } from '@/services/dashboard';
import { useScreenResource } from './useScreen';
import { ScreenErrorPlaceholder, ScreenLoading } from './ScreenStates';
import {
  BG,
  PANEL_BORDER,
  TEXT_MAIN,
  TEXT_SUB,
  fmtRate,
  fmtShortTs,
  fmtUsd,
  laneBadge,
  laneLabel,
  sparklineHeights,
} from './shared';

// 静态汇报线 SVG 布局参数（固定坐标，节点按分区列 × 区内行定位）
const EDGE_NODE_R = 5;
const EDGE_COL_W = 150;
const EDGE_ROW_H = 30;
const EDGE_PAD_X = 24;
const EDGE_PAD_Y = 18;

/** 汇报线静态 SVG：节点=花名册车道（按分区列布局），细线=EDGES 常量
 * （响应下发冻结结构）。一次渲染零动画属性（红线：无 CSS animation/
 * transition/SMIL）。 */
function ReportingLines({ org }: { org: CommandCenterOrg }) {
  // 节点坐标：分区序（响应 zones 固定序）× 区内车道序
  const pos = new Map<string, { x: number; y: number }>();
  let maxRows = 0;
  org.zones.forEach((z, zi) => {
    maxRows = Math.max(maxRows, z.cards.length);
    z.cards.forEach((c, ci) => {
      pos.set(c.lane, { x: EDGE_PAD_X + zi * EDGE_COL_W, y: EDGE_PAD_Y + ci * EDGE_ROW_H });
    });
  });
  // 末列追加标签预留宽度：text 自圆心右侧 10px 起排，无预留会被
  // SVG 默认 overflow hidden 裁掉末列车道名。
  const width =
    EDGE_PAD_X * 2 + Math.max(0, org.zones.length - 1) * EDGE_COL_W + 60;
  const height = EDGE_PAD_Y * 2 + Math.max(0, maxRows - 1) * EDGE_ROW_H;
  if (!org.zones.length || width <= 0 || height <= 0) return null;
  return (
    <div
      style={{
        border: `1px solid ${PANEL_BORDER}`,
        borderRadius: 8,
        padding: '10px 8px 4px',
        marginBottom: 14,
      }}
    >
      <div style={{ fontSize: 12, color: TEXT_SUB, marginBottom: 4 }}>汇报线（静态）</div>
      <svg
        width={width}
        height={height + 14}
        viewBox={`0 0 ${width} ${height + 14}`}
        role="img"
        aria-label="汇报线"
      >
        {/* 边先画（衬底），节点后画 */}
        {org.edges.map((e) => {
          const a = pos.get(e.from);
          const b = pos.get(e.to);
          if (!a || !b) return null;
          return (
            <line
              key={`${e.from}->${e.to}`}
              x1={a.x + EDGE_NODE_R}
              y1={a.y + 8}
              x2={b.x - EDGE_NODE_R}
              y2={b.y + 8}
              stroke={PANEL_BORDER}
              strokeWidth={1}
            />
          );
        })}
        {org.zones.map((z) => {
          const p = pos.get(z.cards[0]?.lane ?? '');
          if (!p) return null;
          return (
            <text
              key={`zone-${z.zone}`}
              x={p.x}
              y={height + 8}
              textAnchor="middle"
              fontSize={11}
              fill={TEXT_SUB}
            >
              {z.zone}
            </text>
          );
        })}
        {[...pos.entries()].map(([lane, p]) => (
          <g key={`node-${lane}`}>
            <circle cx={p.x} cy={p.y + 8} r={EDGE_NODE_R} fill={TEXT_MAIN} />
            <text x={p.x + 10} y={p.y + 12} fontSize={11} fill={TEXT_MAIN}>
              {laneLabel(lane)}
            </text>
          </g>
        ))}
      </svg>
    </div>
  );
}

/** 14 日活动柱点 sparkline：静态 SVG 逐日矩形（旧→新），无动画属性。 */
function ActivitySparkline({ activity }: { activity: number[] }) {
  const heights = sparklineHeights(activity);
  const barW = 5;
  const gap = 2;
  const h = 20;
  const width = activity.length * (barW + gap);
  return (
    <svg
      width={width}
      height={h}
      viewBox={`0 0 ${width} ${h}`}
      role="img"
      aria-label="近 14 日活动"
      style={{ display: 'block' }}
    >
      {heights.map((hpct, i) => {
        const bh = Math.max(hpct > 0 ? 2 : 1, Math.round((hpct / 100) * h));
        return (
          <rect
            key={i}
            x={i * (barW + gap)}
            y={h - bh}
            width={barW}
            height={bh}
            fill={hpct > 0 ? '#40a9ff' : PANEL_BORDER}
          />
        );
      })}
    </svg>
  );
}

/** 车道卡：working 且可归属 SPEC 可点击钻取 /projects/:name/:spec。 */
function LaneCard({ card }: { card: CommandCenterLaneCard }) {
  const badge = laneBadge(card.status);
  const clickable = card.status === 'working' && !!card.attributable;
  const open = () => {
    if (clickable && card.attributable) {
      history.push(
        `/projects/${encodeURIComponent(card.attributable.project)}/${encodeURIComponent(card.attributable.spec)}`,
      );
    }
  };
  return (
    <div
      onClick={clickable ? open : undefined}
      style={{
        border: `1px solid ${PANEL_BORDER}`,
        borderRadius: 8,
        padding: '10px 12px',
        background: 'rgba(10, 30, 56, 0.55)',
        cursor: clickable ? 'pointer' : 'default',
        display: 'flex',
        flexDirection: 'column',
        gap: 8,
        minWidth: 190,
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8 }}>
        <span style={{ fontWeight: 600 }}>{laneLabel(card.lane)}</span>
        <span style={{ fontSize: 12, color: badge.color, display: 'inline-flex', alignItems: 'center', gap: 4 }}>
          <span
            style={{
              width: 6,
              height: 6,
              borderRadius: 3,
              background: badge.color,
              display: 'inline-block',
            }}
          />
          {badge.text}
        </span>
      </div>
      <div style={{ fontSize: 12, color: TEXT_SUB, display: 'flex', flexWrap: 'wrap', gap: '2px 12px' }}>
        <span>今日 run {card.runs_today}</span>
        <span>7 日成功率 {fmtRate(card.success_rate_7d)}</span>
        <span>成本 {fmtUsd(card.cost_7d)}</span>
      </div>
      <ActivitySparkline activity={card.activity_14d} />
      <div style={{ fontSize: 12, color: TEXT_SUB }}>
        最近活动 {fmtShortTs(card.last_activity_ts)}
        {clickable && card.attributable ? (
          <span style={{ color: TEXT_MAIN }}> · {card.attributable.spec}</span>
        ) : null}
      </div>
    </div>
  );
}

export default function OrgGrid({ active }: { active: boolean }) {
  const { data, error, loading, retry } = useScreenResource<CommandCenterOrg>(
    () => commandCenterOrg(),
    active,
  );
  if (error && !data) return <ScreenErrorPlaceholder error={error} onRetry={retry} />;
  if (!data) return <ScreenLoading hint="组织网格加载中" />;
  return (
    <div>
      {/* 后台刷新失败保留旧数据（静默轮询恢复），内联提示不阻塞视图 */}
      {error ? (
        <Alert style={{ marginBottom: 12 }} type="warning" showIcon message={`组织网格刷新失败：${error}`} />
      ) : null}
      <ReportingLines org={data} />
      {data.zones.map((z) => (
        <section key={z.zone} style={{ marginBottom: 18 }}>
          <div style={{ fontSize: 13, fontWeight: 600, color: TEXT_SUB, marginBottom: 8 }}>
            {z.zone}
          </div>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 10 }}>
            {z.cards.map((c) => (
              <LaneCard key={c.lane} card={c} />
            ))}
          </div>
        </section>
      ))}
    </div>
  );
}
