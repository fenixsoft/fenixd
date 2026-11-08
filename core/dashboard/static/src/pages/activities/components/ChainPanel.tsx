/**
 * 处置链页签（原 /chain 独立页迁入运维页三页签，2026-11-05 用户指令）
 *
 * Admin→Arbiter→Human 自动处置链的观测面：在办件 / 队列（人工队列）/
 * 配额水位 / 上升件四区块。数据源 /api/chain（data/admin_alerts.py
 * chain_overview 单读聚合）；项目筛选 Select 由宿主页（activities）在统一
 * 标题栏 filters 槽位渲染，本组件只持有数据与轮询。
 *
 * 只读纪律：本面板零写动作——链状态只由链运行时与管理配置通道（设置页链
 * 配置区块）演进，视图不得提供任何变更入口。30s 轮询对齐人观测频率；
 * 页签失活即卸载，轮询随卸载自动停止。
 */
import { Alert, Card, Col, Empty, Progress, Row, Spin, Table, Tag, Tooltip, Typography } from 'antd';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { getChainOverview } from '@/services/dashboard';
import type {
  ChainEscalationItem,
  ChainInFlightItem,
  ChainOverviewData,
  ChainSignatureQuota,
} from '@/services/dashboard';
import { fmtDate } from '@/components/alert-shared';
import { useIsMobile } from '@/hooks/useIsMobile';

// 轮询周期：与设置页链配置热更新（30s）同拍——观测面无需更快
const REFRESH_MS = 30_000;

const PHASE_META: Record<string, { label: string; color: string }> = {
  admin: { label: 'Admin 处置中', color: 'blue' },
  arbiter: { label: 'Arbiter 调查中', color: 'purple' },
};

const GRANULARITY_META: Record<string, { label: string; color: string }> = {
  spec: { label: 'SPEC', color: 'geekblue' },
  subject: { label: '主体键', color: 'cyan' },
  type: { label: '类型级', color: 'default' },
};

const CLOSE_CAUSE_META: Record<string, { label: string; color: string }> = {
  'closed-by-chain': { label: '链闭环收口', color: 'green' },
  migrated: { label: '存量迁移收口', color: 'blue' },
};

function severityTag(sev?: string) {
  const color = sev === 'critical' ? 'red' : sev === 'major' ? 'orange' : 'gold';
  return <Tag color={color}>{(sev || 'minor').toUpperCase()}</Tag>;
}

/** 签名展示主体：spec 归属优先，spec=null 回落主体键（类型级显式标注） */
function subjectLabel(row: { spec?: string; subject?: string; granularity: string }) {
  if (row.granularity === 'subject') return row.subject || '(主体键缺失)';
  if (row.granularity === 'type') return '(类型级)';
  return row.spec || '(未知)';
}

export default function ChainPanel({
  project,
}: {
  /** 单项目聚合筛选（宿主页持有并同步到标题栏 Select，undefined=全部项目） */
  project?: string;
}) {
  const isMobile = useIsMobile();
  const [data, setData] = useState<ChainOverviewData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  // fix 43351def1296: load 自增请求序号——project 变化时 useEffect 重建轮询，
  // 旧项目的在飞请求可能晚于新项目响应落地，过期响应直接丢弃不落状态，
  // 防旧项目链在办/配额/上升件覆盖当前筛选（activities 页 loadSeqRef 同款口径）
  const loadSeqRef = useRef(0);

  const load = useCallback(async (name?: string) => {
    const seq = ++loadSeqRef.current;
    try {
      const view = await getChainOverview(name);
      if (seq !== loadSeqRef.current) return;
      // fix 6fe630a044a7: 服务端对 ?project 指向不存在/未就绪项目返回**有意 200**
      // 错误体 {"error": "project not found"}（alert_routes.py _api_chain 契约、
      // ChainOverviewData.error 注释均声明「调用方按 error 分支」）——直接落盘会
      // 渲染成全「—」统计格与空态文案，误导用户以为链上确无数据。走既有错误
      // 横幅（「处置链刷新失败：」前缀）透出并保留上一帧数据（catch 分支同款
      // fail-soft），不清屏
      if (view.error) {
        setError(view.error);
        return;
      }
      setData(view);
      setError('');
    } catch (err) {
      // 观测面 fail-soft（command-center useScreen 同款口径）：刷新失败保留
      // 上一帧数据仅置 error，由页首内联 Alert 透出，不静默吞掉
      // 过期请求的失败同样不落状态，防旧项目错误横幅盖掉新项目数据
      if (seq !== loadSeqRef.current) return;
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      // fix 6e3faa904945: 收尾置 false 同样纳入序号守卫（activities/index.tsx
      // fix 9fc948945fc7 同款口径）——旧请求不得抢在并发新请求之前撤加载指示
      if (seq === loadSeqRef.current) setLoading(false);
    }
  }, []);

  useEffect(() => {
    // fix 6e3faa904945: project 切换重建轮询时置加载反馈——重拉期间 Spin 转、
    // 旧项目数据不再持续可见（序号守卫只保证不落盘，不保证视觉中性）。
    // 30s 轮询重拉不置 true，防周期性闪烁；挂载时与初始 state true 重复赋值
    // 由 React 同值 bailout 吸收
    setLoading(true);
    load(project);
    const timer = setInterval(() => load(project), REFRESH_MS);
    return () => clearInterval(timer);
  }, [load, project]);

  const summary = data?.summary;
  const total = data?.total;

  // null 指标占位口径（command-center shared.ts fmtMetric 同款）：数据未到
  // （data=null，首载未到或请求失败）统计格显「—」——0 与「口径不可得」
  // 语义不同，MUST NOT 显示 0；total/summary 字段级缺失（服务端代差）同显「—」
  // fix 3151a7bf4b1f: 字段级缺失兜底链收敛为统一「—」占位，不再漏渲染空 span
  const stats = useMemo(
    () => [
      { title: '链在办', value: data ? (total?.in_flight ?? summary?.in_flight ?? '—') : '—' },
      { title: '人工队列', value: data ? (total?.queue ?? summary?.queue ?? '—') : '—' },
      { title: '签名水位', value: data ? (total?.signatures ?? summary?.signatures ?? '—') : '—' },
      { title: '配额耗尽', value: data ? (total?.quota_exhausted ?? summary?.quota_exhausted ?? '—') : '—' },
      { title: '上升件', value: data ? (total?.escalations ?? summary?.escalations ?? '—') : '—' },
    ],
    [data, summary, total],
  );

  const inFlightColumns = [
    {
      title: '链 ID',
      dataIndex: 'chain_id',
      width: 220,
      render: (v: string) => <Typography.Text code>{v || '—'}</Typography.Text>,
    },
    { title: '项目', dataIndex: 'project', width: 120, render: (v?: string) => v || '—' },
    {
      title: 'SPEC / 主体',
      dataIndex: 'spec',
      render: (v?: string | null) => v || '(主体键/类型级)',
    },
    { title: '签名', dataIndex: 'signature', ellipsis: true, render: (v: string) => <Typography.Text code>{v}</Typography.Text> },
    {
      title: '阶段',
      dataIndex: 'phase',
      width: 130,
      render: (v: string) => {
        const meta = PHASE_META[v] || { label: v || '—', color: 'default' };
        return <Tag color={meta.color}>{meta.label}</Tag>;
      },
    },
    { title: '入链时刻', dataIndex: 'started_at', width: 180, render: (v?: string) => fmtDate(v) },
  ];

  const quotaColumns = [
    {
      title: 'SPEC / 主体',
      key: 'subject',
      render: (_: unknown, row: ChainSignatureQuota) => (
        <span>
          {subjectLabel(row)}{' '}
          <Tag color={GRANULARITY_META[row.granularity]?.color || 'default'}>
            {GRANULARITY_META[row.granularity]?.label || row.granularity}
          </Tag>
        </span>
      ),
    },
    { title: '项目', dataIndex: 'project', width: 110, render: (v?: string) => v || '—' },
    {
      title: 'Admin 尝试',
      key: 'admin',
      width: 170,
      render: (_: unknown, row: ChainSignatureQuota) => (
        // fix 32f03ff150b6: cap 缺失（服务端代差/数据损坏）回落 attempts 原值或「—」，不渲染「N/undefined」
        <Progress
          percent={row.admin_cap ? Math.min(100, Math.round((row.admin_attempts / row.admin_cap) * 100)) : 0}
          size="small"
          status={row.admin_attempts >= row.admin_cap ? 'exception' : 'normal'}
          format={() => (row.admin_cap != null ? `${row.admin_attempts}/${row.admin_cap}` : `${row.admin_attempts ?? '—'}`)}
        />
      ),
    },
    {
      title: 'Arbiter 拍板',
      key: 'arbiter',
      width: 170,
      render: (_: unknown, row: ChainSignatureQuota) => (
        // fix 32f03ff150b6: cap 缺失（服务端代差/数据损坏）回落 rulings 原值或「—」，不渲染「N/undefined」
        <Progress
          percent={row.arbiter_cap ? Math.min(100, Math.round((row.arbiter_rulings / row.arbiter_cap) * 100)) : 0}
          size="small"
          status={row.arbiter_rulings >= row.arbiter_cap ? 'exception' : 'normal'}
          format={() => (row.arbiter_cap != null ? `${row.arbiter_rulings}/${row.arbiter_cap}` : `${row.arbiter_rulings ?? '—'}`)}
        />
      ),
    },
    {
      title: '水位',
      dataIndex: 'exhausted',
      width: 110,
      render: (exhausted: boolean) =>
        exhausted ? <Tag color="red">配额耗尽</Tag> : <Tag color="green">余量可用</Tag>,
    },
    {
      title: '最近出现',
      dataIndex: 'last_seen',
      width: 170,
      render: (v?: string) => <Tooltip title={v || ''}>{fmtDate(v)}</Tooltip>,
    },
    {
      title: '末次 SPEC 状态',
      dataIndex: 'last_spec_status',
      width: 130,
      render: (v?: string) => v || '—',
    },
  ];

  const escalationColumns = [
    { title: 'SPEC', dataIndex: 'spec', width: 160, render: (v?: string | null) => v || '(主体键/类型级)' },
    { title: '项目', dataIndex: 'project', width: 110, render: (v?: string) => v || '—' },
    {
      title: '信号',
      dataIndex: 'signal_type',
      width: 180,
      render: (v?: string, row?: ChainEscalationItem) => (
        <span>
          {severityTag(row?.severity)} <Typography.Text code>{v || '—'}</Typography.Text>
        </span>
      ),
    },
    { title: '描述', dataIndex: 'description', ellipsis: true },
    {
      title: '状态',
      key: 'state',
      width: 150,
      render: (_: unknown, row: ChainEscalationItem) =>
        row.handled ? (
          <Tag color={CLOSE_CAUSE_META[row.close_cause || '']?.color || 'green'}>
            {CLOSE_CAUSE_META[row.close_cause || '']?.label || '已收口'}
          </Tag>
        ) : (
          <Tag color="volcano">待人工</Tag>
        ),
    },
    { title: '签名', dataIndex: 'chain', ellipsis: true, render: (v?: { signature?: string }) => <Typography.Text code>{v?.signature || '—'}</Typography.Text> },
    { title: '时间', dataIndex: 'created', width: 170, render: (v?: string) => fmtDate(v) },
  ];

  // 移动端直接行呈现（2026-11-07 运维页移动定稿移植，prototype/m-ops.html r2
  // ops-chain-table 四段堆叠卡形态）：统计磁贴隐藏（计数进段标题），桌面表格
  // 转堆叠行——多列观测表窄屏无收缩点（mono 长 ID），越界治理布局优先；
  // 段名对齐原型（在飞链/签名配额/人工队列/升级件），桌面磁贴+表格形态不变
  if (isMobile) {
    const inFlight = data?.in_flight || [];
    const quotas = data?.signatures || [];
    const queue = data?.queue || [];
    const escalations = data?.escalations || [];
    const rowHair = (i: number) => (i ? { borderTop: '1px solid #f0f0f0' } : undefined);
    const metaStyle = { fontSize: 12, color: 'rgba(0,0,0,0.45)' } as const;
    const escRow = (r: ChainEscalationItem, i: number) => (
      <div key={r.id} style={{ ...rowHair(i), padding: '9px 0' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
          <span style={{ fontSize: 13, fontWeight: 600, flex: 1, minWidth: 0 }}>
            {severityTag(r.severity)} {r.signal_type || '—'}
          </span>
          {r.handled ? (
            <Tag style={{ marginInlineEnd: 0 }} color={CLOSE_CAUSE_META[r.close_cause || '']?.color || 'green'}>
              {CLOSE_CAUSE_META[r.close_cause || '']?.label || '已收口'}
            </Tag>
          ) : (
            <Tag style={{ marginInlineEnd: 0 }} color="volcano">待人工</Tag>
          )}
        </div>
        {r.description ? (
          <div style={{ ...metaStyle, marginTop: 3, whiteSpace: 'pre-wrap' }}>{r.description}</div>
        ) : null}
        <div style={{ ...metaStyle, marginTop: 3 }}>{[r.project || '—', fmtDate(r.created)].join(' · ')}</div>
      </div>
    );
    return (
      <Spin spinning={loading}>
        {error ? (
          <Alert style={{ marginBottom: 12 }} type="warning" showIcon message={`处置链刷新失败：${error}`} />
        ) : null}
        <div style={{ fontSize: 13, fontWeight: 600, margin: '0 0 10px' }}>在飞链 {inFlight.length}</div>
        {inFlight.length ? (
          inFlight.map((r, i) => (
            <div key={r.chain_id || r.signature || `in-flight-${i}`} style={{ ...rowHair(i), padding: '9px 0' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
                <Typography.Text code style={{ fontSize: 12.5, flex: 1, minWidth: 0 }} ellipsis>
                  {r.chain_id || '—'}
                </Typography.Text>
                <span style={{ ...metaStyle, flexShrink: 0 }}>{fmtDate(r.started_at)}</span>
              </div>
              <div style={{ ...metaStyle, marginTop: 3, wordBreak: 'break-all' }}>
                {[r.project || '—', r.spec || '(主体键/类型级)', r.phase ? PHASE_META[r.phase]?.label || r.phase : '']
                  .filter(Boolean)
                  .join(' · ')}
              </div>
            </div>
          ))
        ) : (
          <div style={{ ...metaStyle, paddingBottom: 12 }}>链上无在办件</div>
        )}
        <div style={{ fontSize: 13, fontWeight: 600, margin: '16px 0 10px' }}>签名配额 {quotas.length}</div>
        {quotas.length ? (
          quotas.map((r, i) => (
            <div key={r.signature} style={{ ...rowHair(i), padding: '9px 0' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
                <Typography.Text code style={{ fontSize: 12.5, flex: 1, minWidth: 0 }} ellipsis>
                  {subjectLabel(r)}
                </Typography.Text>
                <Tag style={{ marginInlineEnd: 0 }} color={GRANULARITY_META[r.granularity]?.color || 'default'}>
                  {GRANULARITY_META[r.granularity]?.label || r.granularity}
                </Tag>
                {r.exhausted ? (
                  <Tag style={{ marginInlineEnd: 0 }} color="red">配额耗尽</Tag>
                ) : (
                  <Tag style={{ marginInlineEnd: 0 }} color="green">余量可用</Tag>
                )}
              </div>
              <div style={{ ...metaStyle, marginTop: 3, wordBreak: 'break-all' }}>
                {[r.project, `Admin ${r.admin_attempts}/${r.admin_cap}`, `Arbiter ${r.arbiter_rulings}/${r.arbiter_cap}`, fmtDate(r.last_seen)]
                  .filter(Boolean)
                  .join(' · ')}
              </div>
            </div>
          ))
        ) : (
          <div style={{ ...metaStyle, paddingBottom: 12 }}>暂无签名配额记录</div>
        )}
        <div style={{ fontSize: 13, fontWeight: 600, margin: '16px 0 10px' }}>人工队列 {queue.length}</div>
        {queue.length ? queue.map((r, i) => escRow(r, i)) : (
          <div style={{ ...metaStyle, paddingBottom: 12 }}>链终点零待人工件——链内闭环即全闭环</div>
        )}
        <div style={{ fontSize: 13, fontWeight: 600, margin: '16px 0 10px' }}>升级件 {escalations.length}</div>
        {escalations.length ? escalations.map((r, i) => escRow(r, i)) : (
          <div style={{ ...metaStyle, paddingBottom: 12 }}>无链关联上升件</div>
        )}
      </Spin>
    );
  }

  return (
    <>
      <Spin spinning={loading}>
        {/* 刷新失败保留旧数据 + 内联 Alert（command-center 各屏同款形态） */}
        {error ? (
          <Alert style={{ marginBottom: 12 }} type="warning" showIcon message={`处置链刷新失败：${error}`} />
        ) : null}
        <Row gutter={16}>
          {stats.map((s) => (
            <Col key={s.title} xs={12} sm={8} md={4} lg={4} style={{ marginBottom: 16 }}>
              <Card size="small">
                <Card.Meta
                  title={<span style={{ fontSize: 13, color: 'rgba(0,0,0,0.45)' }}>{s.title}</span>}
                  description={<span style={{ fontSize: 24, fontWeight: 600 }}>{s.value}</span>}
                />
              </Card>
            </Col>
          ))}
        </Row>

        <Card size="small" title={`链在办（${data?.in_flight?.length ?? 0}）`} style={{ marginBottom: 16 }}>
          <Table<ChainInFlightItem>
            // fix 76072bbd6819: chain_id/signature 双空（链状态 JSON 损坏的历史
            // 数据不可信）时兜底 index 键，防 undefined key 触发 duplicate/missing
            // key 告警与行复用异常
            rowKey={(r, i) => r.chain_id || r.signature || `in-flight-${i}`}
            size="small"
            columns={inFlightColumns}
            dataSource={data?.in_flight || []}
            pagination={false}
            locale={{ emptyText: <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="链上无在办件" /> }}
          />
        </Card>

        <Card size="small" title={`配额水位（${data?.signatures?.length ?? 0}）`} style={{ marginBottom: 16 }}>
          <Table<ChainSignatureQuota>
            rowKey="signature"
            size="small"
            columns={quotaColumns}
            dataSource={data?.signatures || []}
            pagination={false}
            locale={{ emptyText: <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无签名配额记录" /> }}
          />
        </Card>

        <Card size="small" title={`人工队列（${data?.queue?.length ?? 0}）`} style={{ marginBottom: 16 }}>
          <Table<ChainEscalationItem>
            rowKey="id"
            size="small"
            columns={escalationColumns}
            dataSource={data?.queue || []}
            pagination={false}
            locale={{ emptyText: <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="链终点零待人工件——链内闭环即全闭环" /> }}
          />
        </Card>

        <Card size="small" title={`上升件全量（${data?.escalations?.length ?? 0}）`}>
          <Table<ChainEscalationItem>
            rowKey="id"
            size="small"
            columns={escalationColumns}
            dataSource={data?.escalations || []}
            pagination={false}
            locale={{ emptyText: <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="无链关联上升件" /> }}
          />
        </Card>
      </Spin>
    </>
  );
}
