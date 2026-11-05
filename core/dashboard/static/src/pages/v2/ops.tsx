// /v2/activities — v2 运维页（redesign-dashboard-v2-ui 2.6）。
//
// UI 真相源：spec/changes/redesign-dashboard-v2-ui/prototype/ops.html
// （头部统计条 + 三页签磁贴）。数据全部消费既有真实端点：人工告警走
// getAlerts（行渲染复用 v2/shared AlertList——裁决选择题闭环与概览横幅同一
// 组件）、处置链走 getChainOverview（在飞/升级/签名配额三块）、自愈记录在
// 现产无数据端点，占位面板如实声明（原型内 94% 成功率等为示意假数据，按
// null 口径红线不伪装）。
import { Alert, Spin, Table, Tabs } from 'antd';
import type { ColumnsType } from 'antd/es/table';
import { useCallback, useEffect, useState } from 'react';
import dayjs from 'dayjs';
import { getAlerts, getChainOverview } from '@/services/dashboard';
import type {
  AlertsData,
  ChainEscalationItem,
  ChainInFlightItem,
  ChainOverviewData,
  ChainSignatureQuota,
} from '@/services/dashboard';
import { HEARTBEAT_MS } from '@/utils/refreshPolicy';
import { V2AlertRows } from './AlertList';
import { V2Page, V2Pill, V2TitleBand } from './shared';
import { useV2IsMobile, V2_HAIRLINE, V2_TEXT, V2_TEXT_QUATERNARY, V2_TEXT_TERTIARY } from './theme';

/** 头部统计条（真实口径四项：待处理告警 / 在飞链 / 升级中 / 签名配额耗尽）。
 *  链摘要取 summary ?? total（跨项目聚合分支无 summary 键、总额在 total）。 */
function StatRow({ alerts, chain }: { alerts: AlertsData | null; chain: ChainOverviewData | null }) {
  const sum = chain?.summary ?? chain?.total;
  const stats: Array<[string, number | null]> = [
    ['待处理告警', alerts ? (alerts.total_unhandled ?? alerts.alerts?.length ?? 0) : null],
    ['在飞链', sum?.in_flight ?? null],
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

const SEV_LABEL: Record<string, string> = { critical: '严重', major: '较重', minor: '轻微', info: '提示' };
const SEV_TONE: Record<string, string> = { critical: 'critical', major: 'warning', minor: 'muted', info: 'muted' };

function AlertPane({
  alerts,
  onChanged,
}: {
  alerts: NonNullable<AlertsData['alerts']>;
  onChanged: () => void;
}) {
  if (!alerts.length) {
    return (
      <div style={{ padding: '20px 10px', fontSize: 12.5, color: V2_TEXT_TERTIARY }}>
        暂无待处理人工告警。
      </div>
    );
  }
  return (
    <div style={{ paddingTop: 6 }}>
      <div className="v2-bento" data-proto-id="ops-alert-list" style={{ padding: '6px 6px 4px' }}>
        <V2AlertRows alerts={alerts} onChanged={onChanged} />
      </div>
    </div>
  );
}

function ChainPane({ chain, mobile }: { chain: ChainOverviewData | null; mobile?: boolean }) {
  if (!chain) {
    return (
      <div style={{ padding: 32, textAlign: 'center' }}>
        <Spin />
      </div>
    );
  }
  if (chain.error) {
    return (
      <Alert type="warning" showIcon style={{ margin: '16px 0' }} message="处置链视图未就绪" description={chain.error} />
    );
  }

  // 移动形态（prototype/m-ops.html ops-chain「卡片列表随实现展开」）：三块
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
        <div style={{ fontSize: 13, fontWeight: 600, margin: '16px 0 10px' }}>升级件 {chain.escalations.length}</div>
        {chain.escalations.length ? (
          chain.escalations.map((r, i) => (
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
          ))
        ) : (
          <div style={{ fontSize: 12, color: V2_TEXT_TERTIARY, paddingBottom: 12 }}>暂无升级件</div>
        )}
        <div style={{ fontSize: 13, fontWeight: 600, margin: '16px 0 10px' }}>签名配额 {chain.signatures.length}</div>
        {chain.signatures.length ? (
          chain.signatures.map((r, i) => (
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
      <div style={{ fontSize: 13, fontWeight: 600, margin: '16px 0 10px' }}>升级件 {chain.escalations.length}</div>
      {chain.escalations.length ? (
        <Table columns={escCols} dataSource={chain.escalations} rowKey="id" pagination={false} size="middle" />
      ) : (
        <div style={{ fontSize: 12, color: V2_TEXT_TERTIARY, paddingBottom: 12 }}>暂无升级件</div>
      )}
      <div style={{ fontSize: 13, fontWeight: 600, margin: '16px 0 10px' }}>签名配额 {chain.signatures.length}</div>
      {chain.signatures.length ? (
        <Table columns={quotaCols} dataSource={chain.signatures} rowKey={(r) => `${r.signature}-${r.spec || r.subject || ''}`} pagination={false} size="middle" />
      ) : (
        <div style={{ fontSize: 12, color: V2_TEXT_TERTIARY }}>暂无签名配额记录</div>
      )}
    </div>
  );
}

export default function V2OpsPage() {
  const [alertsData, setAlertsData] = useState<AlertsData | null>(null);
  const [chain, setChain] = useState<ChainOverviewData | null>(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);
  const [resolvedOpen, setResolvedOpen] = useState(false);
  const mobile = useV2IsMobile();

  const load = useCallback(async () => {
    try {
      const [al, ch] = await Promise.all([getAlerts(), getChainOverview()]);
      setAlertsData(al);
      setChain(ch);
      setError('');
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
    const hb = setInterval(() => void load(), HEARTBEAT_MS);
    return () => clearInterval(hb);
  }, [load]);

  const alerts = alertsData?.alerts ?? [];
  const resolved = alertsData?.resolved ?? [];

  return (
    <V2Page>
      <V2TitleBand title="运维" subtitle={<StatRow alerts={alertsData} chain={chain} />} />
      <div style={{ marginTop: 18 }}>
        {error ? (
          <Alert type="error" showIcon style={{ marginBottom: 16 }} message="运维数据加载失败" description={error} />
        ) : null}
        {loading && !alertsData ? (
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
              defaultActiveKey="alert"
              items={[
                {
                  key: 'alert',
                  label: `人工告警 (${alerts.length})`,
                  children: (
                    <>
                      <AlertPane alerts={alerts} onChanged={() => void load()} />
                      {resolved.length ? (
                        <div style={{ borderTop: `1px solid ${V2_HAIRLINE}`, margin: '4px 8px 0', paddingTop: 4 }}>
                          <a
                            role="button"
                            tabIndex={0}
                            onClick={() => setResolvedOpen((o) => !o)}
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
                    </>
                  ),
                },
                { key: 'chain', label: '处置链观测', children: <ChainPane chain={chain} mobile={mobile} /> },
                {
                  key: 'auto',
                  label: '自愈记录',
                  children: (
                    <div data-proto-id="ops-auto" style={{ padding: '16px 0' }}>
                      <div style={{ fontSize: 12.5, color: V2_TEXT_TERTIARY }}>
                        自愈记录分面暂无数据端点（陈旧代码自愈触发日志未对 dashboard 下发），本页不渲染估算统计；
                        自愈行为可在 SPEC 时间轴与项目「问题/阻塞」计数中观察。
                      </div>
                    </div>
                  ),
                },
              ]}
            />
          </div>
        )}
      </div>
    </V2Page>
  );
}
