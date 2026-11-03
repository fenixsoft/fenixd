/**
 * 处置链视图（add-escalation-chain-admin-arbiter 5.2，只读）
 *
 * Admin→Arbiter→Human 自动处置链的观测面：在办件 / 队列（人工队列）/
 * 配额水位 / 上升件四区块。数据源 /api/chain（data/admin_alerts.py
 * chain_overview 单读聚合）；缺省跨项目聚合，可切单项目。
 *
 * 只读纪律：本页零写动作——链状态只由链运行时与管理配置通道（设置页链
 * 配置区块）演进，视图不得提供任何变更入口。30s 轮询对齐人观测频率。
 */
import { PageContainer } from '@ant-design/pro-components';
import { Card, Col, Empty, Progress, Row, Select, Spin, Table, Tag, Tooltip, Typography } from 'antd';
import { useCallback, useEffect, useMemo, useState } from 'react';
import { useModel } from '@umijs/max';
import { getChainOverview } from '@/services/dashboard';
import type {
  ChainEscalationItem,
  ChainInFlightItem,
  ChainOverviewData,
  ChainSignatureQuota,
} from '@/services/dashboard';
import { fmtDate } from '@/components/alert-shared';

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

export default function ChainPage() {
  const [data, setData] = useState<ChainOverviewData | null>(null);
  const [loading, setLoading] = useState(true);
  const [project, setProject] = useState<string | undefined>(undefined);
  // 项目选择器选项取全局 initialState.projects（选定单项目后聚合分支的
  // projects 字段不再下发，避免选项列表被自身响应掏空）
  const { initialState } = useModel('@@initialState');
  const projectOptions = initialState?.projects || [];

  const load = useCallback(async (name?: string) => {
    try {
      const view = await getChainOverview(name);
      setData(view);
    } catch {
      // 观测面 fail-soft：请求失败保留上一帧数据，仅停 spinner
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    setLoading(true);
    load(project);
    const timer = setInterval(() => load(project), REFRESH_MS);
    return () => clearInterval(timer);
  }, [load, project]);

  const summary = data?.summary;
  const total = data?.total;

  const stats = useMemo(
    () => [
      { title: '链在办', value: total ? total.in_flight : summary?.in_flight ?? 0 },
      { title: '人工队列', value: total ? total.queue : summary?.queue ?? 0 },
      { title: '签名水位', value: total ? total.signatures : summary?.signatures ?? 0 },
      { title: '配额耗尽', value: total ? total.quota_exhausted : summary?.quota_exhausted ?? 0 },
      { title: '上升件', value: total ? total.escalations : summary?.escalations ?? 0 },
    ],
    [summary, total],
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
        <Progress
          percent={row.admin_cap ? Math.min(100, Math.round((row.admin_attempts / row.admin_cap) * 100)) : 0}
          size="small"
          status={row.admin_attempts >= row.admin_cap ? 'exception' : 'normal'}
          format={() => `${row.admin_attempts}/${row.admin_cap}`}
        />
      ),
    },
    {
      title: 'Arbiter 拍板',
      key: 'arbiter',
      width: 170,
      render: (_: unknown, row: ChainSignatureQuota) => (
        <Progress
          percent={row.arbiter_cap ? Math.min(100, Math.round((row.arbiter_rulings / row.arbiter_cap) * 100)) : 0}
          size="small"
          status={row.arbiter_rulings >= row.arbiter_cap ? 'exception' : 'normal'}
          format={() => `${row.arbiter_rulings}/${row.arbiter_cap}`}
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

  return (
    <PageContainer
      header={{ title: '处置链', subTitle: 'Admin → Arbiter → Human 自动处置链观测（只读）' }}
      extra={[
        <Select
          key="project"
          allowClear
          placeholder="全部项目"
          style={{ minWidth: 200 }}
          value={project}
          onChange={(v) => setProject(v)}
          options={projectOptions.map((name) => ({ value: name, label: name }))}
        />,
      ]}
    >
      <Spin spinning={loading}>
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
            rowKey={(r) => r.chain_id || r.signature}
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
    </PageContainer>
  );
}
