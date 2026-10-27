// index.tsx — 跨项目角色协作图谱大屏（add-collab-graph-bigscreen 3.2）。
//
// 脱壳全屏深色页面：路由 /overview/collab-graph 以 layout:false 关闭
// ProLayout 框架壳（无侧边栏/顶栏，specs「overview 入口与脱壳大屏路由」
// Requirement），顶部为大屏标题 + 全局 KPI 条（SPEC 总数/活跃/在飞 run/
// 总成本/总 run 数/总交接）+ 项目筛选器（全部/各项目，选中态可辨）+
// 退出按钮（返回 overview 枢纽页）。
//
// 实时刷新：SSE 失效全量重拉（复用既有 /api/stream 通道，角色级聚合数据量
// 小、全量渲染成本可接受）+ 30s 轮询兜底——与单 SPEC 拓扑大屏同策略
// （design D7）。归档口径注记：archived_excluded > 0 时可见。

import { useCallback, useEffect, useRef, useState } from 'react';
import { history } from '@umijs/max';
import { Alert, Button, ConfigProvider, Segmented, Spin, theme } from 'antd';
import { LogoutOutlined, ReloadOutlined } from '@ant-design/icons';
import { getCollabGraph, STREAM_URL } from '@/services/dashboard';
import type { CollabGraphData } from '@/services/dashboard';
import { HEARTBEAT_MS, REFRESH_THROTTLE_MS } from '@/utils/refreshPolicy';
import { fmtCost } from '@/pages/projects/topology/shared';
import { fmtDuration } from '@/utils/duration';
import CollabGraphView from './CollabGraphView';

// 深色大屏配色（IOC 风格，与单 SPEC 拓扑大屏同一色系）
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

export default function CollabGraphPage() {
  // project='' = 全部项目（服务端缺省聚合范围）；选中态经 Segmented 可辨
  const [project, setProject] = useState<string>('');
  const [data, setData] = useState<CollabGraphData | null>(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);

  // ── 拉取（SSE 触发的节流重拉与 30s 心跳共用；后台刷新静默原位，先例
  //    projects/topology/index.tsx）──
  const loadRef = useRef<(initial?: boolean) => Promise<void>>(async () => {});
  // 仿 overview/activities 页 loadSeqRef 口径：项目筛选切换重拉、SSE 节流重拉与
  // 30s 心跳可并发在飞，响应到达顺序不保证——较早发出（如「全部项目」）的响应
  // 后到会把旧聚合结果写回覆盖新筛选数据。仅最新一次请求允许落状态，过期响应
  // （含其失败与收尾置位）直接丢弃
  const loadSeqRef = useRef(0);

  const load = useCallback(
    async (initial = false) => {
      const seq = ++loadSeqRef.current;
      try {
        if (initial) setLoading(true);
        const d = await getCollabGraph(project || undefined);
        // 写回前复核序号：过期请求不改写任何状态
        if (seq !== loadSeqRef.current) return;
        setData(d);
        setError(d.error ?? '');
      } catch (err) {
        // 过期请求的失败同样不落状态，防旧错误提示覆盖新请求结果
        if (seq !== loadSeqRef.current) return;
        setError(err instanceof Error ? err.message : String(err));
      } finally {
        // 收尾置 false 同样纳入序号守卫：旧请求后完成时不抢撤加载指示
        if (seq === loadSeqRef.current) setLoading(false);
      }
    },
    [project],
  );
  loadRef.current = load;

  useEffect(() => {
    void load(true);
  }, [load]);

  useEffect(() => {
    // SSE 热更新（复用既有通道）：跨项目大屏对 run_meta（任意项目）/refresh/
    // state 一律节流全量重拉（角色级聚合节点量级 ~8，不做增量 patch）
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
      let msg: { type?: string } = {};
      try {
        msg = JSON.parse(ev.data);
      } catch {
        return;
      }
      if (msg.type === 'run_meta' || msg.type === 'refresh' || msg.type === 'state') {
        throttledLoad();
      }
    };
    // 30s 轮询兜底（SSE 建立失败/断连后仍能刷新；数据未变时 React 状态
    // 原位替换，无体感）
    const hb = setInterval(() => void loadRef.current(), HEARTBEAT_MS);
    return () => {
      es.close();
      clearInterval(hb);
      if (throttle) clearTimeout(throttle);
    };
  }, []);

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
        {/* 顶栏：标题 + KPI 条 + 项目筛选器 + 刷新 + 退出 */}
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
          <span style={{ fontSize: 20, fontWeight: 700, letterSpacing: 0.3 }}>
            AI-Native 组织画像 · 协作图谱
          </span>
          <div style={{ display: 'flex', alignItems: 'center', gap: 2, flex: 1, minWidth: 320 }}>
            <KpiCell label="SPEC 总数" value={kpis ? kpis.spec_count : '—'} />
            <KpiCell label="活跃 SPEC" value={kpis ? kpis.active_spec_count : '—'} />
            <KpiCell label="在飞" value={kpis ? kpis.running_runs : '—'} sub="运行中" />
            <KpiCell label="总成本" value={kpis ? fmtCost(kpis.total_cost_usd) : '—'} />
            <KpiCell label="总 run 数" value={kpis ? kpis.total_runs : '—'} />
            <KpiCell label="总交接" value={kpis ? kpis.total_handoffs : '—'} sub="次" />
            <KpiCell label="累计时长" value={kpis ? fmtDuration(sumDuration(data)) : '—'} />
          </div>
          <Segmented
            value={project}
            onChange={(v) => setProject(v as string)}
            options={[
              { label: '全部项目', value: '' },
              ...(data?.projects ?? []).map((p) => ({ label: p, value: p })),
            ]}
          />
          <Button icon={<ReloadOutlined />} onClick={() => void load()} />
          <Button icon={<LogoutOutlined />} onClick={() => history.push('/overview')}>
            退出大屏
          </Button>
        </div>

        {/* 归档口径注记（specs「归档口径注记」Requirement：archived_excluded
            > 0 时可见） */}
        {(data?.archived_excluded ?? 0) > 0 && (
          <Alert
            style={{ marginTop: 12 }}
            type="info"
            showIcon
            message={`${data?.archived_excluded} 个已归档 SPEC 仅计入 KPI，不计入图谱`}
            description="已归档 SPEC 的 run 明细已随归档清理，图谱边与节点权重仅聚合活跃 SPEC 数据。"
          />
        )}
        {error && (
          <Alert style={{ marginTop: 12 }} type="error" showIcon message={`协作图谱数据加载失败：${error}`} />
        )}

        {/* 画布 */}
        <div style={{ marginTop: 14 }}>
          {loading && !data ? (
            <div style={{ display: 'flex', justifyContent: 'center', padding: 80 }}>
              <Spin size="large" />
            </div>
          ) : data ? (
            <CollabGraphView data={data} />
          ) : null}
        </div>
      </div>
    </ConfigProvider>
  );
}

/** 全角色累计时长（KPI 条「累计时长」格；角色级 duration_seconds 求和）。 */
function sumDuration(data: CollabGraphData | null): number {
  if (!data) return 0;
  return data.roles.reduce((acc, r) => acc + (r.duration_seconds || 0), 0);
}
