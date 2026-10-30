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
import { Alert, Input, Popover } from 'antd';
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
import { commandCenterOrg, commandCenterSpecRuns } from '@/services/dashboard';
import type {
  CommandCenterLaneCard,
  CommandCenterOrg,
  CommandCenterSpecRuns,
} from '@/services/dashboard';
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
  SPEC_CELL_HOVER_BG,
  SPEC_CELL_SELECTED_BG,
  TEXT_SUB,
  TimeWindow,
  activityLineState,
  filterSpecEntries,
  fmtDurationSeconds,
  fmtMetric,
  fmtRate,
  fmtShortTs,
  fmtUsd,
  isSpecInList,
  laneBadge,
  laneLabel,
  laneSpecRounds,
  sparklineHeights,
  specEntryLabel,
  specRoundLabel,
  windowLabels,
} from './shared';
import type { AttributableRun, SpecEntry, SpecRound } from './shared';

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
 * 卡（2026-10-28 用户定稿内容居中）。clickHint 用于需求数量格可点击态
 * （add-command-center-spec-view 4.2：值下 dotted 下划线轻量视觉暗示 +
 * 选中态值提亮为 ACCENT）。 */
function MetricCell({
  value,
  label,
  divided,
  dim,
  center,
  clickHint,
  selected,
}: {
  value: string;
  label: string;
  divided?: boolean;
  dim?: boolean;
  center?: boolean;
  clickHint?: boolean;
  selected?: boolean;
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
          color: selected ? ACCENT : dim ? TEXT_SUB : undefined,
          ...(clickHint
            ? {
                display: 'inline-block',
                borderBottom: `1px dotted ${selected ? ACCENT : TEXT_SUB}`,
                paddingBottom: 1,
              }
            : {}),
        }}
      >
        {value}
      </div>
      <div style={{ fontSize: 11.5, color: TEXT_SUB, marginTop: 3, whiteSpace: 'nowrap' }}>{label}</div>
    </div>
  );
}

/** spec 选择下拉内容（add-command-center-spec-view 4.2）：搜索框本地过滤
 * + 限高滚动列表（.cmdcenter-lanescroll 深色滚动条；静态红线无动画）。
 * 条目排序由后端 summary.specs 下发（created 新→旧）；全部项目视图条目
 * `project/spec` 消歧、单项目只显 spec 名（shared.specEntryLabel）。 */
function SpecPicker({
  entries,
  allProjects,
  onPick,
}: {
  entries: SpecEntry[];
  allProjects: boolean;
  onPick: (entry: SpecEntry) => void;
}) {
  const [query, setQuery] = useState('');
  const [hoverKey, setHoverKey] = useState<string | null>(null);
  const filtered = filterSpecEntries(entries, query);
  return (
    <div style={{ width: 264 }}>
      <Input
        size="small"
        placeholder="搜索 SPEC"
        allowClear
        value={query}
        onChange={(e) => setQuery(e.target.value)}
      />
      <div
        className="cmdcenter-lanescroll"
        style={{
          marginTop: 8,
          maxHeight: 240,
          overflowY: 'auto',
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'stretch',
          gap: 2,
        }}
      >
        {filtered.length ? (
          filtered.map((e) => {
            const key = `${e.project}/${e.spec}`;
            return (
              <div
                key={key}
                title={key}
                onClick={() => onPick(e)}
                role="link"
                tabIndex={0}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') onPick(e);
                }}
                onMouseEnter={() => setHoverKey(key)}
                onMouseLeave={() => setHoverKey(null)}
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  minHeight: 24,
                  padding: '3px 8px',
                  borderRadius: 5,
                  cursor: 'pointer',
                  background: hoverKey === key ? GREEN_DIM_BG_HOVER : 'transparent',
                }}
              >
                <span
                  style={{
                    color: ACCENT,
                    fontFamily: FONT_MONO,
                    fontSize: 12.5,
                    whiteSpace: 'nowrap',
                    overflow: 'hidden',
                    textOverflow: 'ellipsis',
                  }}
                >
                  {specEntryLabel(e, allProjects)}
                </span>
              </div>
            );
          })
        ) : (
          <div style={{ fontSize: 12, color: TEXT_SUB, padding: '6px 8px' }}>
            当前时间窗内无活跃 SPEC
          </div>
        )}
      </div>
    </div>
  );
}

/** 车道卡（2026-10-28 重设计五段结构，定稿原型
 * .history/agent-card-prototype.html）：2026-10-29 整卡钻取取消，点击目标
 * 收敛到活动行 spec 条目（onOpenRun 开运行记录弹窗）。三格指标标签随时间
 * 窗变（windowLabels）。静态红线：无 animation/transition，hover 纯色切换。
 * 2026-10-30 spec 视图分支（add-command-center-spec-view 4.3）：specSel
 * 非空时活动区替换为该车道对该 SPEC 的轮次列表/未运行/加载占位——其余四段
 * （头行/三格指标/sparkline/页脚）保持实时口径不动。 */
function LaneCard({
  card,
  win,
  onOpenRun,
  specSel,
  specRounds,
}: {
  card: CommandCenterLaneCard;
  win: TimeWindow;
  onOpenRun: (run: AttributableRun) => void;
  /** spec 视图选中态（null=实时模式，走既有三分渲染） */
  specSel: { project: string; spec: string } | null;
  /** 该车道轮次（spec-runs 未到数据时为 null → 显「加载中」占位） */
  specRounds: SpecRound[] | null;
}) {
  const L = windowLabels(win);
  const [hoverRun, setHoverRun] = useState<string | null>(null);
  const [hoverRound, setHoverRound] = useState<string | null>(null);
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
      {/* 活动行（灵魂）：spec 视图选中时替换为轮次列表（add-command-center-
          spec-view 4.3：`spec名 · 第N轮` 最新在前、点击行开运行记录弹窗、
          在飞轮次照常入列可点开、run_id 缺失禁点兜底；无 run 显灰虚线框
          「未运行」；spec-runs 未到数据显「加载中」占位——均无动画）。
          实时模式保持既有三分：在飞 spec 列表（点击开运行记录）/ 执行中 /
          待命虚线框。多 spec 并行时限高 ≈3 行手动滚动（.cmdcenter-lanescroll
          深色滚动条；静态红线无动画）。整卡点击已取消（2026-10-29），点击
          目标收敛到 spec 条目自身。 */}
      {specSel ? (
        specRounds === null ? (
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
            加载中
          </div>
        ) : specRounds.length ? (
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
            {specRounds.map((r) => {
              // run_id 空 = 旧后端形态防御（保留行但禁点，零伪造红线）
              const clickable = !!r.run_id;
              const key = `${r.seq}-${r.run_id || 'na'}`;
              const openRun = clickable
                ? () =>
                    onOpenRun({
                      project: specSel.project,
                      spec: specSel.spec,
                      run_id: r.run_id,
                    })
                : undefined;
              return (
                <div
                  key={key}
                  title={`${r.seq} 轮 · ${fmtShortTs(r.started_ts)}`}
                  onClick={openRun}
                  // 键盘可达（对齐 PipelineBoard.PipelineCard 既有模式）：
                  // 可点行补 role+tabIndex+Enter；禁点行不进 tab 序
                  role={clickable ? 'button' : undefined}
                  tabIndex={clickable ? 0 : undefined}
                  onKeyDown={
                    openRun
                      ? (e) => {
                          if (e.key === 'Enter') openRun();
                        }
                      : undefined
                  }
                  onMouseEnter={clickable ? () => setHoverRound(key) : undefined}
                  onMouseLeave={clickable ? () => setHoverRound(null) : undefined}
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: 8,
                    minHeight: 19,
                    padding: '1px 5px',
                    borderRadius: 4,
                    cursor: clickable ? 'pointer' : 'default',
                    background:
                      clickable && hoverRound === key ? GREEN_DIM_BG_HOVER : 'transparent',
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
                    {specRoundLabel(specSel.spec, r.seq)}
                  </span>
                  <span style={{ fontSize: 11, color: TEXT_SUB, flexShrink: 0 }}>
                    {fmtShortTs(r.started_ts)}
                  </span>
                </div>
              );
            })}
          </div>
        ) : (
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
            未运行
          </div>
        )
      ) : activity.kind === 'rest' ? (
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
            const openRun = clickable ? () => onOpenRun(it) : undefined;
            return (
              <div
                key={key}
                title={`${it.project}/${it.spec}`}
                onClick={openRun}
                // 键盘可达（对齐 PipelineBoard.PipelineCard 既有模式）：
                // 可点行补 role+tabIndex+Enter；禁点行不进 tab 序
                role={clickable ? 'button' : undefined}
                tabIndex={clickable ? 0 : undefined}
                onKeyDown={
                  openRun
                    ? (e) => {
                        if (e.key === 'Enter') openRun();
                      }
                    : undefined
                }
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
  specView,
  onSpecViewChange,
}: {
  active: boolean;
  /** 项目筛选：''=全部项目（服务端缺省聚合范围） */
  project: string;
  /** 时间窗（today/7d/all），约束三格指标与团队汇总口径 */
  win: TimeWindow;
  /** 项目全集上报（供页签右侧项目下拉），数据变化时回调一次 */
  onProjects?: (projects: string[]) => void;
  /** spec 视图选中态（add-command-center-spec-view 4.1：宿主提升+深链 URL） */
  specView?: { project: string; spec: string } | null;
  /** 选中态回写宿主（置 null=退出，宿主同步清 URL 参数） */
  onSpecViewChange?: (v: { project: string; spec: string } | null) => void;
}) {
  const { data, error, retry } = useScreenResource<CommandCenterOrg>(
    () => commandCenterOrg(project || undefined, win),
    active,
    // 筛选变化即时重拉（同 PipelineBoard refreshKey 口径）
    `${project}|${win}`,
  );
  // spec 视图选中态（宿主提升；缺省 null 兼容无宿主直用场景）
  const specSel = specView ?? null;
  // 下拉名单数据源 = org 响应 summary.specs（缺键兜底视为空名单，旧后端/
  // 新前端混跑不异常——shared.isSpecInList 内部防御）
  const specsList = data?.summary?.specs;
  // 隐式退出（add-command-center-spec-view 4.1/隐式退出规则）：选中态下
  // org 数据到达后所选 (spec_project, spec) 不在当前名单（项目筛选 × 时间窗
  // 变化后）→ 自动退出；深链直达校验不过同此规则（清参数回实时模式）。
  // data 未到不判（首载/刷新中不误退）。
  useEffect(() => {
    if (!specSel || !data) return;
    if (!isSpecInList(specsList, specSel.project, specSel.spec)) {
      onSpecViewChange?.(null);
    }
  }, [specSel, data, specsList, onSpecViewChange]);
  // spec-runs 资源（add-command-center-spec-view 4.3）：走 useScreenResource
  // 既有口径——active=屏激活且选中，refreshKey=`project|win|spec`，60s 轮询
  // 与序号防乱序随既有 hook；失败保留上轮数据（屏级 Alert 既有模式）。
  const {
    data: specRuns,
    error: specRunsError,
  } = useScreenResource<CommandCenterSpecRuns>(
    () =>
      specSel
        ? commandCenterSpecRuns(specSel.project, win, specSel.spec)
        : Promise.reject(new Error('spec 视图未选中')),
    active && !!specSel,
    `${project}|${win}|${specSel?.project ?? ''}|${specSel?.spec ?? ''}`,
  );
  // 选中态与响应一致性守卫：响应回显 (project, spec) 与当前选中不符（切换
  // spec 瞬间的上一选择残留数据）时按「未到数据」处理，不拿旧轮次套新 label
  const specRunsForSel =
    specRuns && specSel && specRuns.project === specSel.project && specRuns.spec === specSel.spec
      ? specRuns
      : null;
  // 需求数量格下拉开合（受控 Popover；选中态点击=退出而非重开下拉）
  const [pickerOpen, setPickerOpen] = useState(false);
  const [specCellHover, setSpecCellHover] = useState(false);
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
      {/* spec-runs 刷新失败（add-command-center-spec-view 4.3）：保留上轮
          数据既有口径，屏级 Alert 内联提示 */}
      {specSel && specRunsError ? (
        <Alert
          style={{ marginBottom: 12 }}
          type="warning"
          showIcon
          message={`spec 视图轮次刷新失败：${specRunsError}`}
        />
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
              {/* 需求数量格 = spec 视图入口（add-command-center-spec-view
                  4.2）：cursor pointer + hover 纯色提亮 + 值下 dotted 下划线
                  暗示；选中态底色常亮标识当前模式。toggle 语义：选中态再点
                  =退出（经 onOpenChange 单点分派，避免双击双发）；未选中态
                  点击弹 antd Popover 下拉（开箱动画与全站 antd Modal 既有
                  口径一致，不属静态渲染红线约束的列表 DOM）。 */}
              <Popover
                trigger="click"
                placement="bottom"
                open={pickerOpen}
                onOpenChange={(o) => {
                  if (specSel) {
                    // 选中态点击 = 退出 spec 视图回实时模式（不弹下拉）
                    if (o) onSpecViewChange?.(null);
                    return;
                  }
                  setPickerOpen(o);
                }}
                content={
                  <SpecPicker
                    entries={specsList ?? []}
                    allProjects={!project}
                    onPick={(e) => {
                      onSpecViewChange?.({ project: e.project, spec: e.spec });
                      setPickerOpen(false);
                    }}
                  />
                }
              >
                <div
                  onMouseEnter={() => setSpecCellHover(true)}
                  onMouseLeave={() => setSpecCellHover(false)}
                  style={{
                    flex: 1,
                    minWidth: 0,
                    cursor: 'pointer',
                    borderRadius: 6,
                    padding: '2px 8px',
                    margin: '-2px -8px',
                    background: specSel
                      ? SPEC_CELL_SELECTED_BG
                      : specCellHover
                        ? SPEC_CELL_HOVER_BG
                        : 'transparent',
                  }}
                >
                  <MetricCell
                    value={fmtMetric(data.summary?.spec_count)}
                    label={windowLabels(win).teamSpecs}
                    center
                    clickHint
                    selected={!!specSel}
                  />
                </div>
              </Popover>
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
                    <LaneCard
                      key={c.lane}
                      card={c}
                      win={win}
                      onOpenRun={setRunView}
                      specSel={specSel}
                      specRounds={
                        specSel
                          ? specRunsForSel
                            ? laneSpecRounds(specRunsForSel.lanes, c.lane)
                            : null
                          : null
                      }
                    />
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
