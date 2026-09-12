import { PageContainer } from '@ant-design/pro-components';
import { Alert, Button, Card, Space, Spin } from 'antd';
import { useCallback, useEffect, useState } from 'react';
import { getOverview } from '@/services/dashboard';
import type { OverviewData } from '@/services/dashboard';
import AlertBanner from './components/AlertBanner';
import IntroduceRow from './components/IntroduceRow';
import ProjectCards from './components/ProjectCards';

// dashboard-sse-refresh 3.3：overview 轮询 2s → 30s 心跳校准 + visibilitychange 补刷
const HEARTBEAT_MS = 30000;

export default function OverviewPage() {
  const [data, setData] = useState<OverviewData | null>(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);
  const [alertsTick, setAlertsTick] = useState(0);

  const load = useCallback(async () => {
    try {
      const d = await getOverview();
      setData(d);
      setError('');
    } catch (e) {
      // fix-dashboard-fault-isolation 3.1：请求失败 MUST NOT 清空已成功加载的
      // data——错误提示叠加在既有数据之上，刷新失败不清空已展示的项目卡片与 totals
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
    // 30s 心跳校准：overview 仍作为本地统计的校准源（SSE 断线时心跳兜底）。
    // SSE 增量事件（state/refresh/run_meta）不再逐事件重拉 overview（2s→30s）。
    const hb = setInterval(() => void load(), HEARTBEAT_MS);
    const onVisible = () => {
      if (document.visibilityState === 'visible') void load();
    };
    document.addEventListener('visibilitychange', onVisible);
    const es = new EventSource('/api/stream');
    es.onmessage = (ev: MessageEvent) => {
      let msg: { type?: string } = {};
      try {
        msg = JSON.parse(ev.data);
      } catch {
        return;
      }
      // 仅 alerts 事件驱动横幅刷新（跨项目告警聚合，与 30s 心跳解耦）
      if (msg.type === 'alerts') setAlertsTick((t) => t + 1);
      // state/refresh/run_meta 不触发 overview 重拉：由 30s 心跳统一校准
    };
    // 卸载必须关闭，防 EventSource 连接泄漏
    return () => {
      es.close();
      clearInterval(hb);
      document.removeEventListener('visibilitychange', onVisible);
    };
  }, [load]);

  return (
    <PageContainer
      header={{
        title: '跨项目概览',
        subtitle: data ? `监控 ${data.projects.length} 个项目` : ' ',
      }}
    >
      <AlertBanner refreshTick={alertsTick} />
      {error ? (
        <Alert
          type="error"
          showIcon
          style={{ marginBottom: 16 }}
          message="概览数据加载失败"
          description={error}
          action={
            <Button size="small" onClick={() => void load()}>
              重试
            </Button>
          }
        />
      ) : null}

      {loading && !data ? (
        <Card>
          <div style={{ textAlign: 'center', padding: 48 }}>
            <Spin size="large" />
          </div>
        </Card>
      ) : data ? (
        <Space direction="vertical" size={16} style={{ width: '100%' }}>
          <IntroduceRow totals={data.totals} tokenRecent={data.token_usage?.recent ?? []} />
          <ProjectCards projects={data.projects} onChanged={() => void load()} />
        </Space>
      ) : null}
    </PageContainer>
  );
}
