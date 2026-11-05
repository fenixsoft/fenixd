// /v2/overview — v2 概览页（redesign-dashboard-v2-ui 2.1）。
//
// UI 真相源：spec/changes/redesign-dashboard-v2-ui/prototype/variant-b-bento.html
// （4 卡等宽 KPI + 告警横幅 + 项目台账表格，Bento 语言）。数据全部来自与既有页
// 同源的 /api/ 真实端点（getOverview / getAlerts），不内联原型假数据；原型中
// 无真实口径的装饰（示例速率文案）按 null 口径红线不渲染。刷新走 30s 心跳轮询
// （v2 域简化口径：不接入 SSE 合帧，页面为与现产并行的开发期界面）。
import { Alert, App, Button, Dropdown, Input, Progress, Radio, Space, Spin, Table } from 'antd';
import type { ColumnsType } from 'antd/es/table';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate } from '@umijs/max';
import dayjs from 'dayjs';
import {
  clearAllAlerts,
  deleteProject,
  getAlerts,
  getOverview,
  installHosting,
  markAlertHandled,
  statusMeta,
  stopProject,
} from '@/services/dashboard';
import type { AlertsData, OverviewData, ProjectSummary } from '@/services/dashboard';
import { compactWan } from '@/utils/format';
import { pct } from '@/utils/percent';
import { HEARTBEAT_MS } from '@/utils/refreshPolicy';
import { V2AlertRows } from './AlertList';
import { V2Page, V2Pill, V2TitleBand } from './shared';
import {
  useV2IsMobile,
  V2_ERROR,
  V2_GREEN_SOFT,
  V2_HAIRLINE,
  V2_LANE_COLORS,
  V2_RAMP_IMPLEMENTING,
  V2_RAMP_VERIFYING,
  V2_RED_SOFT,
  V2_SPLIT,
  V2_TEXT,
  V2_TEXT_QUATERNARY,
  V2_TEXT_SECONDARY,
  V2_TEXT_TERTIARY,
  V2_TILE_BORDER,
  V2_WARNING,
} from './theme';

// 活跃 Agent 归族口径（与现产 IntroduceRow AGENT_CATS 同源：键域 =
// core/agent_runner/run_files.py RUN_ID_AGENT_PREFIXES 值域，impl-ocr 归实现、
// code-review/评审 judge 族归评审、code-fix/repair 归修复、administrator 运维、
// 未知归其它）；色板用 v2 域数据编码色 V2_LANE_COLORS。
const AGENT_CATS: Array<[string[], string]> = [
  [['implementer', 'impl-ocr'], '实现'],
  [['planner', 'planner-plan'], '规划'],
  [['planner-judge', 'spec-review', 'dispute-judge', 'code-review'], '评审'],
  [['verifier'], '验证'],
  [['tester'], '测试'],
  [['code-fix', 'repair'], '修复'],
  [['administrator'], '运维'],
];

// 段内白字数值的可读下限占比（同现产 IntroduceRow 阈值）
const SEGMENT_LABEL_MIN_SHARE = 0.12;

function TileLabel({ children }: { children: React.ReactNode }) {
  return <div style={{ fontSize: 12, fontWeight: 500, color: V2_TEXT_TERTIARY }}>{children}</div>;
}

/** 任务进度圆环（静态 SVG，原型 Donut 形态）。 */
function Donut({ pct, box = 92 }: { pct: number; box?: number }) {
  const r = 34;
  const circ = 2 * Math.PI * r;
  return (
    <svg width={box} height={box} viewBox="0 0 92 92" aria-hidden>
      <circle cx={46} cy={46} r={r} fill="none" stroke={V2_HAIRLINE} strokeWidth={10} />
      <circle
        cx={46}
        cy={46}
        r={r}
        fill="none"
        stroke={V2_RAMP_IMPLEMENTING}
        strokeWidth={10}
        strokeLinecap="round"
        strokeDasharray={`${((pct / 100) * circ).toFixed(1)} ${circ.toFixed(1)}`}
        transform="rotate(-90 46 46)"
      />
      <text
        x={46}
        y={50}
        textAnchor="middle"
        fontSize={20}
        fontWeight={700}
        fill={V2_TEXT}
        style={{ fontVariantNumeric: 'tabular-nums' }}
      >
        {pct}%
      </text>
    </svg>
  );
}

/** Token 静态 SVG 面积图（原型 spark 形态；x 从旧到新，最新点最右；移动形态
 * h=40 压高度）。 */
function SparkArea({ values, h }: { values: number[]; h?: number }) {
  const W = 560;
  const H = h ?? 56;
  const max = Math.max(...values, 1);
  const pts = values.map((v, i) => [
    6 + (i * (W - 12)) / Math.max(1, values.length - 1),
    H - 8 - (v / max) * (H - 18),
  ]);
  const line = pts.map((p, i) => `${i ? 'L' : 'M'}${p[0].toFixed(1)} ${p[1].toFixed(1)}`).join(' ');
  const area = `${line} L ${W - 6} ${H - 2} L 6 ${H - 2} Z`;
  return (
    <svg width="100%" height={H} viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" aria-hidden>
      <defs>
        <linearGradient id="v2-token-spark" x1={0} y1={0} x2={0} y2={1}>
          <stop offset="0%" stopColor={V2_RAMP_IMPLEMENTING} stopOpacity={0.22} />
          <stop offset="100%" stopColor={V2_RAMP_IMPLEMENTING} stopOpacity={0} />
        </linearGradient>
      </defs>
      <path d={area} fill="url(#v2-token-spark)" />
      <path d={line} fill="none" stroke={V2_RAMP_IMPLEMENTING} strokeWidth={1.6} />
      <circle cx={pts[pts.length - 1][0]} cy={pts[pts.length - 1][1]} r={3} fill={V2_RAMP_IMPLEMENTING} />
    </svg>
  );
}

/** 告警横幅磁贴（多行明细 + 裁决选择题，行渲染复用 V2AlertRow）。移动形态
 * （prototype/m-overview.html overview-alert-banner）：左缘警示条 + 最高级别
 * 统计胶囊 + 单条摘要 + 去处置/标记已处理双按钮，「展开」渐进披露完整列表。 */
function AlertCard({
  alerts,
  totalUnhandled,
  onChanged,
  mobile,
}: {
  alerts: NonNullable<AlertsData['alerts']>;
  totalUnhandled: number;
  onChanged: () => void;
  mobile?: boolean;
}) {
  const { message, modal } = App.useApp();
  const navigate = useNavigate();
  const [collapsed, setCollapsed] = useState(false);
  const [handling, setHandling] = useState(false);
  const rank = (s?: string) => (s === 'critical' ? 3 : s === 'major' ? 2 : s === 'minor' ? 1 : 0);
  const top = alerts.reduce((m, a) => (rank(a.severity) > rank(m.severity) ? a : m), alerts[0]);
  const topTone = top.severity === 'critical' ? 'critical' : top.severity === 'major' ? 'warning' : 'muted';
  const topLabel = top.severity === 'critical' ? '最高级别：严重' : top.severity === 'major' ? '最高级别：较重' : '最高级别：轻微';

  const confirmClearAll = () => {
    modal.confirm({
      title: '清理所有事件',
      content: `确认清理全部项目的 ${totalUnhandled} 条未处理告警？标记后不可撤销，AdminMonitor 不会对同一告警重新升级。`,
      okText: '全部清理',
      okButtonProps: { danger: true },
      cancelText: '取消',
      onOk: () => {
        clearAllAlerts()
          .then(() => {
            message.success('已清理所有事件');
            onChanged();
          })
          .catch((e) => message.error(`清理失败：${e instanceof Error ? e.message : String(e)}`));
      },
    });
  };

  const markTopHandled = async () => {
    setHandling(true);
    try {
      await markAlertHandled(top.project, top.id);
      message.success('已标记处理');
      onChanged();
    } catch (e) {
      message.error(`标记失败：${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setHandling(false);
    }
  };

  if (mobile) {
    const sevShort = top.severity === 'critical' ? '严重' : top.severity === 'major' ? '较重' : '轻微';
    const topSevCount = alerts.filter((a) => a.severity === top.severity).length;
    const edgeColor =
      top.severity === 'critical' ? V2_ERROR : top.severity === 'major' ? V2_WARNING : undefined;
    return (
      <div
        className="v2-bento"
        style={{ marginTop: 16, padding: '12px 12px 6px', borderLeft: edgeColor ? `3px solid ${edgeColor}` : undefined }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <V2Pill tone={topTone}>{`${sevShort} ${topSevCount}`}</V2Pill>
          <span style={{ fontSize: 13, fontWeight: 600, flex: 1, minWidth: 0 }}>
            <span className="v2-num">{totalUnhandled}</span> 条待处理
          </span>
          <a
            className="touch-expand"
            style={{ fontSize: 12, color: V2_TEXT_QUATERNARY }}
            onClick={() => setCollapsed((c) => !c)}
            role="button"
            tabIndex={0}
          >
            {collapsed ? '展开' : '收起'}
          </a>
        </div>
        {!collapsed ? (
          <>
            <div style={{ marginTop: 8, borderTop: `1px solid ${V2_SPLIT}`, padding: '9px 2px' }}>
              <div className="v2-ellipsis" style={{ fontSize: 13, fontWeight: 600 }} title={top.description || top.id}>
                {top.description || top.id}
              </div>
              <div className="v2-num" style={{ fontSize: 12, color: V2_TEXT_QUATERNARY, marginTop: 3 }}>
                {top.project || ''}
                {top.created ? ` · ${dayjs(top.created).format('MM-DD HH:mm')}` : ''}
              </div>
              <div style={{ display: 'flex', gap: 8, marginTop: 8 }}>
                <Button size="small" type="primary" style={{ flex: 1 }} onClick={() => navigate('/v2/activities')}>
                  去处置
                </Button>
                <Button size="small" style={{ flex: 1 }} loading={handling} onClick={() => void markTopHandled()}>
                  标记已处理
                </Button>
              </div>
            </div>
            {alerts.length > 1 ? (
              <V2AlertRows alerts={alerts.filter((a) => a.id !== top.id)} onChanged={onChanged} />
            ) : null}
          </>
        ) : null}
      </div>
    );
  }

  return (
    <div className="v2-bento" style={{ padding: '13px 14px 8px' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '0 4px 11px' }}>
        {/* 圆角方形警示 chip（bento 图标语言） */}
        <span
          style={{
            width: 34,
            height: 34,
            borderRadius: 10,
            background: V2_RED_SOFT,
            display: 'inline-flex',
            alignItems: 'center',
            justifyContent: 'center',
            flexShrink: 0,
          }}
        >
          <svg width={17} height={17} viewBox="0 0 16 16" fill={V2_ERROR} aria-hidden>
            <path d="M8 1.5a6.5 6.5 0 1 1 0 13 6.5 6.5 0 0 1 0-13zM8 4.2a.85.85 0 0 0-.85.9l.2 3.3a.65.65 0 0 0 1.3 0l.2-3.3A.85.85 0 0 0 8 4.2zm0 5.9a.95.95 0 1 0 0 1.9.95.95 0 0 0 0-1.9z" />
          </svg>
        </span>
        <span style={{ fontSize: 14, fontWeight: 600 }}>
          <span className="v2-num">{totalUnhandled}</span> 条待处理人工告警
        </span>
        <V2Pill tone={topTone}>{topLabel}</V2Pill>
        <span style={{ flex: 1 }} />
        <Button size="small" danger onClick={confirmClearAll}>
          清理所有事件
        </Button>
        <a
          style={{ fontSize: 12, color: V2_TEXT_QUATERNARY }}
          onClick={() => setCollapsed((c) => !c)}
          role="button"
          tabIndex={0}
        >
          {collapsed ? '展开' : '收起'}
        </a>
      </div>
      {!collapsed ? <V2AlertRows alerts={alerts} onChanged={onChanged} /> : null}
    </div>
  );
}

/** KPI 区：4 卡等宽磁贴（SPEC 总数 / 任务进度圆环 / Token 消耗 / 活跃 Agent）。
 * 移动形态（prototype/m-overview.html overview-kpi-row）：2×2 磁贴 + 卡内
 * 字号/圆环/spark 压缩。 */
function KpiRow({ data, mobile }: { data: OverviewData; mobile?: boolean }) {
  const t = data.totals;
  const recent = data.token_usage?.recent ?? [];
  const taskPct = pct(t.task_done ?? 0, t.task_total ?? 0);
  const tokenSum = recent.reduce((s, r) => s + (r.tokens || 0), 0);
  const statusEntries = Object.entries(t.status_counts || {});
  const tilePad = mobile ? '14px 16px' : '18px 20px';

  // 活跃 Agent 归族计数（口径见 AGENT_CATS 注记）
  const byType = t.active_runs_by_type || {};
  const cats = AGENT_CATS.map(([keys, label], i) => ({
    label,
    value: keys.reduce((s, k) => s + (byType[k] || 0), 0),
    color: V2_LANE_COLORS[i % V2_LANE_COLORS.length],
  })).filter((d) => d.value > 0);
  const knownTotal = cats.reduce((s, d) => s + d.value, 0);
  const otherValue = Math.max(0, (t.active_runs ?? 0) - knownTotal);
  if (otherValue > 0) {
    cats.push({
      label: '其它',
      value: otherValue,
      color: V2_LANE_COLORS[AGENT_CATS.length % V2_LANE_COLORS.length],
    });
  }
  const agentTotal = cats.reduce((s, d) => s + d.value, 0);

  return (
    <div
      style={
        mobile
          ? { display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }
          : { display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: 16 }
      }
    >
      {/* SPEC 总数 */}
      <div className="v2-bento" style={{ padding: tilePad }}>
        <TileLabel>SPEC 总数</TileLabel>
        <div
          className="v2-num"
          style={{
            fontSize: mobile ? 28 : 40,
            fontWeight: 700,
            letterSpacing: mobile ? -0.6 : -1,
            lineHeight: mobile ? '36px' : '48px',
            marginTop: 8,
          }}
        >
          {t.spec_count ?? 0}
        </div>
        <div style={{ display: 'flex', gap: 16, marginTop: 10 }}>
          <span className="v2-num" style={{ fontSize: 12, color: V2_TEXT_TERTIARY }}>
            今日更新 <span style={{ fontWeight: 600, color: V2_TEXT }}>{t.spec_updated_today ?? 0}</span>
          </span>
          <span className="v2-num" style={{ fontSize: 12, color: V2_TEXT_TERTIARY }}>
            近 7 天 <span style={{ fontWeight: 600, color: V2_TEXT }}>{t.spec_updated_week ?? 0}</span>
          </span>
        </div>
        {/* 状态分布微型堆叠条（真实口径：totals.status_counts；原型此位为无
            数据源的装饰性周条，按 null 口径红线以真实分布替代） */}
        {statusEntries.length ? (
          <div style={{ display: 'flex', gap: 3, marginTop: 14 }}>
            {statusEntries.map(([st, n]) => {
              const meta = statusMeta(st);
              return (
                <div
                  key={st}
                  title={`${meta.label}：${n}`}
                  style={{
                    flex: n,
                    height: 6,
                    borderRadius: 3,
                    background:
                      st === 'blocked' || st === 'bug-found'
                        ? V2_ERROR
                        : st === 'implementing' || st === 'reviewing' || st === 'testing'
                          ? V2_WARNING
                          : V2_TILE_BORDER,
                  }}
                />
              );
            })}
          </div>
        ) : null}
      </div>
      {/* 任务进度（圆环 + 明细行） */}
      <div className="v2-bento" style={{ padding: tilePad, display: 'flex', flexDirection: 'column' }}>
        <TileLabel>任务进度</TileLabel>
        <div style={{ flex: 1, display: 'flex', alignItems: 'center', gap: mobile ? 10 : 14, marginTop: 10 }}>
          <Donut pct={taskPct} box={mobile ? 56 : 72} />
          <div style={{ minWidth: 0 }}>
            <div className="v2-num" style={{ fontSize: mobile ? 15 : 20, fontWeight: 700, whiteSpace: 'nowrap' }}>
              {t.task_done ?? 0} / {t.task_total ?? 0}
              <span style={{ fontSize: 12, fontWeight: 400, color: V2_TEXT_TERTIARY }}> 已完成</span>
            </div>
            {!mobile ? (
              <Progress
                percent={taskPct}
                size="small"
                strokeColor={V2_RAMP_IMPLEMENTING}
                railColor={V2_HAIRLINE}
                showInfo={false}
                style={{ marginTop: 8 }}
              />
            ) : null}
          </div>
        </div>
      </div>
      {/* Token 消耗（口径：最近 20 个有消耗 SPEC 的累计，同现产 Token 卡） */}
      <div className="v2-bento" style={{ padding: tilePad }}>
        <TileLabel>Token 消耗</TileLabel>
        <div
          className="v2-num"
          style={{
            fontSize: mobile ? 24 : 28,
            fontWeight: 700,
            letterSpacing: -0.6,
            lineHeight: '36px',
            marginTop: 8,
          }}
        >
          {recent.length ? compactWan(tokenSum) : '—'}
        </div>
        <div className="v2-num" style={{ fontSize: 12, color: V2_TEXT_TERTIARY, marginTop: 8 }}>
          {recent.length ? (
            <>
              平均每 SPEC{' '}
              <span style={{ fontWeight: 600, color: V2_TEXT, fontSize: 13 }}>{compactWan(Math.round(tokenSum / recent.length))}</span>
            </>
          ) : (
            '暂无 token 记录'
          )}
        </div>
        <div style={{ marginTop: 10 }}>
          {recent.length >= 2 ? <SparkArea values={recent.slice().reverse().map((r) => r.tokens || 0)} h={mobile ? 40 : undefined} /> : null}
        </div>
      </div>
      {/* 活跃 Agent（大数字 + 图例 + 归一化堆叠条） */}
      <div className="v2-bento" style={{ padding: tilePad }}>
        <TileLabel>活跃 Agent</TileLabel>
        <div style={{ display: 'flex', alignItems: 'baseline', gap: 8, flexWrap: 'wrap' }}>
          <div
            className="v2-num"
            style={{
              fontSize: mobile ? 28 : 32,
              fontWeight: 700,
              letterSpacing: -0.8,
              lineHeight: mobile ? '36px' : '40px',
              marginTop: 8,
            }}
          >
            {t.active_runs ?? 0}
          </div>
          {!mobile ? (
            <span
              className="v2-num"
              style={{
                fontSize: 12,
                color: V2_RAMP_VERIFYING,
                fontWeight: 600,
                background: V2_GREEN_SOFT,
                borderRadius: 999,
                padding: '2px 8px',
              }}
            >
              按类型分布
            </span>
          ) : null}
        </div>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: '4px 12px', marginTop: 8 }}>
          {cats.map((d) => (
            <span key={d.label} style={{ display: 'inline-flex', alignItems: 'center', gap: 5, fontSize: 12, color: V2_TEXT_SECONDARY }}>
              <span style={{ width: 7, height: 7, borderRadius: 3, background: d.color, display: 'inline-block' }} />
              {d.label} {d.value}
            </span>
          ))}
        </div>
        <div style={{ display: 'flex', height: mobile ? 12 : 16, borderRadius: mobile ? 6 : 8, overflow: 'hidden', gap: 2, marginTop: 12 }}>
          {agentTotal > 0 &&
            cats.map((d) => {
              const share = d.value / agentTotal;
              return (
                <div
                  key={d.label}
                  title={`${d.label}：${d.value}`}
                  style={{
                    flex: d.value,
                    background: d.color,
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    fontSize: 11,
                    fontWeight: 600,
                    color: '#fff',
                  }}
                >
                  {!mobile && share >= SEGMENT_LABEL_MIN_SHARE ? d.value : ''}
                </div>
              );
            })}
        </div>
      </div>
    </div>
  );
}

/** 项目单元格：名称行（运行态胶囊 + 自动发现/项目错误）+ 路径 + 长简介 + 状态胶囊。 */
function ProjectCell({ p }: { p: ProjectSummary }) {
  const navigate = useNavigate();
  if (p.error) {
    return (
      <div style={{ minWidth: 0 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
          <span style={{ fontSize: 14, fontWeight: 600 }}>{p.name}</span>
          <V2Pill tone="critical">项目错误</V2Pill>
        </div>
        <div className="v2-num" style={{ fontSize: 12, color: V2_TEXT_QUATERNARY, marginTop: 5 }}>
          {p.path}
        </div>
        <div className="v2-ellipsis" style={{ fontSize: 12, color: V2_ERROR, marginTop: 4 }}>
          {p.error}
        </div>
      </div>
    );
  }
  const kids = [
    <div key="id" style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
      <span
        style={{ fontSize: 14, fontWeight: 600, cursor: 'pointer' }}
        onClick={(e) => {
          e.stopPropagation();
          navigate(`/v2/projects/${encodeURIComponent(p.name)}`);
        }}
      >
        {p.name}
      </span>
      {p.daemon === 'running' ? (
        p.hosting === 'unmanaged' ? (
          <V2Pill tone="warning">运行中·未托管</V2Pill>
        ) : (
          <V2Pill tone="good">运行中</V2Pill>
        )
      ) : p.daemon === 'stopped' ? (
        <V2Pill tone="warning">未运行</V2Pill>
      ) : null}
      {p.discovered ? <V2Pill tone="muted">自动发现</V2Pill> : null}
    </div>,
    <div key="path" className="v2-num" style={{ fontSize: 12, color: V2_TEXT_QUATERNARY, marginTop: 5 }}>
      {p.path}
    </div>,
    // 长注释换行显示（pre-wrap，表格 fixed 布局防撑坏）
    <div key="desc" style={{ fontSize: 12, color: V2_TEXT_TERTIARY, marginTop: 4, whiteSpace: 'pre-wrap', lineHeight: '20px' }}>
      {p.description || '暂无简介'}
    </div>,
  ];
  const tags = Object.entries(p.status_counts || {}).map(([st, n]) => {
    const meta = statusMeta(st);
    return <V2Pill key={st} tone={meta.tone}>{`${meta.label} ${n}`}</V2Pill>;
  });
  if (tags.length) {
    kids.push(
      <div key="tags" style={{ display: 'flex', flexWrap: 'wrap', gap: 4, marginTop: 7 }}>
        {tags}
      </div>,
    );
  }
  return <div style={{ minWidth: 0 }}>{kids}</div>;
}

function NumCell({ v, color }: { v: number; color?: string }) {
  return (
    <span className="v2-num" style={{ fontSize: 16, fontWeight: 700, color: color || V2_TEXT }}>
      {v}
    </span>
  );
}

function DashCell() {
  return (
    <span className="v2-num" style={{ color: V2_TEXT_QUATERNARY, fontSize: 16 }}>
      —
    </span>
  );
}

/** 项目台账表格磁贴（fixed 布局 / 首列 14px 缩进 / 长注释换行）。移动形态
 * （prototype/m-overview.html overview-project-panel）：表格转堆叠项目卡，
 * 行级组件复用 ProjectCell，操作收敛在卡头更多菜单（语义同桌面行内操作）。 */
function ProjectPanel({ data, onChanged, mobile }: { data: OverviewData; onChanged: () => void; mobile?: boolean }) {
  const { message, modal } = App.useApp();
  const navigate = useNavigate();
  const [keyword, setKeyword] = useState('');
  const [runFilter, setRunFilter] = useState<'all' | 'running' | 'stopped'>('all');
  const [busy, setBusy] = useState(false);

  const projects = useMemo(() => {
    let list = data.projects || [];
    if (runFilter === 'running') list = list.filter((p) => p.daemon === 'running');
    if (runFilter === 'stopped') list = list.filter((p) => p.daemon !== 'running');
    const kw = keyword.trim().toLowerCase();
    if (kw) {
      list = list.filter(
        (p) =>
          p.name.toLowerCase().includes(kw) ||
          (p.path || '').toLowerCase().includes(kw) ||
          (p.description || '').toLowerCase().includes(kw),
      );
    }
    return list;
  }, [data.projects, keyword, runFilter]);

  const runCount = (data.projects || []).filter((p) => p.daemon === 'running').length;

  const act = (p: ProjectSummary, kind: 'stop' | 'install' | 'delete') => {
    if (kind === 'stop') {
      modal.confirm({
        title: `停止项目 ${p.name}？`,
        content: '将停止该项目的 daemon。',
        okText: '停止',
        onOk: async () => {
          setBusy(true);
          try {
            await stopProject(p.name);
            message.success('已发送停止指令');
            onChanged();
          } catch (e) {
            message.error(e instanceof Error ? e.message : String(e));
          } finally {
            setBusy(false);
          }
        },
      });
      return;
    }
    if (kind === 'install') {
      modal.confirm({
        title: `为 ${p.name} 安装托管？`,
        content: '将安装 daemon 托管（systemd 承载）。',
        okText: '安装托管',
        onOk: async () => {
          setBusy(true);
          try {
            await installHosting(p.name);
            message.success('已发送安装指令');
            onChanged();
          } catch (e) {
            message.error(e instanceof Error ? e.message : String(e));
          } finally {
            setBusy(false);
          }
        },
      });
      return;
    }
    modal.confirm({
      title: `删除项目 ${p.name}？`,
      content: '该操作将项目移出 dashboard 管理，不可撤销。',
      okText: '删除',
      okButtonProps: { danger: true },
      onOk: async () => {
        setBusy(true);
        try {
          await deleteProject(p.name);
          message.success('已删除');
          onChanged();
        } catch (e) {
          message.error(e instanceof Error ? e.message : String(e));
        } finally {
          setBusy(false);
        }
      },
    });
  };

  if (mobile) {
    const taskPct = (p: ProjectSummary) => pct(p.task_done, p.task_total);
    return (
      <div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
          <span style={{ fontSize: 16, fontWeight: 700 }}>项目清单</span>
          <span className="v2-num" style={{ fontSize: 12, color: V2_TEXT_QUATERNARY }}>
            {(data.projects || []).length} 个 · 运行中 {runCount}
          </span>
        </div>
        <Input.Search
          placeholder="搜索项目"
          size="small"
          allowClear
          style={{ width: '100%', marginTop: 10 }}
          value={keyword}
          onChange={(e) => setKeyword(e.target.value)}
        />
        <div style={{ marginTop: 12, display: 'flex', flexDirection: 'column', gap: 12 }}>
          {projects.map((p) => (
            <div
              key={p.name}
              className="v2-bento"
              style={{ padding: '14px 16px', cursor: p.error ? 'default' : 'pointer' }}
              onClick={() => {
                if (!p.error) navigate(`/v2/projects/${encodeURIComponent(p.name)}`);
              }}
            >
              <div style={{ display: 'flex', alignItems: 'flex-start', gap: 8 }}>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <ProjectCell p={p} />
                </div>
                <Dropdown
                  menu={{
                    items: [
                      { key: 'stop', label: '停止', disabled: busy || Boolean(p.error) || p.daemon !== 'running' },
                      { key: 'install', label: '安装托管', disabled: busy || Boolean(p.error) || p.hosting === 'managed' },
                      { type: 'divider' },
                      { key: 'delete', label: '删除', danger: true, disabled: busy || Boolean(p.error) },
                    ],
                    onClick: ({ key, domEvent }) => {
                      domEvent.stopPropagation();
                      if (key === 'stop') act(p, 'stop');
                      if (key === 'install') act(p, 'install');
                      if (key === 'delete') act(p, 'delete');
                    },
                  }}
                  placement="bottomRight"
                  trigger={['click']}
                >
                  <Button type="text" size="small" icon={<DotsIcon />} aria-label="更多操作" />
                </Dropdown>
              </div>
              {!p.error ? (
                <>
                  <div style={{ display: 'flex', gap: 14, marginTop: 8 }}>
                    <span className="v2-num" style={{ fontSize: 12, color: V2_TEXT_TERTIARY }}>
                      SPEC <span style={{ fontWeight: 700, color: V2_TEXT }}>{p.spec_count}</span>
                    </span>
                    <span className="v2-num" style={{ fontSize: 12, color: V2_TEXT_TERTIARY }}>
                      问题{' '}
                      <span style={{ fontWeight: 700, color: p.problems > 0 ? V2_ERROR : V2_TEXT }}>{p.problems}</span>
                    </span>
                    <span className="v2-num" style={{ fontSize: 12, color: V2_TEXT_TERTIARY }}>
                      活跃{' '}
                      <span style={{ fontWeight: 700, color: p.active_runs > 0 ? V2_WARNING : V2_TEXT }}>{p.active_runs}</span>
                    </span>
                  </div>
                  <div style={{ marginTop: 8 }}>
                    <Progress percent={taskPct(p)} size="small" strokeColor={V2_RAMP_IMPLEMENTING} railColor={V2_HAIRLINE} showInfo={false} />
                  </div>
                  <div className="v2-num" style={{ fontSize: 12, color: V2_TEXT_TERTIARY, marginTop: 4 }}>
                    {p.task_done}/{p.task_total} · {taskPct(p)}%
                  </div>
                </>
              ) : null}
            </div>
          ))}
          {!projects.length ? (
            <div style={{ fontSize: 12, color: V2_TEXT_TERTIARY, padding: '12px 0' }}>无匹配项目</div>
          ) : null}
        </div>
      </div>
    );
  }

  const columns: ColumnsType<ProjectSummary> = [
    { title: '项目', dataIndex: 'name', render: (_, p) => <ProjectCell p={p} /> },
    {
      title: 'SPEC 数',
      dataIndex: 'spec_count',
      width: 96,
      align: 'right',
      render: (v, p) => (p.error ? <DashCell /> : <NumCell v={v} />),
    },
    {
      title: '任务进度',
      dataIndex: 'task_total',
      width: 220,
      render: (_, p) =>
        p.error ? (
          <DashCell />
        ) : (
          <div style={{ minWidth: 0 }}>
            <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', gap: 8 }}>
              <span style={{ fontSize: 12, color: V2_TEXT_TERTIARY }}>任务进度</span>
              <span className="v2-num" style={{ fontSize: 12, fontWeight: 600 }}>
                {p.task_done}/{p.task_total} ·{' '}
                {pct(p.task_done, p.task_total)}%
              </span>
            </div>
            <div style={{ marginTop: 6 }}>
              <Progress
                percent={pct(p.task_done, p.task_total)}
                size="small"
                strokeColor={V2_RAMP_IMPLEMENTING}
                railColor={V2_HAIRLINE}
                showInfo={false}
              />
            </div>
          </div>
        ),
    },
    {
      title: '问题/阻塞',
      dataIndex: 'problems',
      width: 108,
      align: 'right',
      render: (v, p) => (p.error ? <DashCell /> : <NumCell v={v} color={v > 0 ? V2_ERROR : undefined} />),
    },
    {
      title: '活跃运行',
      dataIndex: 'active_runs',
      width: 108,
      align: 'right',
      render: (v, p) => (p.error ? <DashCell /> : <NumCell v={v} color={v > 0 ? V2_WARNING : undefined} />),
    },
    {
      title: '操作',
      key: 'actions',
      width: 116,
      align: 'right',
      render: (_, p) => (
        <Space size={4} onClick={(e) => e.stopPropagation()}>
          <Button
            type="link"
            size="small"
            onClick={() => navigate(`/v2/projects/${encodeURIComponent(p.name)}`)}
          >
            进入
          </Button>
          <Dropdown
            menu={{
              items: [
                // p.error 是错误文案字符串，disabled 须布尔化
                { key: 'stop', label: '停止', disabled: busy || Boolean(p.error) || p.daemon !== 'running' },
                { key: 'install', label: '安装托管', disabled: busy || Boolean(p.error) || p.hosting === 'managed' },
                { type: 'divider' },
                { key: 'delete', label: '删除', danger: true, disabled: busy || Boolean(p.error) },
              ],
              onClick: ({ key, domEvent }) => {
                domEvent.stopPropagation();
                if (key === 'stop') act(p, 'stop');
                if (key === 'install') act(p, 'install');
                if (key === 'delete') act(p, 'delete');
              },
            }}
            placement="bottomRight"
            trigger={['click']}
          >
            <Button type="text" size="small" icon={<DotsIcon />} aria-label="更多操作" />
          </Dropdown>
        </Space>
      ),
    },
  ];

  return (
    <div className="v2-bento">
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 12,
          flexWrap: 'wrap',
          padding: '14px 20px',
          borderBottom: `1px solid ${V2_SPLIT}`,
        }}
      >
        <span style={{ fontSize: 16, fontWeight: 700 }}>项目清单</span>
        <span className="v2-num" style={{ fontSize: 12, color: V2_TEXT_QUATERNARY }}>
          共 {(data.projects || []).length} 个 · 运行中 {runCount}
        </span>
        <span style={{ flex: 1 }} />
        <Input.Search
          placeholder="搜索项目"
          size="small"
          allowClear
          style={{ width: 200 }}
          value={keyword}
          onChange={(e) => setKeyword(e.target.value)}
        />
        <Radio.Group
          optionType="button"
          size="small"
          value={runFilter}
          onChange={(e) => setRunFilter(e.target.value)}
          options={[
            { label: '全部', value: 'all' },
            { label: '运行中', value: 'running' },
            { label: '未运行', value: 'stopped' },
          ]}
        />
      </div>
      <div className="v2-bento-table">
        <Table
          columns={columns}
          dataSource={projects}
          rowKey="name"
          pagination={false}
          size="middle"
          scroll={{ x: 1060 }}
          rowClassName={() => 'v2-project-row'}
          onRow={(rec) => ({
            onClick: () => {
              if (!rec.error) navigate(`/v2/projects/${encodeURIComponent(rec.name)}`);
            },
            style: { cursor: rec.error ? 'default' : 'pointer' },
          })}
        />
      </div>
    </div>
  );
}

function DotsIcon() {
  return (
    <svg width={14} height={14} viewBox="0 0 14 14" fill="currentColor" aria-hidden>
      <circle cx={2.6} cy={7} r={1.2} />
      <circle cx={7} cy={7} r={1.2} />
      <circle cx={11.4} cy={7} r={1.2} />
    </svg>
  );
}

export default function V2OverviewPage() {
  const mobile = useV2IsMobile();
  const [data, setData] = useState<OverviewData | null>(null);
  const [alerts, setAlerts] = useState<AlertsData | null>(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);
  const seqRef = useRef(0);

  const load = useCallback(async () => {
    const seq = ++seqRef.current;
    try {
      // 告警拉取失败不阻断概览本体（横幅缺数据退场，错误由 alerts error 提示）
      const [ov, al] = await Promise.all([getOverview(), getAlerts().catch(() => null)]);
      if (seq !== seqRef.current) return;
      setData(ov);
      setAlerts(al);
      setError('');
    } catch (e) {
      if (seq !== seqRef.current) return;
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      if (seq === seqRef.current) setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
    const hb = setInterval(() => void load(), HEARTBEAT_MS);
    return () => clearInterval(hb);
  }, [load]);

  const unhandled = alerts?.alerts ?? [];

  return (
    <V2Page>
      <V2TitleBand
        title="跨项目概览"
        subtitle={
          data
            ? `监控 ${(data.projects || []).length} 个项目${(data.totals?.problems ?? 0) > 0 ? ` · ${data.totals.problems} 个问题/阻塞` : ''}`
            : undefined
        }
      />
      <div style={{ marginTop: 20 }}>
        {error ? (
          <Alert
            type="error"
            showIcon
            style={{ marginBottom: 16 }}
            message="概览数据加载失败"
            description={error}
            action={
              <Button size="small" onClick={() => void load()}>
                重试
              </Button>
            }
          />
        ) : null}
        {loading && !data ? (
          <div className="v2-bento" style={{ padding: 48, textAlign: 'center' }}>
            <Spin size="large" />
          </div>
        ) : data ? (
          <>
            {unhandled.length ? (
              <AlertCard
                alerts={unhandled}
                totalUnhandled={alerts?.total_unhandled ?? unhandled.length}
                onChanged={() => void load()}
                mobile={mobile}
              />
            ) : null}
            <div style={{ marginTop: 16 }}>
              <KpiRow data={data} mobile={mobile} />
            </div>
            <div style={{ marginTop: 16 }}>
              <ProjectPanel data={data} onChanged={() => void load()} mobile={mobile} />
            </div>
          </>
        ) : null}
      </div>
    </V2Page>
  );
}
