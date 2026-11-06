// /v2/projects/:name/:spec — v2 SPEC 详情页（redesign-dashboard-v2-ui 2.3）。
//
// UI 真相源：spec/changes/redesign-dashboard-v2-ui/prototype/spec-detail.html
// （标题带 + 项目信息 8 项 + 任务清单大百分比 + 五页签磁贴）。数据消费
// /api/specs/<spec> 与 /api/hooks/audit 真实端点；缺口字段渲染「—」不伪装 0。
// 状态转移动作词表与判据同现产（list.tsx specMenuItems / SpecStatusModal 收敛
// 后的真实端点子集），不重造状态机；验证结论汇总走 verdict/quality_gates 结构
// 不自造「通过/失败」断言。刷新走 30s 心跳轮询（v2 域简化口径，不接 SSE 合帧）。
import { Alert, App, Button, Dropdown, Image, Progress, Spin, Table, Tabs } from 'antd';
import type { MenuProps } from 'antd';
import type { ColumnsType } from 'antd/es/table';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate, useParams } from '@umijs/max';
import dayjs from 'dayjs';
import {
  clearSpecError,
  deleteSpec,
  freezeSpec,
  getHookAudit,
  getSpecDetail,
  getSpecs,
  promoteSpec,
  reReviewSpec,
  resumeSpec,
  statusMeta,
  unfreezeSpec,
} from '@/services/dashboard';
import type { HookAuditData, SpecDetail, SpecSummary } from '@/services/dashboard';
import { fmtDuration } from '@/utils/duration';
// 副标题组合单源（add-spec-subtitle-and-row-click task 1.3：「中文标题 ·
// branch」组合语义不在页面自拼）
import { combineSpecSubtitle } from '@/pages/projects/specTitle';
import { compactWan } from '@/utils/format';
import { formatUsd } from '@/utils/runVisual';
import { HEARTBEAT_MS } from '@/utils/refreshPolicy';
import { SPEC_REVIEW_BLOCKED_PREFIXES } from '@/utils/specReview';
import { V2Page, V2Pill, V2StatusPill } from './shared';
import { PageTitleBar } from '@/components/PageTitleBar';
import {
  useV2IsMobile,
  V2_BG,
  V2_ERROR,
  V2_HAIRLINE,
  V2_LINK,
  V2_RAMP_IMPLEMENTING,
  V2_RAMP_VERIFYING,
  V2_SPLIT,
  V2_TEXT,
  V2_TEXT_QUATERNARY,
  V2_TEXT_SECONDARY,
  V2_TEXT_TERTIARY,
  V2_WARNING,
} from './theme';

// 终态（冻结等调度类动作的禁用口径，同现产 PRIORITY_TERMINAL + archived）
const TERMINAL_STATUSES = new Set(['done', 'pushed', 'archived']);

// 截图静态路由（同现产 detail.tsx screenshotUrl 形态）
const screenshotUrl = (project: string, spec: string, file: string) =>
  `/screenshots/${encodeURIComponent(project)}/${encodeURIComponent(spec)}/${encodeURIComponent(file)}`;

function fmtTime(v?: string | null): string {
  return v ? dayjs(v).format('YYYY-MM-DD HH:mm:ss') : '—';
}

function Dash({ children }: { children?: React.ReactNode }) {
  if (children === undefined || children === null || children === '') {
    return <span className="v2-num" style={{ color: V2_TEXT_QUATERNARY }}>—</span>;
  }
  return <>{children}</>;
}

/** 项目信息 8 项（原型 InfoCard grid；缺口「—」）。移动形态（prototype/
 * m-spec-detail.html sd-info）：单列键值行（label 固宽 + 值右对齐 + 分隔线）。 */
function InfoCard({ d, mobile }: { d: SpecDetail; mobile?: boolean }) {
  const tu = d.token_usage;
  // 缓存命中率 = 缓存读 / tokens_in（token_usage 契约：tokens_in 已含缓存写入
  // 与命中、分项 cache 入 input，口径同 @/utils/tokens fmtInputTokens，不做
  // 分母双重计数）；[0,100] 钳制同源。分项缺省（历史条目 null）不显示括号
  let inCell: React.ReactNode = <Dash />;
  if (tu) {
    const cacheRead = tu.cache_read_input_tokens;
    const hitRate =
      cacheRead != null && tu.tokens_in > 0
        ? Math.min(100, Math.max(0, Math.round((cacheRead / tu.tokens_in) * 1000) / 10))
        : null;
    inCell = (
      <>
        <span className="v2-num">{compactWan(tu.tokens_in || 0)}</span>
        {cacheRead != null ? (
          <span className="v2-num" style={{ fontWeight: 400, color: V2_TEXT_TERTIARY }}>
            {' '}（缓存命中 {compactWan(cacheRead)}
            {hitRate != null ? `，命中率 ${hitRate}%` : ''}）
          </span>
        ) : null}
      </>
    );
  }
  let costCell: React.ReactNode = <Dash />;
  if (d.cost_summary) {
    costCell =
      d.cost_summary.computed_usd != null ? (
        <>
          <span className="v2-num">{formatUsd(d.cost_summary.computed_usd)}</span>
          {d.cost_summary.unpriced_runs > 0 ? (
            <span className="v2-num" style={{ fontWeight: 400, color: V2_TEXT_TERTIARY }}>
              （含 {d.cost_summary.unpriced_runs} 个未计价 run）
            </span>
          ) : null}
        </>
      ) : (
        <span className="v2-num" style={{ color: V2_TEXT_QUATERNARY }}>run 均不可计价</span>
      );
  } else if (tu?.cost_usd != null) {
    costCell = <span className="v2-num">{formatUsd(tu.cost_usd)}</span>;
  }
  const items: Array<[string, React.ReactNode]> = [
    ['优先级', d.priority != null ? <span key="p">P{d.priority}</span> : <Dash key="p" />],
    ['创建时间', <span key="c">{fmtTime(d.created)}</span>],
    ['更新时间', <span key="u">{fmtTime(d.updated)}</span>],
    ['依赖', d.depends_on ? <span key="d">{d.depends_on}</span> : <span key="d">无依赖</span>],
    ['输入 Token', inCell],
    ['输出 Token', tu ? <span key="o" className="v2-num">{compactWan(tu.tokens_out || 0)}</span> : <Dash key="o" />],
    ['耗时', d.total_duration ? <span key="t">{fmtDuration(d.total_duration)}</span> : <Dash key="t" />],
    ['成本', costCell],
  ];
  return (
    <div
      className="v2-bento"
      data-proto-id="sd-info"
      style={{ marginTop: 18, padding: mobile ? '14px 16px 10px' : '16px 22px 18px' }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
        <span style={{ fontSize: 15, fontWeight: 700 }}>项目信息</span>
        {d.branch ? (
          <span className="v2-mono v2-ellipsis" style={{ fontSize: 12, color: V2_TEXT_TERTIARY }}>{d.branch}</span>
        ) : null}
      </div>
      {mobile ? (
        <div style={{ marginTop: 8 }}>
          {items.map(([k, v]) => (
            <div
              key={k}
              style={{ display: 'flex', gap: 8, padding: '6px 0', borderBottom: `1px solid ${V2_BG}`, alignItems: 'baseline' }}
            >
              <span style={{ fontSize: 12, color: V2_TEXT_TERTIARY, width: 76, flexShrink: 0 }}>{k}</span>
              <span className="v2-num" style={{ fontSize: 13, fontWeight: 600, flex: 1, minWidth: 0, textAlign: 'right' }}>
                {v}
              </span>
            </div>
          ))}
        </div>
      ) : (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: '12px 32px', marginTop: 14 }}>
          {items.map(([k, v]) => (
            <div key={k} style={{ minWidth: 0, display: 'flex', gap: 8, alignItems: 'baseline' }}>
              <span style={{ fontSize: 12, color: V2_TEXT_TERTIARY, flexShrink: 0 }}>{k}：</span>
              <span className="v2-num" style={{ fontSize: 13, fontWeight: 600, minWidth: 0 }}>{v}</span>
            </div>
          ))}
        </div>
      )}
      {d.error ? (
        <Alert
          type="error"
          showIcon
          style={{ marginTop: 12 }}
          message="SPEC 处于异常态"
          description={<span style={{ whiteSpace: 'pre-wrap' }}>{d.error}</span>}
        />
      ) : null}
    </div>
  );
}

/** 任务清单卡（大百分比 + 分组勾选清单；分组内超 8 行折叠，toggle 真实可用；
 * 移动形态容器 padding 收窄，结构与桌面一致）。 */
function TaskCard({ d, mobile }: { d: SpecDetail; mobile?: boolean }) {
  const [expanded, setExpanded] = useState(false);
  const groups = d.tasks || [];
  const done = groups.reduce((s, g) => s + g.done, 0);
  const total = groups.reduce((s, g) => s + g.total, 0);
  const pct = Math.round((done / Math.max(1, total)) * 100);
  const rows = groups.flatMap((g) => g.tasks.map((t) => ({ ...t, group: g.title })));
  const visible = expanded ? rows : rows.slice(0, 8);
  // 按折叠视图计 hidden（code-review item 4d3b9e8b2d60）：展开态 visible 取全量，
  // 减 visible 会使 hidden 恒 0、「收起」入口消失；固定阈值 8 与上方 slice 对齐。
  const hidden = Math.max(0, rows.length - 8);

  return (
    <div
      className="v2-bento"
      data-proto-id="sd-tasks"
      style={{ marginTop: 16, padding: mobile ? '14px 16px 18px' : '16px 22px 18px' }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
        <span style={{ fontSize: 15, fontWeight: 700 }}>任务清单</span>
        {d.run_activity?.active ? <V2Pill tone="info">运行中</V2Pill> : null}
        {d.run_progress ? (
          <span className="v2-num" style={{ fontSize: 12, color: V2_TEXT_TERTIARY }}>
            run 实时 {d.run_progress.done}/{d.run_progress.total}
          </span>
        ) : null}
      </div>
      <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', marginTop: 10 }}>
        <span className="v2-num" style={{ fontSize: 30, fontWeight: 700, letterSpacing: -0.8 }}>
          {total > 0 ? `${pct}%` : '—'}
        </span>
        <span className="v2-num" style={{ fontSize: 13, color: V2_TEXT_TERTIARY }}>
          已完成 <span style={{ fontWeight: 700, color: V2_TEXT, fontSize: 15 }}>{done} / {total}</span>
        </span>
      </div>
      <div style={{ marginTop: 8 }}>
        <Progress percent={pct} strokeColor={V2_RAMP_IMPLEMENTING} railColor={V2_HAIRLINE} showInfo={false} />
      </div>
      {d.tasks_note ? (
        <div style={{ fontSize: 12, color: V2_TEXT_TERTIARY, marginTop: 10 }}>{d.tasks_note}</div>
      ) : null}
      <div style={{ marginTop: 8 }}>
        {groups.map((g) => (
          <div key={g.title} className="v2-num" style={{ fontSize: 12, color: V2_TEXT_TERTIARY, marginTop: 10 }}>
            {g.title} · {g.done}/{g.total}
          </div>
        ))}
      </div>
      <div style={{ marginTop: 4 }}>
        {visible.map((t) => (
          <div key={`${t.group}-${t.id}`} style={{ display: 'flex', gap: 10, padding: '7px 0', borderBottom: `1px solid ${V2_HAIRLINE}` }}>
            {t.done ? (
              <span className="v2-task-check" aria-hidden>
                <svg width={9} height={9} viewBox="0 0 10 10" fill="none">
                  <path d="M1.5 5.2 4 7.6 8.5 2.6" stroke="#fff" strokeWidth={1.6} strokeLinecap="round" strokeLinejoin="round" />
                </svg>
              </span>
            ) : (
              <span
                aria-hidden
                style={{ width: 16, height: 16, borderRadius: 8, border: `1.5px solid ${V2_TEXT_QUATERNARY}`, flexShrink: 0, marginTop: 1 }}
              />
            )}
            <div style={{ minWidth: 0, fontSize: 13 }}>
              <span className="v2-mono" style={{ color: V2_LINK, fontWeight: 600, marginRight: 8 }}>{t.id}</span>
              <span className="v2-mono" style={{ fontSize: 12.5, color: V2_TEXT_SECONDARY }}>{t.desc}</span>
            </div>
          </div>
        ))}
      </div>
      {hidden > 0 ? (
        <a
          role="button"
          tabIndex={0}
          onClick={() => setExpanded((e) => !e)}
          style={{ fontSize: 12, color: V2_TEXT_QUATERNARY, display: 'inline-block', marginTop: 8 }}
        >
          {expanded ? '收起' : `展开其余 ${hidden} 项`}
        </a>
      ) : null}
    </div>
  );
}

/** 时间轴节点标记色（kind 语义；回退转移升 warning；色值取 v2 域单源 V2_* 常量）。 */
const NODE_TONE_HEX: Record<string, string> = {
  muted: V2_TEXT_QUATERNARY,
  info: V2_RAMP_IMPLEMENTING,
  warning: V2_WARNING,
  critical: V2_ERROR,
  good: V2_RAMP_VERIFYING,
};
function nodeTone(ev: NonNullable<SpecDetail['timeline']>[number]): string {
  if (ev.kind === 'state') return ev.backward ? 'warning' : 'muted';
  if (ev.kind === 'run') return 'warning';
  if (ev.kind === 'verify') return ev.errors ? 'critical' : 'good';
  // admin：escalation 人工告警 / disposition 处置记录
  return ev.record_kind === 'disposition' ? 'info' : 'critical';
}

function nodeLabel(ev: NonNullable<SpecDetail['timeline']>[number]): string {
  if (ev.kind === 'state') return ev.backward ? '状态回退' : '状态转移';
  if (ev.kind === 'run') return ev.agent_type || 'run';
  if (ev.kind === 'verify') return '验证执行';
  return ev.record_kind === 'disposition' ? '处置记录' : '人工告警';
}

function stateText(ev: NonNullable<SpecDetail['timeline']>[number]): string {
  const lbl = (s?: string | null) => (s ? statusMeta(s).label : s ?? '');
  if (ev.chain && ev.chain.length > 0) return ev.chain.map(lbl).join(' → ');
  if (ev.from && ev.to) return `${lbl(ev.from)} → ${lbl(ev.to)}`;
  return lbl(ev.to) || lbl(ev.from);
}

function TimelinePane({ d }: { d: SpecDetail }) {
  const tl = d.timeline || [];
  const origin = tl.find((e) => e.origin_request);
  return (
    <div data-proto-id="sd-timeline" style={{ padding: '18px 4px 4px' }}>
      {origin?.origin_request ? (
        <div className="v2-bento" style={{ padding: '10px 14px', marginBottom: 14 }}>
          <div style={{ fontSize: 12, fontWeight: 600, color: V2_TEXT_TERTIARY }}>立项原话</div>
          <div style={{ fontSize: 12.5, whiteSpace: 'pre-wrap', marginTop: 5, color: V2_TEXT_SECONDARY }}>
            {origin.origin_request}
          </div>
        </div>
      ) : null}
      {tl.length === 0 ? (
        <div style={{ fontSize: 12, color: V2_TEXT_TERTIARY, padding: '8px 4px' }}>暂无时间轴记录</div>
      ) : null}
      {tl.map((ev, i) => {
        const kids: React.ReactNode[] = [];
        if (ev.kind === 'state') {
          kids.push(<span key="st" style={{ fontSize: 13.5, fontWeight: 600 }}>{stateText(ev)}</span>);
          if (ev.reason) kids.push(<span key="r" style={{ fontSize: 12, color: V2_TEXT_TERTIARY }}>{ev.reason}</span>);
        } else if (ev.kind === 'run') {
          kids.push(<span key="t" style={{ fontSize: 13.5, fontWeight: 600 }}>{ev.summary || `${nodeLabel(ev)} 完成`}</span>);
        } else if (ev.kind === 'verify') {
          kids.push(
            <span key="t" style={{ fontSize: 13.5, fontWeight: 600 }}>
              验证 {ev.passed ?? 0}/{ev.total ?? 0} 通过{ev.failed ? ` · 失败 ${ev.failed}` : ''}
              {ev.errors ? ` · 错误 ${ev.errors}` : ''}
            </span>,
          );
        } else {
          kids.push(<span key="t" style={{ fontSize: 13.5, fontWeight: 600 }}>{ev.description || nodeLabel(ev)}</span>);
        }
        const metas: string[] = [];
        if (ev.run_id) metas.push(ev.run_id);
        if (ev.llm) metas.push(ev.llm);
        if (ev.duration_seconds) metas.push(`耗时 ${fmtDuration(ev.duration_seconds)}`);
        if (ev.cost_usd != null) metas.push(formatUsd(ev.cost_usd));
        if (ev.retry_count) metas.push(`重试 ${ev.retry_count}${ev.retry_max ? `/${ev.retry_max}` : ''}`);
        if (ev.harness && ev.harness !== 'claude') metas.push(ev.harness);
        if (ev.handled != null) metas.push(ev.handled ? '已处置' : '未处置');
        if (ev.result) metas.push(ev.result);
        if (ev.env_error) metas.push(`env 错误：${ev.env_error}`);
        if (ev.lane_summary) metas.push(ev.lane_summary);
        if (ev.arbiter?.root_cause) metas.push(`归因：${ev.arbiter.root_cause}`);
        if (ev.status && ev.kind === 'run') metas.push(`状态 ${ev.status}`);
        return (
          <div
            key={`${ev.time}-${i}`}
            style={{
              position: 'relative',
              padding: '0 0 20px 30px',
              borderLeft: i === tl.length - 1 ? 'none' : `2px solid ${V2_SPLIT}`,
              marginLeft: 5,
            }}
          >
            <span
              style={{
                position: 'absolute',
                left: -6,
                top: 2,
                width: 10,
                height: 10,
                borderRadius: 5,
                background: NODE_TONE_HEX[nodeTone(ev)] || NODE_TONE_HEX.muted,
                border: '2px solid #fff',
                boxShadow: `0 0 0 1px ${V2_SPLIT}`,
              }}
            />
            <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
              <span className="v2-num" style={{ fontSize: 12, color: V2_TEXT_QUATERNARY }}>
                {fmtTime(ev.time)}
              </span>
              <V2Pill tone={nodeTone(ev)}>{nodeLabel(ev)}</V2Pill>
              {kids}
            </div>
            {metas.length ? (
              <div className="v2-num" style={{ fontSize: 12, color: V2_TEXT_TERTIARY, marginTop: 4, whiteSpace: 'pre-wrap' }}>
                {metas.join(' · ')}
              </div>
            ) : null}
          </div>
        );
      })}
    </div>
  );
}

/** 场景结果页签（汇总 pill 行 + 场景表；断言明细列展示描述/错误首行；移动
 * 形态表格转堆叠卡——越界治理布局优先，窄屏不横向挤压四列表）。 */
function ScenarioPane({ d, mobile }: { d: SpecDetail; mobile?: boolean }) {
  const scenarios = d.scenarios || [];
  const sum = d.report?.summary;
  const bugCount = (d.bugs || []).length;
  const tone = (s: string) => (s === 'pass' ? 'good' : s === 'warning' ? 'warning' : 'critical');
  const label = (s: string) => (s === 'pass' ? '通过' : s === 'warning' ? '警告' : s === 'fail' ? '失败' : '错误');
  type ScenarioRow = NonNullable<SpecDetail['scenarios']>[number];
  const columns: ColumnsType<ScenarioRow> = [
    {
      title: '场景',
      dataIndex: 'scenario_id',
      render: (v: string) => <span className="v2-mono" style={{ fontSize: 12.5, fontWeight: 600 }}>{v}</span>,
    },
    { title: '类型', dataIndex: 'kind', width: 76, render: (v?: string) => <V2Pill tone="muted">{v || 'web'}</V2Pill> },
    {
      title: '结果',
      dataIndex: 'status',
      width: 90,
      render: (v: string) => <V2Pill tone={tone(v)}>{label(v)}</V2Pill>,
    },
    {
      title: '说明',
      dataIndex: 'description',
      render: (_, rec) => (
        <span style={{ fontSize: 12, color: V2_TEXT_TERTIARY }}>{rec.description || '—'}</span>
      ),
    },
  ];
  return (
    <div data-proto-id="sd-scenarios" style={{ padding: '18px 0 4px' }}>
      <div style={{ display: 'flex', gap: 10, marginBottom: 12, flexWrap: 'wrap' }}>
        {sum ? (
          <>
            <V2Pill tone="good">通过 {sum.passed ?? 0}</V2Pill>
            <V2Pill tone={sum.failed ? 'critical' : 'muted'}>失败 {sum.failed ?? 0}</V2Pill>
            <V2Pill tone={sum.errors ? 'critical' : 'muted'}>错误 {sum.errors ?? 0}</V2Pill>
            <V2Pill tone={bugCount ? 'critical' : 'muted'}>产品Bug {bugCount}</V2Pill>
          </>
        ) : (
          <V2Pill tone="muted">暂无验证报告</V2Pill>
        )}
        {d.report?.degrade_annotation ? <V2Pill tone="warning">报告为降级合成</V2Pill> : null}
      </div>
      {scenarios.length ? (
        mobile ? (
          <div>
            {scenarios.map((s) => (
              <div key={s.scenario_id} style={{ borderTop: `1px solid ${V2_HAIRLINE}`, padding: '10px 0' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
                  <span className="v2-mono v2-ellipsis" style={{ fontSize: 12.5, fontWeight: 600, flex: 1, minWidth: 0 }}>
                    {s.scenario_id}
                  </span>
                  <V2Pill tone="muted">{s.kind || 'web'}</V2Pill>
                  <V2Pill tone={tone(s.status)}>{label(s.status)}</V2Pill>
                </div>
                <div style={{ fontSize: 12, color: V2_TEXT_TERTIARY, marginTop: 4, whiteSpace: 'pre-wrap' }}>
                  {s.description || '—'}
                </div>
              </div>
            ))}
          </div>
        ) : (
          <Table
            columns={columns}
            dataSource={scenarios}
            rowKey="scenario_id"
            pagination={false}
            size="middle"
          />
        )
      ) : (
        <div style={{ fontSize: 12, color: V2_TEXT_TERTIARY }}>暂无场景结果记录</div>
      )}
    </div>
  );
}

/** Bug 页签（产品 bug 列表 + 被分类过滤的非产品失败摘要）。 */
function BugPane({ d }: { d: SpecDetail }) {
  const bugs = d.bugs || [];
  const filtered = d.filtered_failures || [];
  const sevTone = (s: string) => (s === 'critical' || s === 'major' ? 'critical' : s === 'minor' ? 'warning' : 'muted');
  const sevLabel: Record<string, string> = { critical: '严重', major: '较重', minor: '轻微', info: '提示' };
  return (
    <div data-proto-id="sd-bugs" style={{ padding: '18px 0' }}>
      <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
        <V2Pill tone={bugs.length ? 'critical' : 'good'}>产品Bug {bugs.length}</V2Pill>
        <V2Pill tone="muted">已过滤失败 {filtered.length}</V2Pill>
      </div>
      {bugs.map((b) => (
        <div key={b.id} style={{ borderTop: `1px solid ${V2_HAIRLINE}`, padding: '10px 0' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
            <V2Pill tone={sevTone(b.severity)}>{sevLabel[b.severity] || b.severity}</V2Pill>
            <span style={{ fontSize: 13, fontWeight: 600 }}>{b.description}</span>
            {b.scenario ? (
              <span className="v2-mono" style={{ fontSize: 12, color: V2_TEXT_TERTIARY }}>{b.scenario}</span>
            ) : null}
          </div>
          {b.evidence ? (
            <div style={{ fontSize: 12, color: V2_TEXT_SECONDARY, whiteSpace: 'pre-wrap', marginTop: 4 }}>
              {b.evidence}
            </div>
          ) : null}
          {b.screenshots?.length ? (
            <div style={{ display: 'flex', gap: 8, marginTop: 6, flexWrap: 'wrap' }}>
              {b.screenshots.map((f) => (
                <Image
                  key={f}
                  src={screenshotUrl(d.project, d.name, f)}
                  alt={f}
                  width={120}
                  height={80}
                  style={{ objectFit: 'cover', border: `1px solid ${V2_HAIRLINE}`, borderRadius: 4 }}
                />
              ))}
            </div>
          ) : null}
        </div>
      ))}
      {!bugs.length ? (
        <div style={{ fontSize: 12, color: V2_TEXT_TERTIARY, marginTop: 8 }}>无产品 bug 记录</div>
      ) : null}
      {filtered.length ? (
        <div style={{ marginTop: 14 }}>
          <div style={{ fontSize: 13, fontWeight: 600 }}>非产品缺陷通道（已按分类过滤）</div>
          {filtered.map((f, i) => (
            <div key={`${f.scenario_id}-${i}`} style={{ borderTop: `1px solid ${V2_HAIRLINE}`, padding: '8px 0' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
                <V2Pill tone="muted">{f.classification || '未分类'}</V2Pill>
                <span className="v2-mono" style={{ fontSize: 12.5, fontWeight: 600 }}>{f.scenario_id}</span>
              </div>
              {f.evidence_summary ? (
                <div style={{ fontSize: 12, color: V2_TEXT_TERTIARY, whiteSpace: 'pre-wrap', marginTop: 3 }}>
                  {f.evidence_summary}
                </div>
              ) : null}
            </div>
          ))}
        </div>
      ) : null}
    </div>
  );
}

/** 截图页签（失败截图清单 + 点击放大，URL 同现产静态路由）。 */
function ShotPane({ d }: { d: SpecDetail }) {
  const shots = d.screenshots || [];
  if (!shots.length) {
    return (
      <div data-proto-id="sd-shots" style={{ padding: '18px 0', fontSize: 12, color: V2_TEXT_TERTIARY }}>
        暂无测试截图
      </div>
    );
  }
  return (
    <div data-proto-id="sd-shots" style={{ padding: '18px 0' }}>
      <div style={{ fontSize: 12, color: V2_TEXT_TERTIARY, marginBottom: 10 }}>
        共 {shots.length} 张截图（点击放大）
      </div>
      <Image.PreviewGroup
        items={shots.map((s) => ({ src: screenshotUrl(d.project, d.name, s.file), alt: s.file }))}
      >
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 12 }}>
          {shots.map((s) => (
            <Image
              key={s.file}
              src={screenshotUrl(d.project, d.name, s.file)}
              alt={s.file}
              width={150}
              height={100}
              style={{ objectFit: 'cover', border: `1px solid ${V2_HAIRLINE}`, borderRadius: 6, cursor: 'pointer' }}
            />
          ))}
        </div>
      </Image.PreviewGroup>
    </div>
  );
}

const HOOK_STATUS_TONE: Record<string, string> = { success: 'good', failure: 'critical', noop: 'muted', skipped: 'muted' };
const HOOK_STATUS_LABEL: Record<string, string> = { success: '成功', failure: '失败', noop: '无操作', skipped: '跳过' };

/** Hook 页签（spec 作用域 hook 审计事件，端点同现产 getHookAudit；移动形态
 * 六列表转堆叠卡——越界治理布局优先）。 */
function HookPane({ project, spec, mobile }: { project: string; spec: string; mobile?: boolean }) {
  const [data, setData] = useState<HookAuditData | null>(null);
  const [error, setError] = useState('');
  useEffect(() => {
    let alive = true;
    getHookAudit(project, spec, 20)
      .then((res) => {
        if (alive) {
          setData(res);
          setError('');
        }
      })
      .catch((e) => {
        if (alive) setError(e instanceof Error ? e.message : String(e));
      });
    return () => {
      alive = false;
    };
  }, [project, spec]);
  if (error) return <div style={{ padding: '18px 0', color: V2_ERROR, fontSize: 12.5 }}>hook 审计加载失败：{error}</div>;
  if (!data) return <div style={{ padding: '18px 0' }}><Spin size="small" /></div>;
  const rows = data.audit || [];
  if (!rows.length) {
    return <div style={{ padding: '18px 0', fontSize: 12, color: V2_TEXT_TERTIARY }}>暂无 hook 审计记录</div>;
  }
  if (mobile) {
    return (
      <div data-proto-id="sd-hooks" style={{ padding: '18px 0' }}>
        {rows.map((r) => (
          <div
            key={`${r.ts}-${r.event}-${r.hook_id || ''}`}
            style={{ borderTop: `1px solid ${V2_HAIRLINE}`, padding: '9px 0' }}
          >
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
              <span className="v2-mono" style={{ fontSize: 12.5, fontWeight: 600 }}>{r.event}</span>
              <V2Pill tone={HOOK_STATUS_TONE[r.status] || 'muted'}>{HOOK_STATUS_LABEL[r.status] || r.status}</V2Pill>
              <span className="v2-num" style={{ fontSize: 12, color: V2_TEXT_QUATERNARY, marginLeft: 'auto' }}>
                {fmtTime(r.ts)}
              </span>
            </div>
            <div className="v2-num" style={{ fontSize: 12, color: V2_TEXT_TERTIARY, marginTop: 3 }}>
              {r.action || '—'}
              {r.duration_ms != null ? ` · ${r.duration_ms}ms` : ''}
            </div>
            {r.detail ? (
              <div style={{ fontSize: 12, color: V2_TEXT_TERTIARY, whiteSpace: 'pre-wrap', marginTop: 3 }}>
                {r.detail}
              </div>
            ) : null}
          </div>
        ))}
      </div>
    );
  }
  return (
    <div data-proto-id="sd-hooks" style={{ padding: '18px 0' }}>
      <Table
        dataSource={rows}
        rowKey={(r) => `${r.ts}-${r.event}-${r.hook_id || ''}`}
        pagination={false}
        size="middle"
        columns={[
          {
            title: '时间',
            dataIndex: 'ts',
            width: 150,
            render: (v: string) => <span className="v2-num" style={{ fontSize: 12 }}>{fmtTime(v)}</span>,
          },
          { title: '事件', dataIndex: 'event', width: 130, render: (v: string) => <span className="v2-mono" style={{ fontSize: 12.5 }}>{v}</span> },
          { title: '动作', dataIndex: 'action', width: 110, render: (v: string) => <span className="v2-mono" style={{ fontSize: 12.5 }}>{v}</span> },
          {
            title: '结果',
            dataIndex: 'status',
            width: 90,
            render: (v: string) => <V2Pill tone={HOOK_STATUS_TONE[v] || 'muted'}>{HOOK_STATUS_LABEL[v] || v}</V2Pill>,
          },
          {
            title: '耗时',
            dataIndex: 'duration_ms',
            width: 90,
            align: 'right',
            render: (v?: number) => <span className="v2-num" style={{ fontSize: 12 }}>{v != null ? `${v}ms` : '—'}</span>,
          },
          {
            title: '明细',
            dataIndex: 'detail',
            render: (v?: string) => (
              <span style={{ fontSize: 12, color: V2_TEXT_TERTIARY, whiteSpace: 'pre-wrap' }}>{v || '—'}</span>
            ),
          },
        ]}
      />
    </div>
  );
}

export default function V2SpecDetailPage() {
  const { name = '', spec = '' } = useParams<{ name: string; spec: string }>();
  const navigate = useNavigate();
  const { message, modal } = App.useApp();
  const mobile = useV2IsMobile();
  const [detail, setDetail] = useState<SpecDetail | null>(null);
  const [summary, setSummary] = useState<SpecSummary | null>(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const seqRef = useRef(0);

  const load = useCallback(async () => {
    const seq = ++seqRef.current;
    try {
      // frozen / cancelled_hold 判定字段只在列表端点 SpecSummary 下发（详情
      // SpecDetail 无该字段），附带拉一次列表按名对齐，失败不阻断详情本体
      const [d, listRes] = await Promise.all([
        getSpecDetail(name, spec),
        getSpecs(name).catch(() => null),
      ]);
      if (seq !== seqRef.current) return;
      setDetail(d);
      setSummary(listRes?.specs.find((s) => s.name === spec) || null);
      setError('');
    } catch (e) {
      if (seq !== seqRef.current) return;
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      if (seq === seqRef.current) setLoading(false);
    }
  }, [name, spec]);

  useEffect(() => {
    void load();
    const hb = setInterval(() => void load(), HEARTBEAT_MS);
    return () => {
      clearInterval(hb);
      seqRef.current += 1;
    };
  }, [load]);

  const runAction = async (label: string, fn: () => Promise<unknown>, opts?: { confirm?: string; okTitle?: string }) => {
    const exec = async () => {
      setBusy(true);
      try {
        await fn();
        message.success(`${opts?.okTitle || label}指令已发送`);
        await load();
      } catch (e) {
        message.error(`${label}失败：${e instanceof Error ? e.message : String(e)}`);
      } finally {
        setBusy(false);
      }
    };
    if (opts?.confirm) {
      modal.confirm({
        title: opts.okTitle || label,
        content: opts.confirm,
        okText: opts.okTitle || label,
        okButtonProps: { danger: label.includes('删除') },
        cancelText: '取消',
        onOk: exec,
      });
    } else {
      await exec();
    }
  };

  const reviewBlocked =
    detail?.status === 'blocked' &&
    SPEC_REVIEW_BLOCKED_PREFIXES.some((p) => (detail.error || '').startsWith(p));
  const terminal = detail ? TERMINAL_STATUSES.has(detail.status || '') : true;
  const frozen = summary?.frozen ?? false;
  const cancelledHold = summary?.cancelled_hold ?? false;

  const transitionItems = useMemo<MenuProps['items']>(() => {
    if (!detail) return [];
    const items: MenuProps['items'] = [];
    if (cancelledHold) items.push({ key: 'resume', label: '恢复运行（取消保持态）' });
    if (frozen) items.push({ key: 'unfreeze', label: '解冻' });
    if (!frozen && !terminal) items.push({ key: 'freeze', label: '冻结' });
    if (detail.status === 'drafted') items.push({ key: 'promote', label: '晋升 ready' });
    if (reviewBlocked) items.push({ key: 're-review', label: '重新评审' });
    if (detail.error) items.push({ key: 'clear-error', label: '清除错误' });
    if (items.length) items.push({ type: 'divider' });
    items.push({ key: 'delete', label: '删除 SPEC', danger: true });
    return items;
  }, [detail, reviewBlocked, terminal, frozen, cancelledHold]);

  const onTransition = (key: string) => {
    if (!detail) return;
    if (key === 'resume') {
      void runAction('恢复运行', () => resumeSpec(name, spec), {
        confirm: '将复位 ready 并保留分支续做（无可保留分支时降级全新重派）。',
        okTitle: '恢复运行',
      });
    } else if (key === 'unfreeze') {
      void runAction('解冻', () => unfreezeSpec(name, spec));
    } else if (key === 'freeze') {
      void runAction('冻结', () => freezeSpec(name, spec), {
        confirm: '冻结将停止该 SPEC 的在跑 agent 并暂停调度。',
      });
    } else if (key === 'promote') {
      void runAction('晋升 ready', () => promoteSpec(name, spec), {
        confirm: '对草案执行软化 + lint 预检 + 状态转移 ready。',
        okTitle: '晋升',
      });
    } else if (key === 're-review') {
      void runAction('重新评审', () => reReviewSpec(name, spec), {
        confirm: '将 SPEC 转回 reviewing 重开方案评审（开放条件由后端校验）。',
      });
    } else if (key === 'clear-error') {
      void runAction('清除错误', () => clearSpecError(name, spec));
    } else if (key === 'delete') {
      void runAction('删除 SPEC', () => deleteSpec(name, spec), {
        confirm: '将从项目中删除该 SPEC 目录，不可撤销。',
        okTitle: '删除',
      });
    }
  };

  const modeLabel = detail?.mode ? (detail.mode === 'fast-track' ? '快速模式' : '完整模式') : null;

  // 移动形态（prototype/m-spec-detail.html sd-titlebar + D4 头部按钮收敛）：
  // 标题 17px 换行收纳，移除「状态转移」「更多操作」两入口（冻结/删除等对应
  // 动作由列表页/桌面端承载）；页签转短标签。
  const rightActions = mobile ? undefined : (
    <div style={{ display: 'flex', gap: 8 }}>
      <Dropdown
        menu={{ items: transitionItems, onClick: ({ key }) => onTransition(key) }}
        placement="bottomRight"
        trigger={['click']}
      >
        <Button size="small" loading={busy}>状态转移</Button>
      </Dropdown>
      <Dropdown
        menu={{
          items: [
            { key: 'doc', label: '查看文档' },
            { key: 'topo', label: '协作拓扑' },
          ],
          onClick: ({ key }) => {
            if (key === 'doc') navigate(`/projects/${encodeURIComponent(name)}/${encodeURIComponent(spec)}`);
            if (key === 'topo')
              navigate(`/projects/${encodeURIComponent(name)}/${encodeURIComponent(spec)}/topology`);
          },
        }}
        placement="bottomRight"
        trigger={['click']}
      >
        <Button type="text" size="small" aria-label="更多操作">
          <svg width={14} height={14} viewBox="0 0 14 14" fill="currentColor" aria-hidden>
            <circle cx={2.6} cy={7} r={1.2} />
            <circle cx={7} cy={7} r={1.2} />
            <circle cx={11.4} cy={7} r={1.2} />
          </svg>
        </Button>
      </Dropdown>
    </div>
  );

  // 富标题（2026-11-06 用户指令「v2 页标题收编全站统一标题栏控件」，同现产
  // SPEC 详情页 D6 整体迁移习语）：SPEC 名 + 模式/状态胶囊作为 ReactNode 整体
  // 传入 PageTitleBar title 槽位，控件对富节点透明不拆解；原 V2TitleBand
  // children（胶囊行）并入本节点随迁。移动端 17px 收纳排布保留。
  //
  // 中文标题下方行（2026-11-06 用户指令「中文标题放在英文标题下方」）：组合
  // 「中文标题 · branch」作为块级第二行收进富标题内部（同列表名称列副标题行
  // 形态：次级字号/色/单行省略），不经 subtitle 槽——槽位行尾跟随是概览等页
  // 副标题形态，详情中文标题要的是确定性换行位置，不随宽度漂移。组合语义
  // 仍单源 combineSpecSubtitle（branch 空只显中文标题、title 空维持 branch
  // 单独显示、双空不渲染）；移动端隐藏（同 subtitle 槽既有规则，页级 gate）。
  //
  // 两列结构（同日用户指令「模式/状态标签垂直居中」实测落地：初版把胶囊留在
  // 首行内只互相对齐，量测胶囊簇中心 21px vs 标题栏中心 28px 偏高 7px）——
  // 左列（英文名+中文下方行）、右簇（胶囊行）分列，外层 alignItems center
  // 使右簇随标题块整体取中；窄视口外层 wrap 右簇下坠（同旧 wrap 形态）。
  const chineseTitle = combineSpecSubtitle(detail?.title, detail?.branch);
  const richTitle = (
    <span style={{ display: 'flex', alignItems: 'center', flexWrap: 'wrap', columnGap: 10, rowGap: 2, minWidth: 0 }}>
      <span style={{ display: 'block', minWidth: 0 }}>
        <span
          className="v2-ellipsis"
          style={{
            display: 'block',
            fontSize: mobile ? 17 : 20,
            fontWeight: 700,
            letterSpacing: -0.3,
            lineHeight: '28px',
          }}
        >
          {spec}
        </span>
        {!mobile && chineseTitle ? (
          <span
            style={{
              display: 'block',
              fontSize: 12,
              fontWeight: 400,
              color: V2_TEXT_TERTIARY,
              // 贴排（2026-11-06 用户指令「中文与英文标题之间的间隔缩小」）：
              // 零外边距 + 行高收紧 14px，只留行盒固有半行距
              lineHeight: '14px',
              // 定宽技巧：width 0 使本行不参与左列 max-content 定宽（列宽只由
              // 英文名决定，右簇胶囊紧跟英文名不被中文行宽度推开），minWidth
              // 100% 再撑回列宽、超出即省略
              width: 0,
              minWidth: '100%',
              whiteSpace: 'nowrap',
              overflow: 'hidden',
              textOverflow: 'ellipsis',
            }}
          >
            {chineseTitle}
          </span>
        ) : null}
      </span>
      {/* 右簇移动端不渲染（2026-11-06 用户指令「移动端设备样式中只显示标题」
          ——中文下方行既有移动端隐藏同门），桌面随标题块整体垂直居中 */}
      {!mobile ? (
        <span style={{ display: 'inline-flex', alignItems: 'center', gap: 10, flexShrink: 0 }}>
          {modeLabel ? <V2Pill tone="muted">{modeLabel}</V2Pill> : null}
          {detail ? <V2StatusPill status={detail.status} /> : null}
          {frozen ? <V2Pill tone="warning">已冻结</V2Pill> : null}
          {cancelledHold ? <V2Pill tone="warning">取消保持</V2Pill> : null}
        </span>
      ) : null}
    </span>
  );

  return (
    // 页标题经 V2Page titleBar 槽位落统一标题栏（standalone 与移动端均由顶栏
    // 承载，embed 行壳位满宽贴顶）；返回箭头/rightActions（状态转移/更多操作，
    // 移动端豁免）随迁 back / filters 槽位。
    <V2Page
      titleBar={
        <PageTitleBar
          title={richTitle}
          back={() => navigate(`/v2/projects/${encodeURIComponent(name)}`)}
          filters={rightActions}
        />
      }
    >
      {error ? (
        <Alert type="error" showIcon message="SPEC 详情加载失败" description={error} />
      ) : null}
      {loading && !detail ? (
        <div className="v2-bento" style={{ padding: 48, textAlign: 'center' }}>
          <Spin size="large" />
        </div>
      ) : detail ? (
        <>
          <InfoCard d={detail} mobile={mobile} />
          <TaskCard d={detail} mobile={mobile} />
          <div
            className="v2-bento"
            data-proto-id="sd-panel"
            style={{ marginTop: 16, padding: mobile ? '4px 12px 16px' : '4px 22px 16px' }}
          >
            <Tabs
              defaultActiveKey="timeline"
              items={
                mobile
                  ? [
                      { key: 'timeline', label: '时间轴', children: <TimelinePane d={detail} /> },
                      { key: 'scenarios', label: '场景', children: <ScenarioPane d={detail} mobile={mobile} /> },
                      { key: 'bugs', label: 'Bug', children: <BugPane d={detail} /> },
                      { key: 'shots', label: `截图 ${(detail.screenshots || []).length}` , children: <ShotPane d={detail} /> },
                      { key: 'hooks', label: 'Hook', children: <HookPane project={name} spec={spec} mobile={mobile} /> },
                    ]
                  : [
                      { key: 'timeline', label: '运行时间轴', children: <TimelinePane d={detail} /> },
                      { key: 'scenarios', label: '场景结果', children: <ScenarioPane d={detail} /> },
                      { key: 'bugs', label: 'Bug 列表', children: <BugPane d={detail} /> },
                      { key: 'shots', label: '测试截图', children: <ShotPane d={detail} /> },
                      { key: 'hooks', label: 'Hook', children: <HookPane project={name} spec={spec} /> },
                    ]
              }
            />
          </div>
        </>
      ) : null}
    </V2Page>
  );
}
