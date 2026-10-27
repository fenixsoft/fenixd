// ExecutionLedger.tsx — 指挥中心「执行台账」屏（add-command-center 4.4）。
//
// KPI 条（四指标 + 网关状态徽标；null 显示「—」非 0——分母零/不可计价的
// 口径语义，specs「KPI 条」Requirement）+ 台账表格（项目/SPEC/车道/结果/
// 耗时/tokens/成本/开始时间/trigger 九列，null 显示「—」）+ 项目筛选
// （与流水线屏同数据源模式：响应 projects 全集 +「全部项目」）。
// KPI 数据独立加载（收件箱裁决成功后经 kpiTick 触发重拉），表格独立加载，
// 互不拖垮。

import { useState } from 'react';
import { Alert, Select, Table, Tag } from 'antd';
import type { ColumnsType } from 'antd/es/table';
import { commandCenterKpi, commandCenterLedger } from '@/services/dashboard';
import type { CommandCenterKpi, CommandCenterLedger, CommandCenterLedgerRow } from '@/services/dashboard';
import { useScreenResource } from './useScreen';
import { ScreenErrorPlaceholder, ScreenLoading } from './ScreenStates';
import {
  PANEL_BORDER,
  TEXT_MAIN,
  TEXT_SUB,
  fmtDurationSeconds,
  fmtMetric,
  fmtRate,
  fmtShortTs,
  fmtTokens,
  fmtUsd,
  laneLabel,
  outcomeBadge,
} from './shared';

const cellStyle: React.CSSProperties = {
  display: 'flex',
  flexDirection: 'column',
  alignItems: 'center',
  minWidth: 90,
  padding: '2px 10px',
};

function KpiCell({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div style={cellStyle}>
      <span style={{ fontSize: 17, fontWeight: 700, color: TEXT_MAIN, lineHeight: 1.3 }}>{value}</span>
      <span style={{ fontSize: 11, color: TEXT_SUB }}>{label}</span>
    </div>
  );
}

/** KPI 条：四指标 + 网关状态徽标（配置态派生，零探测）。 */
function KpiBar({ kpi, kpiError, onRetry }: { kpi: CommandCenterKpi | null; kpiError: string; onRetry: () => void }) {
  if (kpiError && !kpi) {
    return (
      <div
        style={{
          border: `1px solid ${PANEL_BORDER}`,
          borderRadius: 8,
          padding: '10px 14px',
          marginBottom: 12,
          display: 'flex',
          alignItems: 'center',
          gap: 12,
          color: TEXT_SUB,
        }}
      >
        <span>KPI 加载失败：{kpiError}</span>
        <a onClick={onRetry} style={{ color: TEXT_MAIN }}>
          重试
        </a>
      </div>
    );
  }
  const gh = kpi?.gateway_health;
  return (
    <div
      style={{
        display: 'flex',
        flexWrap: 'wrap',
        alignItems: 'center',
        gap: 2,
        border: `1px solid ${PANEL_BORDER}`,
        borderRadius: 8,
        padding: '8px 10px',
        marginBottom: 12,
      }}
    >
      <KpiCell label="7 日交付 SPEC" value={kpi ? kpi.delivered_specs_7d : '—'} />
      <KpiCell label="人工介入率" value={kpi ? fmtRate(kpi.human_intervention_rate_7d) : '—'} />
      <KpiCell label="run 成功率" value={kpi ? fmtRate(kpi.run_success_rate_7d) : '—'} />
      <KpiCell label="单 SPEC 成本" value={kpi ? fmtUsd(kpi.cost_per_spec_7d) : '—'} />
      {gh ? (
        <span style={{ marginLeft: 10 }}>
          <Tag color={gh.configured ? 'green' : 'default'}>
            网关{gh.configured ? '已配置' : '未配置'}
            {gh.configured ? ` · ${gh.providers} provider` : ''}
          </Tag>
        </span>
      ) : null}
    </div>
  );
}

const columns: ColumnsType<CommandCenterLedgerRow> = [
  { title: '项目', dataIndex: 'project', key: 'project', render: (v) => v || '—' },
  {
    title: 'SPEC',
    dataIndex: 'spec',
    key: 'spec',
    render: (v) => v || '—',
  },
  { title: '车道', dataIndex: 'lane', key: 'lane', render: (v) => laneLabel(String(v ?? '')) || '—' },
  {
    title: '结果',
    dataIndex: 'outcome',
    key: 'outcome',
    render: (v) => {
      const b = outcomeBadge(v);
      return <span style={{ color: b.color }}>{b.text}</span>;
    },
  },
  { title: '耗时', dataIndex: 'duration', key: 'duration', render: (v) => fmtDurationSeconds(v) },
  { title: 'tokens', dataIndex: 'tokens', key: 'tokens', render: (v) => fmtTokens(v) },
  { title: '成本', dataIndex: 'cost', key: 'cost', render: (v) => fmtUsd(v) },
  { title: '开始时间', dataIndex: 'started_at', key: 'started_at', render: (v) => fmtShortTs(v) },
  // trigger 为既有调度记录数据缺口（后端口径允许 null 不硬造）
  { title: 'trigger', dataIndex: 'trigger', key: 'trigger', render: (v) => fmtMetric(v) },
];

export default function ExecutionLedger({ active, kpiTick }: { active: boolean; kpiTick: number }) {
  // project='' = 全部项目（与流水线屏同数据源模式）
  const [project, setProject] = useState('');
  const kpi = useScreenResource<CommandCenterKpi>(
    () => commandCenterKpi(project || undefined),
    active,
    // kpiTick=裁决后 KPI 刷新；project=筛选切换即时重拉（BUG-01 同源修复，
    // specs「台账与 KPI 条」Scenario：筛选切到零交付项目后 KPI 换该项目值）
    `${kpiTick}:${project}`,
  );
  const ledger = useScreenResource<CommandCenterLedger>(
    () => commandCenterLedger(project || undefined),
    active,
    // 筛选切换即时重拉（与流水线屏同数据源模式，含同款即时生效语义）
    project,
  );

  const ledgerView = () => {
    if (ledger.error && !ledger.data) {
      return <ScreenErrorPlaceholder error={ledger.error} onRetry={ledger.retry} />;
    }
    if (!ledger.data) return <ScreenLoading hint="执行台账加载中" />;
    return (
      <div>
        {ledger.error ? (
          <Alert style={{ marginBottom: 12 }} type="warning" showIcon message={`执行台账刷新失败：${ledger.error}`} />
        ) : null}
        <Table<CommandCenterLedgerRow>
          size="small"
          rowKey={(r) => `${r.project}/${r.started_at ?? ''}/${r.spec}/${r.lane}`}
          columns={columns}
          dataSource={ledger.data.rows}
          // 单页纯展示（后端台账恒 ≤50 行，specs「执行台账派生」）；不分页
          // ——分页交互不在指挥中心场景集内，不引入未声明交互元素
          pagination={false}
        />
      </div>
    );
  };

  return (
    <div>
      {ledger.data ? (
        <div style={{ display: 'flex', justifyContent: 'flex-end', marginBottom: 12 }}>
          <Select
            value={project}
            onChange={setProject}
            style={{ minWidth: 180 }}
            options={[
              { label: '全部项目', value: '' },
              ...ledger.data.projects.map((p) => ({ label: p, value: p })),
            ]}
          />
        </div>
      ) : null}
      <KpiBar kpi={kpi.data} kpiError={kpi.error} onRetry={kpi.retry} />
      {ledgerView()}
    </div>
  );
}
