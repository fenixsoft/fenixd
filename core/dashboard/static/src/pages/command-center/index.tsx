// index.tsx — 管理指挥中心（add-command-center 3.3）。
//
// 脱壳全屏深色页面：路由 /command-center 以 layout:false 关闭 ProLayout
// 框架壳（与协作图谱/拓扑大屏同款），四 Tab（组织总览默认）各屏数据独立
// 加载、独立错误降级（错误占位 + 重试，互不拖垮——specs「导航与默认 Tab」
// 「独立降级」Requirement），60s 常量静默轮询（design D5，useScreen 单点）。
//
// 收件箱裁决成功 → 卡片移出 + KPI 刷新：裁决回调经 shell 的 kpiTick 传给
// 执行台账屏（KPI 条宿主），重挂载零耦合。深色 antd token 与协作图谱大屏
// 同一色系（design D6：样式作为场景复用，不新增样式配置）。

import { useState } from 'react';
import { history } from '@umijs/max';
import { Button, ConfigProvider, Tabs, theme } from 'antd';
import { LogoutOutlined } from '@ant-design/icons';
import { BG, PANEL_BORDER, TEXT_MAIN } from './shared';
import OrgGrid from './OrgGrid';
import PipelineBoard from './PipelineBoard';
import ExecutionLedger from './ExecutionLedger';
import AdjudicationInbox from './AdjudicationInbox';

export default function CommandCenterPage() {
  // 默认 Tab = 组织总览（specs「导航与默认 Tab」Requirement）
  const [activeKey, setActiveKey] = useState('org');
  // 收件箱裁决成功 → 递增 tick 触发执行台账 KPI 条重拉
  const [kpiTick, setKpiTick] = useState(0);
  const notifyKpiRefresh = () => setKpiTick((t) => t + 1);

  return (
    <ConfigProvider
      theme={{
        algorithm: theme.darkAlgorithm,
        token: { colorBgBase: BG, colorPrimary: '#40a9ff', borderRadius: 8 },
      }}
    >
      <div
        style={{
          minHeight: '100vh',
          background: `radial-gradient(1200px 500px at 70% -10%, rgba(59, 110, 165, 0.25), transparent), ${BG}`,
          padding: '16px 20px 24px',
          color: TEXT_MAIN,
        }}
      >
        {/* 顶栏：标题 + 退出（返回 overview 枢纽页） */}
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            gap: 14,
            borderBottom: `1px solid ${PANEL_BORDER}`,
            paddingBottom: 12,
          }}
        >
          <span style={{ fontSize: 20, fontWeight: 700, letterSpacing: 0.3 }}>
            管理指挥中心
          </span>
          <Button icon={<LogoutOutlined />} onClick={() => history.push('/overview')}>
            退出大屏
          </Button>
        </div>

        <Tabs
          activeKey={activeKey}
          onChange={setActiveKey}
          style={{ marginTop: 8 }}
          items={[
            { key: 'org', label: '组织总览', children: <OrgGrid active={activeKey === 'org'} /> },
            {
              key: 'pipeline',
              label: '交付流水线',
              children: <PipelineBoard active={activeKey === 'pipeline'} />,
            },
            {
              key: 'ledger',
              label: '执行台账',
              children: (
                <ExecutionLedger active={activeKey === 'ledger'} kpiTick={kpiTick} />
              ),
            },
            {
              key: 'inbox',
              label: '裁决收件箱',
              children: (
                <AdjudicationInbox active={activeKey === 'inbox'} onKpiRefresh={notifyKpiRefresh} />
              ),
            },
          ]}
        />
      </div>
    </ConfigProvider>
  );
}
