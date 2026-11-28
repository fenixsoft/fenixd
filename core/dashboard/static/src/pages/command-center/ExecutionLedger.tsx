// ExecutionLedger.tsx — 指挥中心「执行台账」屏（add-command-center 4.4）。
// 文案经 useIntl/intlText（i18n 修复轮 batch-C：本文件静态中文文案迁 i18n 目录）。
//
// KPI 条（四指标 + 网关状态徽标；null 显示「—」非 0——分母零/不可计价的
// 口径语义，specs「KPI 条」Requirement）+ 台账表格（项目/SPEC/车道/结果/
// 耗时/tokens/成本/开始时间/trigger 九列，null 显示「—」）。项目筛选
// 2026-10-28 上移壳层页签右侧全局下拉（与流水线屏同批），本屏经 props
// 接收。KPI 数据独立加载，表格独立加载，互不拖垮。

import { useEffect, useMemo } from 'react';
import { useIntl } from '@umijs/max';
import { Alert, Button, Spin, Table, Tag } from 'antd';
import type { ColumnsType } from 'antd/es/table';
import { commandCenterKpi, commandCenterLedger } from '@/services/dashboard';
import type { CommandCenterKpi, CommandCenterLedger, CommandCenterLedgerRow } from '@/services/dashboard';
import { useIsMobile } from '@/hooks/useIsMobile';
import { intlText } from '@/utils/intlText';
import { useScreenResource } from './useScreen';
import { ScreenErrorPlaceholder, ScreenLoading } from './ScreenStates';
import {
  CARD_FRAME_BORDER,
  CARD_FRAME_SHADOW,
  METRIC_DIVIDER,
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

// KPI 条错误/加载两个占位框共用容器样式（避免两分支内联字面量漂移）
const kpiBoxStyle: React.CSSProperties = {
  border: `1px solid ${PANEL_BORDER}`,
  borderRadius: 8,
  padding: '10px 14px',
  marginBottom: 12,
  display: 'flex',
  alignItems: 'center',
  gap: 12,
  color: TEXT_SUB,
};

function KpiCell({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div style={cellStyle}>
      <span style={{ fontSize: 17, fontWeight: 700, color: TEXT_MAIN, lineHeight: 1.3 }}>{value}</span>
      <span style={{ fontSize: 11, color: TEXT_SUB }}>{label}</span>
    </div>
  );
}

/** KPI 条：四指标 + 网关状态徽标（配置态派生，零探测）。初载（无 data 且
 * 无 error）显加载占位——「—」专指分母零/不可计价口径，不冒充加载态。
 * 移动分支（prototype/m-ledger.html 定稿 2026-11-07）：单 Bento 磁贴内 2×2
 * 网格（无内分隔线，批注定稿）+ 网关徽标跨列行贴底；桌面保持单条四格。 */
function KpiBar({
  kpi,
  kpiLoading,
  kpiError,
  onRetry,
  isMobile,
}: {
  kpi: CommandCenterKpi | null;
  kpiLoading: boolean;
  kpiError: string;
  onRetry: () => void;
  isMobile?: boolean;
}) {
  const intl = useIntl();
  if (kpiError && !kpi) {
    return (
      <div style={kpiBoxStyle}>
        <span>{intl.formatMessage({ id: 'commandCenter.ledger.kpiLoadFailed' }, { error: kpiError })}</span>
        {/* 重试入口用 antd link Button（原生可聚焦/回车触发，同 ScreenStates
            ScreenErrorPlaceholder 口径）：裸 <a onClick> 无 href/role/tabIndex，
            键盘用户无法触发（code-review e10bff410c11） */}
        <Button type="link" onClick={onRetry} style={{ color: TEXT_MAIN, padding: 0 }}>
          {intl.formatMessage({ id: 'common.retry' })}
        </Button>
      </div>
    );
  }
  // 初载占位（Spin 与 ScreenStates 同款 antd 口径）：数据未到不落「—」。
  // 条件含 `!kpiError` 兜底：useScreenResource 的 loading 初值为 false（进入
  // 激活 effect 才置 true），挂载首帧满足 kpi=null/kpiLoading=false/kpiError=''，
  // 只看 kpiLoading 会漏过此分支直落下方「—」冒充加载态一帧（code-review
  // f56ac0882b7d）；error 分支在前已收走 kpiError 非空且无 data 的形态
  if (!kpi && (kpiLoading || !kpiError)) {
    return (
      <div style={kpiBoxStyle}>
        <Spin size="small" />
        <span style={{ fontSize: 12 }}>{intl.formatMessage({ id: 'commandCenter.ledger.kpiLoading' })}</span>
      </div>
    );
  }
  // 后端对未知项目返回 200+error 字典（routes/command_center_routes.py 有意
  // 兼容契约），useScreenResource 只透传 HTTP 层 error——内嵌 error 字段在此
  // 消费并整条透出，避免错误响应落入各格「—」/空值形态被静默吞掉（code-review
  // 61a3e8ab425a，同 OrgGrid/PipelineBoard data.error 先例）
  if (kpi?.error) {
    return (
      <Alert
        style={{ marginBottom: 12 }}
        type="warning"
        showIcon
        message={intl.formatMessage({ id: 'commandCenter.ledger.kpiQueryFailed' }, { error: kpi.error })}
      />
    );
  }
  const gh = kpi?.gateway_health;
  const gatewayTag = gh ? (
    <Tag color={gh.configured ? 'green' : 'default'}>
      {intl.formatMessage({
        id: gh.configured ? 'commandCenter.ledger.gatewayConfigured' : 'commandCenter.ledger.gatewayNotConfigured',
      })}
      {gh.configured
        ? intl.formatMessage({ id: 'commandCenter.ledger.gatewayProviderCount' }, { count: gh.providers })
        : ''}
    </Tag>
  ) : null;
  if (isMobile) {
    return (
      <div>
        <div
          data-proto-id="cc-m-kpi-grid"
          style={{
            border: `1px solid ${CARD_FRAME_BORDER}`,
            borderRadius: 12,
            boxShadow: CARD_FRAME_SHADOW,
            overflow: 'hidden',
            display: 'grid',
            gridTemplateColumns: '1fr 1fr',
            marginBottom: 8,
          }}
        >
          {(
            [
              ['cc-m-kpi-delivered', kpi ? fmtMetric(kpi.delivered_specs_7d) : '—', intl.formatMessage({ id: 'commandCenter.ledger.kpiDelivered7d' })],
              ['cc-m-kpi-intervention', kpi ? fmtRate(kpi.human_intervention_rate_7d) : '—', intl.formatMessage({ id: 'commandCenter.ledger.kpiInterventionRate' })],
              ['cc-m-kpi-success', kpi ? fmtRate(kpi.run_success_rate_7d) : '—', intl.formatMessage({ id: 'commandCenter.ledger.kpiRunSuccessRate' })],
              ['cc-m-kpi-cost', kpi ? fmtUsd(kpi.cost_per_spec_7d) : '—', intl.formatMessage({ id: 'commandCenter.ledger.kpiCostPerSpec' })],
            ] as Array<[string, string, string]>
          ).map(([anchor, value, label]) => (
            <div key={anchor} data-proto-id={anchor} style={{ padding: '10px 12px' }}>
              <div style={{ fontSize: 20, fontWeight: 700, lineHeight: 1.2, fontVariantNumeric: 'tabular-nums' }}>
                {value}
              </div>
              <div style={{ fontSize: 11, color: TEXT_SUB, marginTop: 2 }}>{label}</div>
            </div>
          ))}
          {/* 与桌面 {gh ? … : null} 同口径：徽标缺席时不渲染跨列行，避免无内容留白 */}
          {gatewayTag ? (
            <div data-proto-id="cc-m-gateway-badge" style={{ gridColumn: '1 / -1', padding: '6px 12px' }}>
              {gatewayTag}
            </div>
          ) : null}
        </div>
        {kpiError ? (
          <Alert
            style={{ marginBottom: 12 }}
            type="warning"
            showIcon
            message={intl.formatMessage({ id: 'commandCenter.ledger.kpiRefreshFailed' }, { error: kpiError })}
          />
        ) : null}
      </div>
    );
  }
  return (
    <div>
      <div
        style={{
          display: 'flex',
          flexWrap: 'wrap',
          alignItems: 'center',
          gap: 2,
          // Bento 磁贴框（2026-11-06 用户指令：卡片框对齐 bento 样式，shared 单源）
          border: `1px solid ${CARD_FRAME_BORDER}`,
          borderRadius: 12,
          boxShadow: CARD_FRAME_SHADOW,
          padding: '8px 10px',
          marginBottom: 12,
        }}
      >
        <KpiCell label={intl.formatMessage({ id: 'commandCenter.ledger.kpiDelivered7d' })} value={kpi ? fmtMetric(kpi.delivered_specs_7d) : '—'} />
        <KpiCell label={intl.formatMessage({ id: 'commandCenter.ledger.kpiInterventionRate' })} value={kpi ? fmtRate(kpi.human_intervention_rate_7d) : '—'} />
        <KpiCell label={intl.formatMessage({ id: 'commandCenter.ledger.kpiRunSuccessRate' })} value={kpi ? fmtRate(kpi.run_success_rate_7d) : '—'} />
        <KpiCell label={intl.formatMessage({ id: 'commandCenter.ledger.kpiCostPerSpec' })} value={kpi ? fmtUsd(kpi.cost_per_spec_7d) : '—'} />
        {gh ? <span style={{ marginLeft: 10 }}>{gatewayTag}</span> : null}
      </div>
      {/* 后台刷新失败保留旧数据（与台账/网格/流水线同口径），内联提示不阻塞视图 */}
      {kpiError ? (
        <Alert
          style={{ marginBottom: 12 }}
          type="warning"
          showIcon
          message={intl.formatMessage({ id: 'commandCenter.ledger.kpiRefreshFailed' }, { error: kpiError })}
        />
      ) : null}
    </div>
  );
}

// 列 title 挂 getter（访问期经 intlText 取文案，antd 渲染读值时求值）；
// batch-C 前为静态中文串。
const columns: ColumnsType<CommandCenterLedgerRow> = [
  { get title() { return intlText('commandCenter.ledger.colProject'); }, dataIndex: 'project', key: 'project', render: (v) => v || '—' },
  {
    title: 'SPEC',
    dataIndex: 'spec',
    key: 'spec',
    render: (v) => v || '—',
  },
  { get title() { return intlText('commandCenter.ledger.colLane'); }, dataIndex: 'lane', key: 'lane', render: (v) => laneLabel(String(v ?? '')) || '—' },
  {
    get title() { return intlText('commandCenter.ledger.colOutcome'); },
    dataIndex: 'outcome',
    key: 'outcome',
    render: (v) => {
      const b = outcomeBadge(v);
      return <span style={{ color: b.color }}>{b.text}</span>;
    },
  },
  { get title() { return intlText('commandCenter.ledger.colDuration'); }, dataIndex: 'duration', key: 'duration', render: (v) => fmtDurationSeconds(v) },
  { title: 'tokens', dataIndex: 'tokens', key: 'tokens', render: (v) => fmtTokens(v) },
  { get title() { return intlText('commandCenter.ledger.colCost'); }, dataIndex: 'cost', key: 'cost', render: (v) => fmtUsd(v) },
  { get title() { return intlText('commandCenter.ledger.colStartedAt'); }, dataIndex: 'started_at', key: 'started_at', render: (v) => fmtShortTs(v) },
  // trigger 为既有调度记录数据缺口（后端口径允许 null 不硬造）；字符串
  // 原样透出、空串同归「—」占位符（fmtMetric 数值口径对字符串恒返「—」，
  // 后端补真实 trigger 值时会被整体吃成占位符——code-review 39e3bca2d260）
  { title: 'trigger', dataIndex: 'trigger', key: 'trigger', render: (v) => v || '—' },
];

export default function ExecutionLedger({
  active,
  project,
  onProjects,
  kpiTick = 0,
}: {
  active: boolean;
  /** 项目筛选：''=全部项目（服务端缺省聚合范围；壳层页签右侧全局下拉注入） */
  project: string;
  /** 项目全集上报（供壳层全局下拉合并）。按数据引用触发：60s 轮询每次
   * 成功即回调（不按内容判等），内容级去重由壳层 reportProjects 落地 */
  onProjects?: (projects: string[]) => void;
  /** 裁决收件箱页签移除后无生产者，保留参数位（默认 0=不触发 KPI 重拉） */
  kpiTick?: number;
}) {
  const intl = useIntl();
  const isMobile = useIsMobile();
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
  // 项目全集上报给壳层（页签右侧全局下拉数据源）。依赖 ledger.data 引用：
  // 轮询每次成功 setData 新对象即触发回调（非「内容变化才回调一次」），
  // 同内容重复上报由壳层 reportProjects 去重（返回旧引用 → React 状态
  // 短路，无多余重渲染）——语义与注释对齐（code-review ad8b0a35cb9f）
  useEffect(() => {
    if (ledger.data?.projects) onProjects?.(ledger.data.projects);
  }, [ledger.data, onProjects]);

  // rowKey 撞键防御：后端台账行无 run 维度唯一标识（aggregate_ledger 投影
  // 丢弃 _run_id，started_at 口径允许 null），project/started_at/spec/lane
  // 四字段拼接在 started_at 缺失或同刻同值时可能重复——按行序首见保留原
  // 键、重复键追加序号；映射在渲染前一次性构建，rowKey 内只查表（无跨
  // 渲染残留的可变状态），以行对象身份为索引与 dataSource 逐行对应
  const ledgerRows = ledger.data?.rows;
  const ledgerRowKeys = useMemo(() => {
    const seen = new Map<string, number>();
    const keys = new Map<CommandCenterLedgerRow, string>();
    (ledgerRows ?? []).forEach((r) => {
      const base = `${r.project}/${r.started_at ?? ''}/${r.spec}/${r.lane}`;
      const n = seen.get(base) ?? 0;
      seen.set(base, n + 1);
      keys.set(r, n === 0 ? base : `${base}#${n}`);
    });
    return keys;
  }, [ledgerRows]);

  const ledgerView = () => {
    if (ledger.error && !ledger.data) {
      return <ScreenErrorPlaceholder error={ledger.error} onRetry={ledger.retry} />;
    }
    if (!ledger.data) return <ScreenLoading hint={intl.formatMessage({ id: 'commandCenter.ledger.loadHint' })} />;
    // 后端对未知项目返回 200+error 字典（routes/command_center_routes.py 有意
    // 兼容契约），useScreenResource 只透传 HTTP 层 error——内嵌 error 字段在此
    // 消费并内联透出，避免错误响应落入台账「暂无数据」空态被静默吞掉（错误体
    // 不带 rows/projects，不得进下方表格渲染）（code-review 61a3e8ab425a，
    // 同 OrgGrid/PipelineBoard data.error 先例）
    if (ledger.data.error) {
      return (
        <Alert
          style={{ marginBottom: 12 }}
          type="warning"
          showIcon
          message={intl.formatMessage({ id: 'commandCenter.ledger.queryFailed' }, { error: ledger.data.error })}
        />
      );
    }
    if (isMobile) {
      // 移动端直接行（prototype/m-ledger.html 定稿 2026-11-07）：九列转三行
      // 结构（SPEC+结果色字 / 项目·车道·trigger / 耗时·tokens·成本·开始时间），
      // 发丝线分隔、无卡壳；null 显「—」；不分页（后端恒 ≤50 行）。桌面表格
      // 形态不变。
      // rows 缺失/非数组兜底（契约漂移 200 响应无 error 字段也不带 rows 时，
      // 直读 rows.length 会抛 TypeError 白屏；桌面分支交 antd Table 无此风险）
      // （code-review d4d18c52f29e）
      const rows: CommandCenterLedgerRow[] = Array.isArray(ledger.data.rows) ? ledger.data.rows : [];
      return (
        <div>
          {ledger.error ? (
            <Alert
              style={{ marginBottom: 12 }}
              type="warning"
              showIcon
              message={intl.formatMessage({ id: 'commandCenter.ledger.refreshFailed' }, { error: ledger.error })}
            />
          ) : null}
          <div data-proto-id="cc-m-ledger-rows">
            {rows.length ? (
              rows.map((r, i) => {
                const badge = outcomeBadge(r.outcome);
                return (
                  <div
                    key={ledgerRowKeys.get(r) ?? `row-${i}`}
                    // 行分隔线走 shared 双档 hair 档（浅档与原硬编码 rgba(0,0,0,0.08)
                    // 逐字节一致，深档随 --fenix-split 白 alpha 反相——code-review 156d614f1dd4）
                    style={{ padding: '10px 0', borderTop: i ? `1px solid ${METRIC_DIVIDER}` : undefined }}
                  >
                    <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                      <span
                        style={{
                          fontSize: 13,
                          fontWeight: 600,
                          flex: 1,
                          minWidth: 0,
                          overflow: 'hidden',
                          textOverflow: 'ellipsis',
                          whiteSpace: 'nowrap',
                        }}
                      >
                        {r.spec || '—'}
                      </span>
                      <span style={{ color: badge.color, fontSize: 12.5, fontWeight: 600, flexShrink: 0 }}>{badge.text}</span>
                    </div>
                    <div style={{ fontSize: 12, color: TEXT_SUB, marginTop: 3 }}>
                      {[r.project || '—', laneLabel(String(r.lane ?? '')) || '—', r.trigger || '—'].join(' · ')}
                    </div>
                    <div
                      style={{ fontSize: 12, color: TEXT_SUB, marginTop: 3, fontVariantNumeric: 'tabular-nums' }}
                    >
                      {[fmtDurationSeconds(r.duration), `${fmtTokens(r.tokens)} tokens`, fmtUsd(r.cost), fmtShortTs(r.started_at)].join(' · ')}
                    </div>
                  </div>
                );
              })
            ) : (
              <div style={{ padding: '8px 0', fontSize: 12.5, color: TEXT_SUB }}>
                {intl.formatMessage({ id: 'common.empty.default' })}
              </div>
            )}
          </div>
        </div>
      );
    }
    return (
      <div>
        {ledger.error ? (
          <Alert
            style={{ marginBottom: 12 }}
            type="warning"
            showIcon
            message={intl.formatMessage({ id: 'commandCenter.ledger.refreshFailed' }, { error: ledger.error })}
          />
        ) : null}
        <Table<CommandCenterLedgerRow>
          size="small"
          rowKey={(r) => ledgerRowKeys.get(r) ?? ''}
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
      <KpiBar kpi={kpi.data} kpiLoading={kpi.loading} kpiError={kpi.error} onRetry={kpi.retry} isMobile={isMobile} />
      {ledgerView()}
    </div>
  );
}
