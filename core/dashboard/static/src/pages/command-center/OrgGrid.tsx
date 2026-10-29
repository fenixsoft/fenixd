// OrgGrid.tsx — 指挥中心「组织总览」屏（add-command-center 4.1；2026-10-28
// LaneCard 按设计文档 docs/superpowers/specs/2026-10-28-agent-card-redesign-design.md
// 重设计，参照 ability.ai/trinity 卡片结构；同日用户追加：图标恒彩、五线
// 重划（后端 ROSTER 单源）、分区纵向卡片列且相对面板居中、产品团队汇总卡
// +五条连接线、原「汇报线（静态）」卡取消）。
//
// 顶部产品团队汇总卡（需求数量/Agent 运行·今日/总成本·7 日，数据源为后端
// org 响应 summary 块）+ 车道分区纵列（花名册全量出卡，零 run 车道可见；
// 花名册外观测 lane 落「其他」分区——后端单点派生，本屏零推导）。卡片五段
// 结构：图标徽章+车道名/状态徽标+lane id / 活动行（working+attributable 显
// spec 名、working 无归属显「执行中」、idle 显「待命 · 等待信号」）/ 三格
// 大数值指标（今日 run/7 日成功率/成本·7 日，null→「—」红线）/ 14 日静态
// 柱点 sparkline+最近活动页脚。图标用既有依赖 @ant-design/icons（lane→组件
// 映射置本文件——shared.ts 禁 antd import 的 node --test 直载红线），恒彩
// 蓝系（不随状态变灰）。连接线为静态 SVG 一次性量取渲染（禁动画——specs
// 「静态渲染红线」，本卡同样无 animation/transition，hover 纯色切换）。
// working 且可归属 SPEC 的卡点击跳 /projects/:name/:spec（不可得禁用点击）。
//
// 2026-10-29 用户追加三项：①活动行去 ▶ 前缀；②在飞归属列表化（后端
// attributables，started 降序、同 spec 去重取最新）支持多 spec 并行——活动
// 行限高（≈3 行）手动滚动（.cmdcenter-lanescroll 深色滚动条，禁动画红线），
// 整卡钻取 /projects/:name/:spec 取消，改为点击 spec 名开运行记录弹窗
// （复用 spec 时间轴「查看运行记录」的 RunRecordModal；harness 元数据不
// 带，品牌走回退链缺省中性「AI Assistant」）；③团队卡与五线间距
// 14→24px、连线描边加深加粗（LINK_STROKE + 1.5）。

import { useEffect, useLayoutEffect, useRef, useState } from 'react';
import { Alert } from 'antd';
import {
  BulbOutlined,
  BugOutlined,
  CheckCircleOutlined,
  CodeOutlined,
  CompassOutlined,
  ControlOutlined,
  DiffOutlined,
  ExperimentOutlined,
  EyeOutlined,
  FileTextOutlined,
  FileUnknownOutlined,
  RiseOutlined,
  SafetyCertificateOutlined,
  SettingOutlined,
  SolutionOutlined,
} from '@ant-design/icons';
import { commandCenterOrg } from '@/services/dashboard';
import type { CommandCenterLaneCard, CommandCenterOrg } from '@/services/dashboard';
import RunRecordModal from '@/pages/projects/components/RunRecordModal';
import { useScreenResource } from './useScreen';
import { ScreenErrorPlaceholder, ScreenLoading } from './ScreenStates';
import {
  ACCENT,
  AVATAR_BG,
  AVATAR_BORDER,
  CARD_BG,
  FONT_MONO,
  GREEN,
  GREEN_DIM_BG,
  GREEN_DIM_BG_HOVER,
  LINK_STROKE,
  METRIC_DIVIDER,
  PANEL_BORDER,
  REST_BORDER,
  TEXT_SUB,
  TimeWindow,
  activityLineState,
  fmtDurationSeconds,
  fmtMetric,
  fmtRate,
  fmtShortTs,
  fmtUsd,
  laneBadge,
  laneLabel,
  sparklineHeights,
  windowLabels,
} from './shared';
import type { AttributableRun } from './shared';

// 车道图标映射（@ant-design/icons 6.3.2 均已核实存在；花名册外未知 lane
// 回退 FileUnknownOutlined）。置本文件原因见文件头注。评审族四图标按用户
// 定稿差异化（Solution 会签/Diff 代码差异/SafetyCertificate 验证盾/Control
// 裁决台），避免同款文档风四连。
const LANE_ICONS: Record<string, typeof CodeOutlined> = {
  planner: CompassOutlined,
  'spec-review': SolutionOutlined,
  'planner-plan': BulbOutlined,
  'planner-judge': SafetyCertificateOutlined,
  implementer: CodeOutlined,
  'code-fix': BugOutlined,
  verifier: CheckCircleOutlined,
  judge: ControlOutlined,
  'code-review': DiffOutlined,
  'self-review': EyeOutlined,
  administrator: SettingOutlined,
  evolution: RiseOutlined,
  ocr: FileTextOutlined,
};

/** 14 日活动柱点 sparkline：静态 SVG 逐日矩形（旧→新），无动画属性。 */
function ActivitySparkline({ activity }: { activity: number[] }) {
  const heights = sparklineHeights(activity);
  const barW = 5;
  const gap = 2;
  const h = 18;
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
            fill={hpct > 0 ? ACCENT : PANEL_BORDER}
          />
        );
      })}
    </svg>
  );
}

/** 三格指标单元格：数值大字（tabular-nums）+ 标签小字；divided 加左竖分隔；
 * dim 用于 idle 卡整体降调（数值走副色，同定稿原型）；center 用于产品团队
 * 卡（2026-10-28 用户定稿内容居中）。 */
function MetricCell({
  value,
  label,
  divided,
  dim,
  center,
}: {
  value: string;
  label: string;
  divided?: boolean;
  dim?: boolean;
  center?: boolean;
}) {
  return (
    <div
      style={{
        flex: 1,
        minWidth: 0,
        textAlign: center ? 'center' : undefined,
        ...(divided
          ? { borderLeft: `1px solid ${METRIC_DIVIDER}`, paddingLeft: 12 }
          : {}),
      }}
    >
      <div
        style={{
          fontSize: 18,
          fontWeight: 600,
          fontVariantNumeric: 'tabular-nums',
          lineHeight: 1.15,
          color: dim ? TEXT_SUB : undefined,
        }}
      >
        {value}
      </div>
      <div style={{ fontSize: 11.5, color: TEXT_SUB, marginTop: 3, whiteSpace: 'nowrap' }}>{label}</div>
    </div>
  );
}

/** 车道卡（2026-10-28 重设计五段结构，定稿原型
 * .history/agent-card-prototype.html）：2026-10-29 整卡钻取取消，点击目标
 * 收敛到活动行 spec 条目（onOpenRun 开运行记录弹窗）。三格指标标签随时间
 * 窗变（windowLabels）。静态红线：无 animation/transition，hover 纯色切换。 */
function LaneCard({
  card,
  win,
  onOpenRun,
}: {
  card: CommandCenterLaneCard;
  win: TimeWindow;
  onOpenRun: (run: AttributableRun) => void;
}) {
  const L = windowLabels(win);
  const [hoverRun, setHoverRun] = useState<string | null>(null);
  const badge = laneBadge(card.status);
  const activity = activityLineState(card);
  const working = card.status === 'working';
  const IconComp = LANE_ICONS[card.lane] ?? FileUnknownOutlined;
  return (
    <div
      style={{
        width: 310,
        border: `1px solid ${PANEL_BORDER}`,
        borderRadius: 10,
        padding: '13px 14px 11px',
        background: CARD_BG,
        display: 'flex',
        flexDirection: 'column',
        gap: 10,
      }}
    >
      {/* 头行：图标徽章 + 车道名/状态徽标 + lane id */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
        <div
          style={{
            width: 38,
            height: 38,
            borderRadius: 10,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            flexShrink: 0,
            // 图标恒彩（2026-10-28 定稿）：不随 working/idle 变灰
            color: ACCENT,
            background: AVATAR_BG,
            border: `1px solid ${AVATAR_BORDER}`,
          }}
        >
          <IconComp style={{ fontSize: 18 }} />
        </div>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8 }}>
            <span style={{ fontSize: 15, fontWeight: 600 }}>{laneLabel(card.lane)}</span>
            <span
              style={{
                fontSize: 12,
                color: badge.color,
                display: 'inline-flex',
                alignItems: 'center',
                gap: 5,
                flexShrink: 0,
              }}
            >
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
          <div style={{ fontSize: 12, color: TEXT_SUB, marginTop: 2, letterSpacing: 0.3, fontFamily: FONT_MONO }}>
            {card.lane}
          </div>
        </div>
      </div>
      {/* 活动行（灵魂）：在飞 spec 列表（点击开运行记录）/ 执行中 / 待命虚线框。
          多 spec 并行时限高 ≈3 行手动滚动（.cmdcenter-lanescroll 深色滚动条；
          静态红线无动画）。整卡点击已取消（2026-10-29），点击目标收敛到
          spec 条目自身。 */}
      {activity.kind === 'rest' ? (
        <div
          style={{
            fontSize: 12,
            color: TEXT_SUB,
            minHeight: 19,
            display: 'flex',
            alignItems: 'center',
            padding: '5px 8px',
            borderRadius: 6,
            border: `1px dashed ${REST_BORDER}`,
          }}
        >
          待命 · 等待信号
        </div>
      ) : activity.kind === 'running' ? (
        <div
          style={{
            fontSize: 13,
            color: GREEN,
            background: GREEN_DIM_BG,
            minHeight: 19,
            display: 'flex',
            alignItems: 'center',
            padding: '5px 8px',
            borderRadius: 6,
          }}
        >
          执行中
        </div>
      ) : (
        <div
          className="cmdcenter-lanescroll"
          style={{
            background: GREEN_DIM_BG,
            borderRadius: 6,
            padding: '4px 5px',
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'stretch',
            gap: 2,
            maxHeight: 75,
            overflowY: 'auto',
          }}
        >
          {activity.items.map((it) => {
            const key = `${it.project}/${it.spec}`;
            // run_id 空 = 旧后端兜底形态（仅显名字，开不了运行记录）
            const clickable = !!it.run_id;
            return (
              <div
                key={key}
                title={`${it.project}/${it.spec}`}
                onClick={clickable ? () => onOpenRun(it) : undefined}
                onMouseEnter={clickable ? () => setHoverRun(key) : undefined}
                onMouseLeave={clickable ? () => setHoverRun(null) : undefined}
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  minHeight: 19,
                  padding: '1px 5px',
                  borderRadius: 4,
                  cursor: clickable ? 'pointer' : 'default',
                  background: clickable && hoverRun === key ? GREEN_DIM_BG_HOVER : 'transparent',
                }}
              >
                <span
                  style={{
                    flex: 1,
                    minWidth: 0,
                    color: ACCENT,
                    fontFamily: FONT_MONO,
                    fontSize: 12.5,
                    whiteSpace: 'nowrap',
                    overflow: 'hidden',
                    textOverflow: 'ellipsis',
                  }}
                >
                  {it.spec}
                </span>
              </div>
            );
          })}
        </div>
      )}
      {/* 三格指标：null→「—」（红线），0 保留；idle 卡降调；窗口口径标签 */}
      <div style={{ display: 'flex' }}>
        <MetricCell value={fmtMetric(card.runs)} label={L.run} dim={!working} />
        <MetricCell value={fmtRate(card.success_rate)} label={L.rate} divided dim={!working} />
        <MetricCell value={fmtUsd(card.cost)} label={L.cost} divided dim={!working} />
      </div>
      {/* 页脚：14 日 sparkline + 最近活动时间 */}
      <div style={{ display: 'flex', alignItems: 'flex-end', justifyContent: 'space-between', gap: 10, paddingTop: 2 }}>
        <ActivitySparkline activity={card.activity_14d} />
        <span style={{ fontSize: 12, color: TEXT_SUB, whiteSpace: 'nowrap' }}>
          最近活动 {fmtShortTs(card.last_activity_ts)}
        </span>
      </div>
    </div>
  );
}

export default function OrgGrid({
  active,
  project,
  win,
  onProjects,
}: {
  active: boolean;
  /** 项目筛选：''=全部项目（服务端缺省聚合范围） */
  project: string;
  /** 时间窗（today/7d/all），约束三格指标与团队汇总口径 */
  win: TimeWindow;
  /** 项目全集上报（供页签右侧项目下拉），数据变化时回调一次 */
  onProjects?: (projects: string[]) => void;
}) {
  const { data, error, loading, retry } = useScreenResource<CommandCenterOrg>(
    () => commandCenterOrg(project || undefined, win),
    active,
    // 筛选变化即时重拉（同 PipelineBoard refreshKey 口径）
    `${project}|${win}`,
  );
  // 运行记录弹窗（2026-10-29 多 spec 并行）：点击活动行 spec 名打开，复用
  // spec 时间轴「查看运行记录」的 RunRecordModal（harness 元数据不带，品牌
  // 回退链缺省中性「AI Assistant」）。state 置本屏——轮询换 data 引用不
  // 卸载组件，打开状态在刷新间保持。
  const [runView, setRunView] = useState<AttributableRun | null>(null);

  // 项目全集上报给宿主（页签右侧下拉数据源）
  useEffect(() => {
    if (data?.projects) onProjects?.(data.projects);
  }, [data, onProjects]);
  const containerRef = useRef<HTMLDivElement>(null);
  const teamRef = useRef<HTMLDivElement>(null);
  const zoneRefs = useRef<(HTMLElement | null)[]>([]);
  const [links, setLinks] = useState<{ x1: number; y1: number; x2: number; y2: number }[]>([]);

  // 产品团队卡 → 五线连接线：静态一次性量取（禁动画红线，无 transition/
  // animation；数据每次刷新（轮询换 data 引用）与窗口 resize 时重量）。
  // hooks 置于早退分支前（rules of hooks）；量取在 layout effect 内、
  // setLinks 触发的重渲染不再进本 effect（deps=[data]），无回环。
  useLayoutEffect(() => {
    if (!data) return;
    const measure = () => {
      const cont = containerRef.current;
      const team = teamRef.current;
      if (!cont || !team) return;
      const cb = cont.getBoundingClientRect();
      const tb = team.getBoundingClientRect();
      const x1 = tb.left + tb.width / 2 - cb.left;
      const y1 = tb.bottom - cb.top;
      setLinks(
        zoneRefs.current
          .filter((el): el is HTMLElement => !!el)
          .map((el) => {
            const b = el.getBoundingClientRect();
            return { x1, y1, x2: b.left + b.width / 2 - cb.left, y2: b.top - cb.top };
          }),
      );
    };
    measure();
    window.addEventListener('resize', measure);
    return () => window.removeEventListener('resize', measure);
  }, [data]);

  if (error && !data) return <ScreenErrorPlaceholder error={error} onRetry={retry} />;
  if (!data) return <ScreenLoading hint="组织网格加载中" />;
  return (
    <div>
      {/* 后台刷新失败保留旧数据（静默轮询恢复），内联提示不阻塞视图 */}
      {error ? (
        <Alert style={{ marginBottom: 12 }} type="warning" showIcon message={`组织网格刷新失败：${error}`} />
      ) : null}
      {/* 双向滚动容器（2026-10-28 定稿：五线不换行，宽度不足出横向滚动条；
          定高=视口减页签区，纵向也走本容器——两条滚动条常驻视口边缘可见，
          不再藏在内容底部折叠线之下；内容层 containerRef 随滚动整体平移，
          连接线坐标层与卡片同源不脱节） */}
      <div
        // 78 = 页面 padding-top(8) + 页签条高(70)（页签条被右侧下拉选择器
        // 撑高；页签间距走 padding-top 防止 margin 塌陷把整页推低）
        style={{ height: 'calc(100vh - 78px)', overflow: 'auto' }}
        className="cmdcenter-hscroll"
      >
        <div
          ref={containerRef}
          style={{ position: 'relative', width: 'fit-content', minWidth: '100%' }}
        >
          {/* 产品团队汇总卡（2026-10-28 追加；三格指标口径见后端 summary 派生） */}
          <div
            ref={teamRef}
            style={{
              position: 'relative',
              width: 'fit-content',
              minWidth: 560,
              // 下间距即连接线垂直段长度（2026-10-29 用户定稿 14→24px：原
              // 折线垂直段太短）
              margin: '0 auto 24px',
              border: `1px solid ${PANEL_BORDER}`,
              borderRadius: 10,
              background: CARD_BG,
              padding: '12px 18px 10px',
            }}
          >
            <div style={{ fontSize: 15, fontWeight: 600, marginBottom: 8, textAlign: 'center' }}>
              {project ? `${project} 产品团队` : '全部团队'}
            </div>
            <div style={{ display: 'flex', gap: 20 }}>
              <MetricCell
                value={fmtMetric(data.summary?.spec_count)}
                label={windowLabels(win).teamSpecs}
                center
              />
              <MetricCell
                value={fmtMetric(data.summary?.runs_total)}
                label={windowLabels(win).teamRuns}
                divided
                center
              />
              <MetricCell
                value={fmtDurationSeconds(data.summary?.duration_total)}
                label={windowLabels(win).teamDuration}
                divided
                center
              />
              <MetricCell
                value={fmtUsd(data.summary?.cost_total)}
                label={windowLabels(win).teamCost}
                divided
                center
              />
            </div>
          </div>
          {/* 连接线静态 SVG（衬底；卡片定位元素后绘自然覆盖其上）。折线形：
              自团队卡底部中点垂直下行至中位线，水平横移至目标列中点，再
              垂直接入列顶（2026-10-28 用户定稿改折线连接）。描边为半透明
              色——逐条画整段折线会让共享段（干道/水平母线）叠画多层而
              加深受色（2026-10-29 用户取证「颜色不一致」），故按几何去重
              拆三组各画一次：干道一条 + 母线一条 + 各列垂尾，色值恒匀。
              2026-10-29 用户定稿加深加粗（LINK_STROKE + 1.5）。 */}
          {links.length ? (
            <svg
              width="100%"
              height="100%"
              style={{ position: 'absolute', inset: 0, pointerEvents: 'none' }}
              role="img"
              aria-label="产品团队与各线连接"
            >
              {(() => {
                const { x1, y1 } = links[0];
                const my = (y1 + links[0].y2) / 2;
                const xs = links.map((l) => l.x2);
                const left = Math.min(...xs, x1);
                const right = Math.max(...xs, x1);
                return (
                  <g stroke={LINK_STROKE} strokeWidth={1.5} fill="none">
                    <path d={`M${x1} ${y1} L${x1} ${my}`} />
                    <path d={`M${left} ${my} L${right} ${my}`} />
                    {links.map((l, i) => (
                      <path key={i} d={`M${l.x2} ${my} L${l.x2} ${l.y2}`} />
                    ))}
                  </g>
                );
              })()}
            </svg>
          ) : null}
          {/* 分区纵列（2026-10-28 定稿：各线纵向卡片列、单行排布不换行；
              行自身 shrink-to-fit + margin auto 整组居中——宽度富余时居中、
              溢出时 auto margin 归零转起排，规避 justify-content:center 的
              溢出左缘不可达陷阱，由外层横向滚动条兜底） */}
          <div
            style={{
              position: 'relative',
              display: 'flex',
              alignItems: 'flex-start',
              flexWrap: 'nowrap',
              gap: 14,
              width: 'fit-content',
              margin: '0 auto',
            }}
          >
            {data.zones.map((z, i) => (
              <section
                key={z.zone}
                ref={(el) => {
                  zoneRefs.current[i] = el;
                }}
              >
                <div
                  style={{
                    fontSize: 13,
                    fontWeight: 600,
                    color: TEXT_SUB,
                    marginBottom: 8,
                    textAlign: 'center',
                  }}
                >
                  {z.zone}
                </div>
                <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
                  {z.cards.map((c) => (
                    <LaneCard key={c.lane} card={c} win={win} onOpenRun={setRunView} />
                  ))}
                </div>
              </section>
            ))}
          </div>
        </div>
      </div>
      {/* 运行记录弹窗（spec 时间轴「查看运行记录」同款最大化窗口） */}
      <RunRecordModal
        runId={runView?.run_id ?? null}
        project={runView?.project ?? ''}
        onClose={() => setRunView(null)}
      />
    </div>
  );
}
