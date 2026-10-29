// index.tsx — SPEC 协作拓扑大屏（add-spec-topology-bigscreen 4.1/4.5）。
//
// 脱壳全屏深色页面：路由 /projects/:name/:spec/topology 以 layout:false 关闭
// ProLayout 框架壳（无侧边栏/顶栏，specs「独立脱壳大屏页面」Requirement），
// 顶部为 SPEC 名 + KPI 条（总耗时/总成本/派发/完成/重试/在飞/状态）+ 胶囊
// 视图切换器 + 退出大屏按钮（返回该项目 SPEC 列表）。
//
// 编排职责：胶囊切换器（一屏独占单视图）、跨视图联动高亮（selectedId 双视图
// 共享）、SSE 失效全量重拉（复用既有 /api/stream 通道；不可用/断连时 30s
// 轮询兜底，先例 detail.tsx）、归档 SPEC「run 明细已随归档清理」横幅、run
// 节点点击下钻复用 RunRecordModal/ClaudeOutputPane（不新建第二套转录组件）、
// PMEngine/用户节点点击展示状态转移与人工动作记录。

import { useCallback, useEffect, useRef, useState } from 'react';
import { history, useParams } from '@umijs/max';
import { Alert, App, Button, ConfigProvider, Empty, Modal, Segmented, Spin, Table, Tag, theme } from 'antd';
import { LogoutOutlined, ReloadOutlined } from '@ant-design/icons';
import {
  getSpecTopology,
  statusMeta,
  STREAM_URL,
} from '@/services/dashboard';
import type { SpecTopology, TopologyNode } from '@/services/dashboard';
import { HEARTBEAT_MS, REFRESH_THROTTLE_MS } from '@/utils/refreshPolicy';
import { fmtDuration } from '@/utils/duration';
import RunRecordModal from '@/pages/projects/components/RunRecordModal';
import PipelineView from './PipelineView';
import SwimlaneView from './SwimlaneView';
import { fmtCost } from './shared';

type ViewKey = 'pipeline' | 'swimlane';

// 深色大屏配色（IOC 风格：深海军底 + 高亮青）
const BG = '#0a1628';
const PANEL_BORDER = 'rgba(59, 110, 165, 0.4)';
const TEXT_MAIN = '#d6e7f7';
const TEXT_SUB = '#7f9cba';

const kpiCellStyle: React.CSSProperties = {
  display: 'flex',
  flexDirection: 'column',
  alignItems: 'center',
  minWidth: 76,
  padding: '2px 10px',
};

function KpiCell({ label, value, sub }: { label: string; value: React.ReactNode; sub?: string }) {
  return (
    <div style={kpiCellStyle}>
      <span style={{ fontSize: 17, fontWeight: 700, color: TEXT_MAIN, lineHeight: 1.3 }}>{value}</span>
      <span style={{ fontSize: 11, color: TEXT_SUB }}>
        {label}
        {sub ? ` · ${sub}` : ''}
      </span>
    </div>
  );
}

export default function SpecTopologyPage() {
  const params = useParams();
  const name = params.name ?? '';
  const spec = params.spec ?? '';
  const { message } = App.useApp();

  const [data, setData] = useState<SpecTopology | null>(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);
  const [view, setView] = useState<ViewKey>('pipeline');
  const [selectedId, setSelectedId] = useState<string | null>(null);
  // 下钻弹窗（run 转录 / pm 状态转移 / user 人工动作）
  const [drillRun, setDrillRun] = useState<{ runId: string; harness?: string } | null>(null);
  const [drillMeta, setDrillMeta] = useState<{ title: string; node: TopologyNode } | null>(null);

  // ── 拉取（SSE 触发的节流重拉与 30s 心跳共用；后台刷新静默原位，先例 detail.tsx）──
  const loadRef = useRef<(initial?: boolean) => Promise<void>>(async () => {});

  // 加载币值守卫（code-review item 7ef79d3a2087，仿 list.tsx loadSeqRef）：SSE 节流
  // 重拉、30s 心跳与手动刷新三个触发源在慢响应（>500ms）下可重叠在飞，先发后至
  // 的旧快照会把较新拓扑覆盖回旧值。每次调用递增序号作为币值，await 返回后比对
  // 仍是最新一次才 setData/setError，过期响应直接丢弃。
  const loadSeqRef = useRef(0);
  const load = useCallback(
    async (initial = false) => {
      if (!name || !spec) return;
      const seq = ++loadSeqRef.current;
      try {
        if (initial) setLoading(true);
        const d = await getSpecTopology(name, spec);
        if (loadSeqRef.current !== seq) return;
        setData(d);
        setError(d.error ?? '');
      } catch (err) {
        if (loadSeqRef.current !== seq) return;
        setError(err instanceof Error ? err.message : String(err));
      } finally {
        // loading 只由最新一次请求收口，过期响应不抢（新请求自己会复位）
        if (loadSeqRef.current === seq) setLoading(false);
      }
    },
    [name, spec],
  );
  // 渲染期副作用消除（code-review item 624414f4664a）：原在渲染体直接写
  // loadRef.current = load，属 render side effect（并发渲染/StrictMode 下 ref 可能
  // 与本次渲染不一致）；改在 effect 中同步（list.tsx specMapRef 同款纪律）。
  useEffect(() => {
    loadRef.current = load;
  }, [load]);

  useEffect(() => {
    setSelectedId(null);
    void load(true);
  }, [load]);

  useEffect(() => {
    if (!name || !spec) return;
    // SSE 热更新（复用既有通道）：run_meta（本项目）/refresh（全局兜底心跳）/
    // state（本项目条目变化）→ 节流全量重拉（拓扑节点量级 ~几十，不做增量 patch）
    let throttle: ReturnType<typeof setTimeout> | null = null;
    const throttledLoad = () => {
      if (throttle) return;
      throttle = setTimeout(() => {
        throttle = null;
        void loadRef.current();
      }, REFRESH_THROTTLE_MS);
    };
    const es = new EventSource(STREAM_URL);
    es.onmessage = (ev: MessageEvent) => {
      let msg: { type?: string; project?: string } = {};
      try {
        msg = JSON.parse(ev.data);
      } catch {
        return;
      }
      if ((msg.type === 'run_meta' && msg.project === name) || msg.type === 'refresh') {
        throttledLoad();
      }
      if (msg.type === 'state' && msg.project === name) {
        throttledLoad();
      }
    };
    // 30s 轮询兜底（detail.tsx 同款）：SSE 建立失败/断连后仍能刷新；正常时
    // 数据未变不产生体感（React 状态原位替换）
    const hb = setInterval(() => void loadRef.current(), HEARTBEAT_MS);
    return () => {
      es.close();
      clearInterval(hb);
      if (throttle) clearTimeout(throttle);
    };
  }, [name, spec]);

  // ── 节点交互：选中（联动高亮）+ 下钻（run 复用运行记录弹窗） ──
  const handleSelect = (node: TopologyNode | null) => {
    if (!node) {
      setSelectedId(null);
      return;
    }
    setSelectedId(node.id);
    if (node.kind === 'run' && node.run_id) {
      setDrillRun({ runId: node.run_id, harness: node.harness });
      return;
    }
    if (node.kind === 'pm' || node.kind === 'user') {
      setDrillMeta({ title: node.kind === 'pm' ? 'PMEngine 状态转移记录' : '用户人工动作记录', node });
    }
    // verify/delivery/approve：仅选中高亮（无下钻弹窗语义）
  };

  const runningCount = (data?.nodes ?? []).filter(
    (n) => n.kind === 'run' && (n.status === 'running' || n.status === 'empty'),
  ).length;

  // ── 画布分支：loading 兜底 → 数据无错 → 按视图二选一 → 空数据兜底 ──
  // 禁止嵌套三元（同 SessionPanel renderBody 先例），用 if/else 早返回逐层表达
  const renderCanvas = () => {
    if (loading && !data) {
      return (
        <div style={{ display: 'flex', justifyContent: 'center', padding: 80 }}>
          <Spin size="large" />
        </div>
      );
    }
    if (data && !data.error) {
      if (view === 'pipeline') {
        return <PipelineView data={data} selectedId={selectedId} onSelect={handleSelect} />;
      }
      return <SwimlaneView data={data} selectedId={selectedId} onSelect={handleSelect} />;
    }
    if (!error) {
      return <Empty description="暂无拓扑数据" style={{ padding: 80 }} />;
    }
    return null;
  };

  if (!name || !spec) {
    return (
      <div style={{ minHeight: '100vh', background: BG, padding: 24 }}>
        <Alert type="error" message="缺少项目或 SPEC 参数" />
      </div>
    );
  }

  const kpis = data?.kpis;

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
        {/* 顶栏：SPEC 名 + 状态 + KPI 条 + 视图切换 + 退出 */}
        <div
          style={{
            display: 'flex',
            flexWrap: 'wrap',
            alignItems: 'center',
            gap: 14,
            borderBottom: `1px solid ${PANEL_BORDER}`,
            paddingBottom: 12,
          }}
        >
          <span style={{ fontSize: 20, fontWeight: 700, letterSpacing: 0.3 }}>{spec}</span>
          {data && (
            <Tag
              color={
                { good: 'green', critical: 'red', warning: 'orange', info: 'blue', aqua: 'cyan', muted: 'default' }[
                  statusMeta(data.status ?? '').tone
                ]
              }
              style={{ marginInlineEnd: 0 }}
            >
              {statusMeta(data.status ?? '').label}
            </Tag>
          )}
          <div style={{ display: 'flex', alignItems: 'center', gap: 2, flex: 1, minWidth: 320 }}>
            <KpiCell label="总耗时" value={kpis ? fmtDuration(kpis.total_duration ?? 0) : '—'} />
            <KpiCell label="总成本" value={kpis ? fmtCost(kpis.total_cost_usd) : '—'} />
            <KpiCell label="派发" value={kpis?.dispatched ?? '—'} />
            <KpiCell label="完成" value={kpis?.completed ?? '—'} />
            <KpiCell label="重试" value={kpis?.retried ?? '—'} />
            {runningCount > 0 && <KpiCell label="在飞" value={runningCount} sub="运行中" />}
          </div>
          <Segmented
            value={view}
            onChange={(v) => setView(v as ViewKey)}
            options={[
              { label: '管线视图', value: 'pipeline' },
              { label: '协作时序', value: 'swimlane' },
            ]}
          />
          <Button icon={<ReloadOutlined />} onClick={() => void load()} />
          <Button
            icon={<LogoutOutlined />}
            onClick={() => history.push(`/projects/${encodeURIComponent(name)}`)}
          >
            退出大屏
          </Button>
        </div>

        {/* 归档降级横幅 */}
        {data?.archived && (
          <Alert
            style={{ marginTop: 12 }}
            type="warning"
            showIcon
            message="该 SPEC 已归档——run 明细已随归档清理"
            description="以下为状态骨架（PMEngine 状态转移 / 验证轮次 / 运维事件与交付终点）；完整协作明细（run 转录、成本、耗时）已随 SPEC 归档清理，不可回看。"
          />
        )}
        {!data?.archived && error && (
          <Alert style={{ marginTop: 12 }} type="error" showIcon message={`拓扑数据加载失败：${error}`} />
        )}

        {/* 画布（胶囊切换器一屏独占单视图） */}
        <div style={{ marginTop: 14 }}>{renderCanvas()}</div>
      </div>

      {/* run 节点下钻：复用现有运行记录弹窗（RunRecordModal/ClaudeOutputPane 单源） */}
      <RunRecordModal
        runId={drillRun?.runId ?? null}
        project={name}
        harness={drillRun?.harness}
        onClose={() => setDrillRun(null)}
      />

      {/* PMEngine / 用户节点详情：状态转移记录 / 人工动作记录 */}
      <Modal
        title={drillMeta?.title}
        open={!!drillMeta}
        onCancel={() => setDrillMeta(null)}
        footer={null}
        width={720}
      >
        {drillMeta?.node.kind === 'pm' ? (
          <Table
            size="small"
            rowKey={(_, i) => String(i)}
            pagination={false}
            dataSource={(data?.transitions ?? []).map((t, i) => ({ ...t, key: i }))}
            columns={[
              { title: '时刻', dataIndex: 'time', width: 190 },
              { title: '转移', render: (_, r) => `${r.from} → ${r.to}` },
              { title: '来源', dataIndex: 'channel', width: 90, render: (v) => v || '—' },
            ]}
          />
        ) : (
          <Table
            size="small"
            rowKey={(_, i) => String(i)}
            pagination={false}
            dataSource={[
              ...(data?.user_actions ?? []).map((a, i) => ({ key: i, time: a.time, action: a.action, kind: '人工动作' })),
              ...(data?.admin_events ?? []).map((e, i) => ({
                key: `e${i}`,
                time: e.time,
                action: e.description || e.signal_type || e.record_kind || e.kind,
                kind: '运维事件',
              })),
            ]}
            columns={[
              { title: '时刻', dataIndex: 'time', width: 190 },
              { title: '类型', dataIndex: 'kind', width: 90 },
              { title: '动作', dataIndex: 'action' },
            ]}
          />
        )}
      </Modal>
    </ConfigProvider>
  );
}
