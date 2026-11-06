// /v2/activities — v2 运维页（redesign-dashboard-v2-ui 2.6）。
//
// 页签与数据口径对齐现产 /activities 三页签（2026-11-05 处置链并入后的原版；
// 2026-11-06 用户指令「页签与原版一致、数据正确加载」）：处置链（缺省，
// URL ?tab= 预选）/ 自动运维记录 / 告警记录。视觉保持 v2 Bento 壳（UI 真相源
// prototype/ops.html）；原型的「自愈记录」占位页签随本次对齐退役——自动运维
// 记录消费真实端点 /api/admin-activities（服务端分页同原版 15/页），原
// 「暂无数据端点」占位声明作废。处置链块序亦对齐原版（在飞链 / 签名配额 /
// 人工队列 / 升级件），人工队列块为本次补齐（原实现漏渲染 queue 分面）。
// 叙述字段（summary 等）以 pre-wrap 纯文本呈现——v2 域不引 react-markdown
//（与其余五页一致），数据字段与原版一一对应不缺列。
import { Alert, Pagination, Select, Spin, Table, Tabs } from 'antd';
import type { ColumnsType } from 'antd/es/table';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useModel } from '@umijs/max';
import dayjs from 'dayjs';
import AdminRunModal from '@/pages/activities/components/AdminRunModal';
import { PageTitleBar } from '@/components/PageTitleBar';
import { getAdminActivities, getAlerts, getChainOverview } from '@/services/dashboard';
import type {
  ActivityItem,
  AdminActivitiesData,
  AlertsData,
  ChainEscalationItem,
  ChainInFlightItem,
  ChainOverviewData,
  ChainSignatureQuota,
} from '@/services/dashboard';
import { fmtDate } from '@/components/alert-shared';
import { HEARTBEAT_MS } from '@/utils/refreshPolicy';
import { V2AlertRows } from './AlertList';
import { V2Page, V2Pill } from './shared';
import {
  useV2IsMobile,
  V2_HAIRLINE,
  V2_TEXT,
  V2_TEXT_QUATERNARY,
  V2_TEXT_SECONDARY,
  V2_TEXT_TERTIARY,
  V2_TONE,
} from './theme';

/** 自动运维记录服务端分页页大小（对齐原版 /activities PAGE_SIZE 单源语义） */
const PAGE_SIZE = 15;

const SEV_LABEL: Record<string, string> = { critical: '严重', major: '较重', minor: '轻微', info: '提示' };
const SEV_TONE: Record<string, string> = { critical: 'critical', major: 'warning', minor: 'muted', info: 'muted' };

/** 信号类型 → 中文标签（与原版 /activities SIGNAL_LABEL 同源词表） */
const SIGNAL_LABEL: Record<string, string> = {
  blocked_stuck: '阻塞滞留',
  stuck: '卡滞',
  flapping: '状态抖动',
  dispatch_stalled: '派发停滞',
  merge_streak: '合并反复失败',
  'manual-intervention': '人工介入',
  repeated_failures: '连续失败',
  verify_fail_escalation: '验证失败升级',
  ready_stuck: '就绪滞留',
  family_explosion: 'SPEC 族爆炸',
  daemon_errors: '守护进程异常',
  stash_pop_conflict: '合并冲突改动滞留',
  mergeback_wip_overlap: '合并被主树改动阻塞',
  verify_uniform_failure: '全场景同因失败',
};

/** 处置结果 → v2 胶囊（与原版 RESULT_META 同源词表，色值落 V2_TONE）；
 *  未收录自由文本按关键词配色兜底（与原版同语义）。 */
function resultPill(result?: string) {
  if (!result) return null;
  const meta: Record<string, string> = {
    resolved: 'good',
    'partially-resolved': 'warning',
    escalated: 'critical',
    failed: 'critical',
    interrupted: 'critical',
    pending: 'muted',
    'in-progress': 'info',
    diagnosed: 'info',
  };
  const label: Record<string, string> = {
    resolved: '已解决',
    'partially-resolved': '部分解决',
    escalated: '已升级',
    failed: '失败',
    interrupted: '已中断',
    pending: '处置中',
    'in-progress': '进行中',
    diagnosed: '已诊断',
  };
  const lower = result.toLowerCase();
  if (meta[lower]) return <V2Pill tone={meta[lower]}>{label[lower]}</V2Pill>;
  let tone = 'muted';
  if (lower.includes('成功') || lower.includes('success')) tone = 'good';
  else if (lower.includes('失败') || lower.includes('fail') || lower.includes('error')) tone = 'critical';
  else if (lower.includes('处理') || lower.includes('handled')) tone = 'info';
  return <V2Pill tone={tone}>{result}</V2Pill>;
}

/** 分页响应的 projects[] 平铺回全局单数组并排序（handled===false 置顶 →
 *  created 倒序，与原版 /activities 同语义；非法 created 归一 0 防 NaN）。 */
function flattenActivities(data: AdminActivitiesData | null): ActivityItem[] {
  const out: ActivityItem[] = [];
  for (const p of data?.projects ?? []) {
    for (const a of p.activities ?? []) {
      out.push({ ...a, project: a.project || p.name });
    }
  }
  return out.sort((x, y) => {
    if (x.handled === false && y.handled !== false) return -1;
    if (x.handled !== false && y.handled === false) return 1;
    const xt = x.created && dayjs(x.created).isValid() ? dayjs(x.created).valueOf() : 0;
    const yt = y.created && dayjs(y.created).isValid() ? dayjs(y.created).valueOf() : 0;
    return yt - xt;
  });
}

/** 头部统计条（真实口径五项：待处理告警 / 在飞链 / 人工队列 / 升级中 /
 *  配额耗尽，对齐原版五统计卡；链摘要取 summary ?? total——跨项目聚合分支
 *  无 summary 键、总额在 total）。 */
function StatRow({ alerts, chain }: { alerts: AlertsData | null; chain: ChainOverviewData | null }) {
  const sum = chain?.summary ?? chain?.total;
  const stats: Array<[string, number | null]> = [
    ['待处理告警', alerts ? (alerts.total_unhandled ?? alerts.alerts?.length ?? 0) : null],
    ['在飞链', sum?.in_flight ?? null],
    ['人工队列', sum?.queue ?? null],
    ['升级中', sum?.escalations ?? null],
    ['配额耗尽', sum?.quota_exhausted ?? null],
  ];
  return (
    <div style={{ display: 'flex', gap: 14, marginTop: 4, flexWrap: 'wrap' }}>
      {stats.map(([label, v]) => (
        <span key={label} className="v2-num" style={{ fontSize: 12, color: V2_TEXT_TERTIARY }}>
          {label}{' '}
          <span style={{ fontWeight: 600, color: (v ?? 0) > 0 ? V2_TEXT : V2_TEXT_TERTIARY, fontSize: 13 }}>
            {v ?? '—'}
          </span>
        </span>
      ))}
    </div>
  );
}

function AlertPane({
  alerts,
  resolved,
  resolvedOpen,
  onToggleResolved,
  onChanged,
}: {
  alerts: NonNullable<AlertsData['alerts']>;
  resolved: NonNullable<AlertsData['resolved']>;
  resolvedOpen: boolean;
  onToggleResolved: () => void;
  onChanged: () => void;
}) {
  const empty = !alerts.length && !resolved.length;
  if (empty) {
    return (
      <div style={{ padding: '20px 10px', fontSize: 12.5, color: V2_TEXT_TERTIARY }}>
        暂无人工告警。
      </div>
    );
  }
  return (
    <div style={{ paddingTop: 6 }}>
      {alerts.length ? (
        <div className="v2-bento" data-proto-id="ops-alert-list" style={{ padding: '6px 6px 4px' }}>
          <V2AlertRows alerts={alerts} onChanged={onChanged} />
        </div>
      ) : (
        <div style={{ padding: '8px 10px 4px', fontSize: 12.5, color: V2_TEXT_TERTIARY }}>暂无未处理告警。</div>
      )}
      {resolved.length ? (
        <div style={{ borderTop: `1px solid ${V2_HAIRLINE}`, margin: '4px 8px 0', paddingTop: 4 }}>
          <a
            role="button"
            tabIndex={0}
            onClick={onToggleResolved}
            style={{ fontSize: 12, color: V2_TEXT_QUATERNARY, display: 'inline-block', padding: '4px 2px' }}
          >
            {resolvedOpen ? '收起已解决' : `已解决 ${resolved.length} 条`}
          </a>
          {resolvedOpen
            ? resolved.map((a) => (
                <div key={a.id} style={{ display: 'flex', gap: 10, padding: '7px 2px', alignItems: 'baseline' }}>
                  <V2Pill tone="good">已解决</V2Pill>
                  <span style={{ fontSize: 12.5, minWidth: 0, flex: 1 }}>{a.description || a.id}</span>
                  <span className="v2-num" style={{ fontSize: 12, color: V2_TEXT_QUATERNARY, flexShrink: 0 }}>
                    {a.handled_at ? dayjs(a.handled_at).format('MM-DD HH:mm') : ''}
                  </span>
                </div>
              ))
            : null}
        </div>
      ) : null}
    </div>
  );
}

/** 上升件/人工队列共用行集（两者同为 ChainEscalationItem；桌面表格与移动
 *  堆叠卡双形态，升级件全量与人工队列复用同一渲染）。 */
function EscCards({ rows }: { rows: ChainEscalationItem[] }) {
  return (
    <>
      {rows.map((r, i) => (
        <div key={`${r.id}-${i}`} style={{ borderTop: `1px solid ${V2_HAIRLINE}`, padding: '9px 0' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
            <span style={{ fontSize: 13, fontWeight: 600, flex: 1, minWidth: 0 }}>{r.signal_type || r.id}</span>
            <V2Pill tone={SEV_TONE[r.severity || ''] || 'muted'}>{SEV_LABEL[r.severity || ''] || r.severity || '—'}</V2Pill>
            {r.handled ? <V2Pill tone="good">已处理</V2Pill> : <V2Pill tone="warning">待处理</V2Pill>}
          </div>
          {r.description ? (
            <div style={{ fontSize: 12, color: V2_TEXT_TERTIARY, marginTop: 3, whiteSpace: 'pre-wrap' }}>
              {r.description}
            </div>
          ) : null}
          <div className="v2-num" style={{ fontSize: 12, color: V2_TEXT_QUATERNARY, marginTop: 3 }}>
            {r.project || '—'}
            {r.created ? ` · ${dayjs(r.created).format('MM-DD HH:mm')}` : ''}
          </div>
        </div>
      ))}
    </>
  );
}

function ChainPane({
  chain,
  chainError,
  mobile,
}: {
  chain: ChainOverviewData | null;
  chainError?: string;
  mobile?: boolean;
}) {
  if (!chain) {
    return (
      <div style={{ padding: 32, textAlign: 'center' }}>
        <Spin />
      </div>
    );
  }
  const error = chainError || chain.error;
  if (error) {
    return (
      <Alert type="warning" showIcon style={{ margin: '16px 0' }} message="处置链视图未就绪" description={error} />
    );
  }

  // 移动形态（prototype/m-ops.html ops-chain「卡片列表随实现展开」）：四块
  // 观测表转堆叠卡——多列观测表窄屏无收缩点（mono 长 ID），越界治理布局优先。
  if (mobile) {
    return (
      <div data-proto-id="ops-chain-table" style={{ padding: '16px 0 4px' }}>
        <div style={{ fontSize: 13, fontWeight: 600, margin: '0 0 10px' }}>在飞链 {chain.in_flight.length}</div>
        {chain.in_flight.length ? (
          chain.in_flight.map((r) => (
            <div key={r.chain_id} style={{ borderTop: `1px solid ${V2_HAIRLINE}`, padding: '9px 0' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
                <span className="v2-mono v2-ellipsis" style={{ fontSize: 12.5, fontWeight: 600, flex: 1, minWidth: 0 }}>
                  {r.chain_id}
                </span>
                <span className="v2-num" style={{ fontSize: 12, color: V2_TEXT_QUATERNARY }}>
                  {r.started_at ? dayjs(r.started_at).format('MM-DD HH:mm') : '—'}
                </span>
              </div>
              <div className="v2-num" style={{ fontSize: 12, color: V2_TEXT_TERTIARY, marginTop: 3, wordBreak: 'break-all' }}>
                {r.project || '—'}
                {r.spec ? ` · ${r.spec}` : ''}
                {r.phase ? ` · ${r.phase}` : ''}
              </div>
            </div>
          ))
        ) : (
          <div style={{ fontSize: 12, color: V2_TEXT_TERTIARY, paddingBottom: 12 }}>暂无在飞处置链</div>
        )}
        <QuotaCards rows={chain.signatures} />
        <div style={{ fontSize: 13, fontWeight: 600, margin: '16px 0 10px' }}>人工队列 {chain.queue.length}</div>
        {chain.queue.length ? (
          <EscCards rows={chain.queue} />
        ) : (
          <div style={{ fontSize: 12, color: V2_TEXT_TERTIARY, paddingBottom: 12 }}>
            链终点零待人工件——链内闭环即全闭环
          </div>
        )}
        <div style={{ fontSize: 13, fontWeight: 600, margin: '16px 0 10px' }}>升级件 {chain.escalations.length}</div>
        {chain.escalations.length ? (
          <EscCards rows={chain.escalations} />
        ) : (
          <div style={{ fontSize: 12, color: V2_TEXT_TERTIARY, paddingBottom: 12 }}>暂无升级件</div>
        )}
      </div>
    );
  }

  const flightCols: ColumnsType<ChainInFlightItem> = [
    {
      title: '链 ID',
      dataIndex: 'chain_id',
      render: (v: string) => <span className="v2-mono" style={{ fontSize: 12.5, fontWeight: 600 }}>{v}</span>,
    },
    { title: '项目', dataIndex: 'project', width: 130, render: (v?: string) => v || '—' },
    { title: 'SPEC', dataIndex: 'spec', width: 220, render: (v?: string | null) => v || '—' },
    { title: '阶段', dataIndex: 'phase', width: 170, render: (v: string) => <span style={{ fontSize: 12.5 }}>{v}</span> },
    {
      title: '开始',
      dataIndex: 'started_at',
      width: 130,
      align: 'right',
      render: (v?: string) => (
        <span className="v2-num" style={{ fontSize: 12, color: V2_TEXT_TERTIARY }}>
          {v ? dayjs(v).format('MM-DD HH:mm') : '—'}
        </span>
      ),
    },
  ];

  const escCols: ColumnsType<ChainEscalationItem> = [
    {
      title: '信号',
      dataIndex: 'signal_type',
      render: (v: string | undefined, r) => (
        <div style={{ minWidth: 0 }}>
          <div style={{ fontSize: 13, fontWeight: 600 }}>{v || r.id}</div>
          {r.description ? (
            <div style={{ fontSize: 12, color: V2_TEXT_TERTIARY, marginTop: 2, whiteSpace: 'pre-wrap' }}>
              {r.description}
            </div>
          ) : null}
        </div>
      ),
    },
    { title: '项目', dataIndex: 'project', width: 120, render: (v?: string) => v || '—' },
    {
      title: '级别',
      dataIndex: 'severity',
      width: 90,
      render: (v?: string) => <V2Pill tone={SEV_TONE[v || ''] || 'muted'}>{SEV_LABEL[v || ''] || v || '—'}</V2Pill>,
    },
    {
      title: '状态',
      key: 'state',
      width: 100,
      render: (_, r) =>
        r.handled ? <V2Pill tone="good">已处理</V2Pill> : <V2Pill tone="warning">待处理</V2Pill>,
    },
    {
      title: '时间',
      dataIndex: 'created',
      width: 120,
      align: 'right',
      render: (v?: string) => (
        <span className="v2-num" style={{ fontSize: 12, color: V2_TEXT_TERTIARY }}>
          {v ? dayjs(v).format('MM-DD HH:mm') : '—'}
        </span>
      ),
    },
  ];

  const quotaCols: ColumnsType<ChainSignatureQuota> = [
    {
      title: '签名',
      dataIndex: 'signature',
      render: (v: string, r) => (
        <span className="v2-mono" style={{ fontSize: 12.5 }}>
          {v}
          {r.spec ? <span style={{ color: V2_TEXT_TERTIARY }}> · {r.spec}</span> : null}
        </span>
      ),
    },
    { title: '粒度', dataIndex: 'granularity', width: 90, render: (v: string) => <V2Pill tone="muted">{v}</V2Pill> },
    {
      title: 'Admin',
      key: 'admin',
      width: 110,
      align: 'right',
      render: (_, r) => (
        <span className="v2-num" style={{ fontSize: 12.5 }}>
          {r.admin_attempts}/{r.admin_cap}
        </span>
      ),
    },
    {
      title: 'Arbiter',
      key: 'arbiter',
      width: 110,
      align: 'right',
      render: (_, r) => (
        <span className="v2-num" style={{ fontSize: 12.5 }}>
          {r.arbiter_rulings}/{r.arbiter_cap}
        </span>
      ),
    },
    {
      title: '状态',
      dataIndex: 'exhausted',
      width: 110,
      render: (v: boolean) => (v ? <V2Pill tone="critical">配额耗尽</V2Pill> : <V2Pill tone="good">余量正常</V2Pill>),
    },
    {
      title: '最近出现',
      dataIndex: 'last_seen',
      width: 120,
      align: 'right',
      render: (v?: string) => (
        <span className="v2-num" style={{ fontSize: 12, color: V2_TEXT_TERTIARY }}>
          {v ? dayjs(v).format('MM-DD HH:mm') : '—'}
        </span>
      ),
    },
  ];

  return (
    <div data-proto-id="ops-chain-table" style={{ padding: '16px 0 4px' }}>
      <div style={{ fontSize: 13, fontWeight: 600, margin: '0 0 10px' }}>在飞链 {chain.in_flight.length}</div>
      {chain.in_flight.length ? (
        <Table columns={flightCols} dataSource={chain.in_flight} rowKey="chain_id" pagination={false} size="middle" />
      ) : (
        <div style={{ fontSize: 12, color: V2_TEXT_TERTIARY, paddingBottom: 12 }}>暂无在飞处置链</div>
      )}
      <div style={{ fontSize: 13, fontWeight: 600, margin: '16px 0 10px' }}>签名配额 {chain.signatures.length}</div>
      {chain.signatures.length ? (
        <Table columns={quotaCols} dataSource={chain.signatures} rowKey={(r) => `${r.signature}-${r.spec || r.subject || ''}`} pagination={false} size="middle" />
      ) : (
        <div style={{ fontSize: 12, color: V2_TEXT_TERTIARY, paddingBottom: 12 }}>暂无签名配额记录</div>
      )}
      <div style={{ fontSize: 13, fontWeight: 600, margin: '16px 0 10px' }}>人工队列 {chain.queue.length}</div>
      {chain.queue.length ? (
        <Table columns={escCols} dataSource={chain.queue} rowKey="id" pagination={false} size="middle" />
      ) : (
        <div style={{ fontSize: 12, color: V2_TEXT_TERTIARY, paddingBottom: 12 }}>
          链终点零待人工件——链内闭环即全闭环
        </div>
      )}
      <div style={{ fontSize: 13, fontWeight: 600, margin: '16px 0 10px' }}>升级件 {chain.escalations.length}</div>
      {chain.escalations.length ? (
        <Table columns={escCols} dataSource={chain.escalations} rowKey="id" pagination={false} size="middle" />
      ) : (
        <div style={{ fontSize: 12, color: V2_TEXT_TERTIARY }}>暂无升级件</div>
      )}
    </div>
  );
}

/** 签名配额移动堆叠卡（ChainPane 移动分支复用；桌面走 quotaCols 表格）。 */
function QuotaCards({ rows }: { rows: ChainSignatureQuota[] }) {
  return (
    <>
      <div style={{ fontSize: 13, fontWeight: 600, margin: '16px 0 10px' }}>签名配额 {rows.length}</div>
      {rows.length ? (
        rows.map((r, i) => (
          <div key={`${r.signature}-${r.spec || r.subject || ''}-${i}`} style={{ borderTop: `1px solid ${V2_HAIRLINE}`, padding: '9px 0' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
              <span className="v2-mono v2-ellipsis" style={{ fontSize: 12.5, flex: 1, minWidth: 0 }}>
                {r.signature}
              </span>
              <V2Pill tone="muted">{r.granularity}</V2Pill>
              {r.exhausted ? <V2Pill tone="critical">配额耗尽</V2Pill> : <V2Pill tone="good">余量正常</V2Pill>}
            </div>
            <div className="v2-num" style={{ fontSize: 12, color: V2_TEXT_TERTIARY, marginTop: 3, wordBreak: 'break-all' }}>
              {r.spec ? `${r.spec} · ` : ''}Admin {r.admin_attempts}/{r.admin_cap} · Arbiter {r.arbiter_rulings}/{r.arbiter_cap}
              {r.last_seen ? ` · ${dayjs(r.last_seen).format('MM-DD HH:mm')}` : ''}
            </div>
          </div>
        ))
      ) : (
        <div style={{ fontSize: 12, color: V2_TEXT_TERTIARY }}>暂无签名配额记录</div>
      )}
    </>
  );
}

/** 自动运维记录单条卡（v2 形态）：时间/项目/SPEC/信号/结果/需人工决策一行 +
 *  失败原因 + 叙述 + 处置/建议，字段与原版 ActivityCard 一一对应；「查看处置
 *  过程」开 AdminRunModal（原版同源组件）。 */
function ActivityCard({ a, onViewRun }: { a: ActivityItem; onViewRun: (a: ActivityItem) => void }) {
  const unhandled = a.handled === false;
  return (
    <div data-testid="v2-activity-card" style={{ borderTop: `1px solid ${V2_HAIRLINE}`, padding: '11px 2px' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
        <span className="v2-num" style={{ fontSize: 12, color: V2_TEXT_QUATERNARY }}>
          {fmtDate(a.created)}
        </span>
        {a.project ? <V2Pill tone="muted">{a.project}</V2Pill> : null}
        {a.spec ? <V2Pill tone="info">{a.spec}</V2Pill> : null}
        {a.signal_type ? <V2Pill tone="aqua">{SIGNAL_LABEL[a.signal_type] || a.signal_type}</V2Pill> : null}
        {resultPill(a.result)}
        {unhandled ? <V2Pill tone="critical">需人工决策</V2Pill> : null}
        <span style={{ flex: 1 }} />
        {a.admin_run_id && a.project ? (
          <a className="touch-expand" style={{ fontSize: 12 }} onClick={() => onViewRun(a)}>
            查看处置过程
          </a>
        ) : null}
      </div>
      {a.error ? (
        <div style={{ fontSize: 12.5, color: V2_TONE.critical[0], marginTop: 5, whiteSpace: 'pre-wrap' }}>
          失败原因：{a.error}
        </div>
      ) : null}
      {a.summary ? (
        <div style={{ fontSize: 12.5, lineHeight: '20px', color: V2_TEXT, marginTop: a.error || unhandled ? 6 : 5, whiteSpace: 'pre-wrap' }}>
          {a.summary}
        </div>
      ) : (
        <div style={{ fontSize: 12.5, color: V2_TEXT_TERTIARY, marginTop: 5 }}>
          {`（无叙述总结）处置：${a.actions_taken || '—'} · 结果：${a.result || '—'}`}
        </div>
      )}
      {a.actions_taken ? (
        <div style={{ fontSize: 12.5, color: V2_TEXT_SECONDARY, marginTop: 4, whiteSpace: 'pre-wrap' }}>
          <span style={{ color: V2_TEXT_TERTIARY }}>处置：</span>
          {a.actions_taken}
        </div>
      ) : null}
      {a.recommended_action ? (
        <div style={{ fontSize: 12.5, color: V2_TEXT_SECONDARY, marginTop: 4, whiteSpace: 'pre-wrap' }}>
          <span style={{ color: V2_TEXT_TERTIARY }}>建议：</span>
          {a.recommended_action}
        </div>
      ) : null}
    </div>
  );
}

function ActivityPane({
  loading,
  data,
  current,
  onPageChange,
  onViewRun,
}: {
  loading: boolean;
  data: AdminActivitiesData | null;
  current: number;
  onPageChange: (page: number) => void;
  onViewRun: (a: ActivityItem) => void;
}) {
  if (loading && !data) {
    return (
      <div style={{ padding: 32, textAlign: 'center' }}>
        <Spin />
      </div>
    );
  }
  const activities = flattenActivities(data);
  if (!activities.length) {
    return (
      <div style={{ padding: '20px 10px', fontSize: 12.5, color: V2_TEXT_TERTIARY }}>
        暂无运维记录。
      </div>
    );
  }
  const total = data?.total ?? activities.length;
  return (
    <div data-proto-id="ops-auto" style={{ paddingTop: 6 }}>
      <div className="v2-bento" style={{ padding: '4px 12px 10px' }}>
        {activities.map((a) => (
          <ActivityCard key={a.id} a={a} onViewRun={onViewRun} />
        ))}
      </div>
      {total > PAGE_SIZE ? (
        <div style={{ display: 'flex', justifyContent: 'flex-end', paddingTop: 12 }}>
          <Pagination
            current={current}
            pageSize={PAGE_SIZE}
            total={total}
            onChange={onPageChange}
            showSizeChanger={false}
          />
        </div>
      ) : null}
    </div>
  );
}

// 页签键与缺省/预选语义与原版 /activities 对齐（?tab= 仅认 auto/alert，
// 非法或缺省回退处置链；/chain 老深链重定向落原版页，v2 页同解析保持一致）
type TabKey = 'chain' | 'auto' | 'alert';

function initialTab(): TabKey {
  const tab = new URLSearchParams(window.location.hash.split('?')[1] || '').get('tab');
  return tab === 'auto' || tab === 'alert' ? tab : 'chain';
}

// 加载失败来源（对齐原版 LoadError 口径）：alerts=人工告警接口，
// activities=运维记录接口；两路失败共用一个 state 但横幅按来源区分文案，
// 告警失败不拖垮运维记录渲染（Promise.allSettled 双 settle）
type LoadError = { source: 'alerts' | 'activities'; message: string };

interface ViewingRun {
  project: string;
  spec?: string;
  runId: string;
  harness?: string;
}

export default function V2OpsPage() {
  const [alertsData, setAlertsData] = useState<AlertsData | null>(null);
  const [activities, setActivities] = useState<AdminActivitiesData | null>(null);
  const [chain, setChain] = useState<ChainOverviewData | null>(null);
  const [chainError, setChainError] = useState('');
  const [loadError, setLoadError] = useState<LoadError | null>(null);
  const [loading, setLoading] = useState(true);
  const [resolvedOpen, setResolvedOpen] = useState(true);
  const [activeTab, setActiveTab] = useState<TabKey>(initialTab);
  // 处置链页签的单项目聚合筛选：state 提升宿主页（与原版同口径——Select 在
  // 标题栏槽位渲染，页签切换后筛选保持）
  const [project, setProject] = useState<string | undefined>(undefined);
  // 项目选择器选项取全局 initialState.projects（原版同源口径）
  const { initialState } = useModel('@@initialState');
  const projectOptions: string[] = (initialState?.projects as string[] | undefined) || [];
  const [current, setCurrent] = useState(1);
  const [viewingRun, setViewingRun] = useState<ViewingRun | null>(null);
  const mobile = useV2IsMobile();
  // 服务端分页当前页（ref 供 load 读取最新页码，不经 setState 闭包）
  const pageRef = useRef(1);
  // load 自增请求序号：心跳刷新与翻页触发可能并发在飞，仅最新一次请求落状态
  const loadSeqRef = useRef(0);
  const chainSeqRef = useRef(0);

  const load = useCallback(async () => {
    const seq = ++loadSeqRef.current;
    const pageAtStart = pageRef.current;
    const errMsg = (r: unknown) => (r instanceof Error ? r.message : String(r));
    try {
      const [actRes, alRes] = await Promise.allSettled([
        getAdminActivities(undefined, undefined, pageAtStart, PAGE_SIZE),
        getAlerts(),
      ]);
      if (seq !== loadSeqRef.current) return;
      const alerts: AlertsData =
        alRes.status === 'fulfilled'
          ? alRes.value
          : { alerts: [], error: errMsg(alRes.reason) };
      if (actRes.status === 'rejected') {
        if (!alerts.error) setAlertsData(alerts);
        const actMsg = errMsg(actRes.reason);
        setLoadError({
          source: 'activities',
          message: alerts.error ? `${actMsg}；告警加载失败：${alerts.error}` : actMsg,
        });
        return;
      }
      let d = actRes.value;
      // 总条数收缩导致当前页越界时回退第 1 页重拉一次（与原版 D5 语义一致；
      // 在飞期间用户已翻页则交新请求处理）
      const totalPages = d.total != null ? Math.max(1, Math.ceil(d.total / PAGE_SIZE)) : null;
      if (totalPages != null && pageAtStart > totalPages && pageRef.current === pageAtStart) {
        pageRef.current = 1;
        setCurrent(1);
        d = await getAdminActivities(undefined, undefined, 1, PAGE_SIZE);
        if (seq !== loadSeqRef.current) return;
      }
      setActivities(d);
      if (!alerts.error) {
        setAlertsData(alerts);
        setLoadError(null);
      } else {
        setLoadError({ source: 'alerts', message: alerts.error });
      }
    } catch (e) {
      if (seq !== loadSeqRef.current) return;
      setLoadError({ source: 'activities', message: errMsg(e) });
    } finally {
      if (seq === loadSeqRef.current) setLoading(false);
    }
  }, []);

  // 处置链独立 fail-soft：刷新失败保留上一帧数据仅置 error（原版 ChainPanel
  // 同口径），不与告警/运维记录的加载失败混报
  const loadChain = useCallback(async (name?: string) => {
    const seq = ++chainSeqRef.current;
    try {
      const view = await getChainOverview(name);
      if (seq !== chainSeqRef.current) return;
      setChain(view);
      setChainError('');
    } catch (e) {
      if (seq !== chainSeqRef.current) return;
      setChainError(e instanceof Error ? e.message : String(e));
    }
  }, []);

  useEffect(() => {
    void load();
    void loadChain(project);
    const hb = setInterval(() => {
      void load();
      void loadChain(project);
    }, HEARTBEAT_MS);
    return () => clearInterval(hb);
  }, [load, loadChain, project]);

  const handlePageChange = useCallback(
    (page: number) => {
      pageRef.current = page;
      setCurrent(page);
      void load();
    },
    [load],
  );

  const handleViewRun = useCallback(
    (a: ActivityItem) =>
      setViewingRun({ project: a.project || '', spec: a.spec, runId: a.admin_run_id || '', harness: a.harness }),
    [],
  );

  const alerts = alertsData?.alerts ?? [];
  const resolved = alertsData?.resolved ?? [];

  return (
    <V2Page
      titleBar={
        // 统一标题栏声明（unified-page-title-bar；2026-11-06 用户指令「六页标题
        // 收编统一标题栏控件」）：经 V2Page titleBar 槽位落 .v2-page 直下
        //（overview/projectDetail 同款接法）——行壳位（embed/移动端）标题带满宽
        // 贴顶、sticky 无跳位；自画标题带随本页迁移退役。处置链页签激活
        // 时筛选槽放单项目聚合 Select（state 提升宿主页，跨页签保持）
        <PageTitleBar
          title="运维"
          subtitle={<StatRow alerts={alertsData} chain={chain} />}
          filters={
            activeTab === 'chain' ? (
              <Select
                allowClear
                placeholder="全部项目"
                style={{ minWidth: 200 }}
                value={project}
                onChange={(v) => setProject(v)}
                options={projectOptions.map((name) => ({ value: name, label: name }))}
              />
            ) : undefined
          }
        />
      }
    >
      <div style={{ marginTop: 18 }}>
        {loadError ? (
          <Alert
            type="error"
            showIcon
            style={{ marginBottom: 16 }}
            message={loadError.source === 'alerts' ? '人工告警加载失败' : '运维记录加载失败'}
            description={loadError.message}
          />
        ) : null}
        {loading && !alertsData && !activities ? (
          <div className="v2-bento" style={{ padding: 48, textAlign: 'center' }}>
            <Spin size="large" />
          </div>
        ) : (
          <div
            className="v2-bento"
            data-proto-id="ops-panel"
            style={{ padding: mobile ? '4px 12px 16px' : '4px 16px 16px' }}
          >
            <Tabs
              activeKey={activeTab}
              onChange={(k) => setActiveTab(k as TabKey)}
              items={[
                {
                  key: 'chain',
                  label: '处置链',
                  children: <ChainPane chain={chain} chainError={chainError} mobile={mobile} />,
                },
                {
                  key: 'auto',
                  label: '自动运维记录',
                  children: (
                    <ActivityPane
                      loading={loading}
                      data={activities}
                      current={current}
                      onPageChange={handlePageChange}
                      onViewRun={handleViewRun}
                    />
                  ),
                },
                {
                  key: 'alert',
                  label: '告警记录',
                  children: (
                    <AlertPane
                      alerts={alerts}
                      resolved={resolved}
                      resolvedOpen={resolvedOpen}
                      onToggleResolved={() => setResolvedOpen((o) => !o)}
                      onChanged={() => void load()}
                    />
                  ),
                },
              ]}
            />
          </div>
        )}
      </div>
      {viewingRun && (
        <AdminRunModal
          project={viewingRun.project}
          spec={viewingRun.spec}
          adminRunId={viewingRun.runId}
          harness={viewingRun.harness}
          open={!!viewingRun}
          onClose={() => setViewingRun(null)}
        />
      )}
    </V2Page>
  );
}
