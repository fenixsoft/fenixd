import { PageContainer } from '@ant-design/pro-components';
import { Alert, Card, Space, Spin } from 'antd';
import { useCallback, useEffect, useRef, useState } from 'react';
import { getOverview } from '@/services/dashboard';
import type { OverviewData } from '@/services/dashboard';
import IntroduceRow from './components/IntroduceRow';
import ProjectCards from './components/ProjectCards';

const REFRESH_THROTTLE_MS = 500;

export default function OverviewPage() {
  const [data, setData] = useState<OverviewData | null>(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);
  const lastRefreshRef = useRef(0);

  const load = useCallback(async () => {
    try {
      const d = await getOverview();
      setData(d);
      setError('');
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
    // SSE 实时刷新（对齐 v1：state/refresh/run_meta 事件触发概览重拉，500ms 前缘节流）
    const es = new EventSource('/api/stream');
    es.onmessage = (ev: MessageEvent) => {
      let msg: { type?: string } = {};
      try {
        msg = JSON.parse(ev.data);
      } catch {
        return;
      }
      if (
        msg.type !== 'state' &&
        msg.type !== 'refresh' &&
        msg.type !== 'run_meta'
      ) {
        return;
      }
      const now = Date.now();
      if (now - lastRefreshRef.current < REFRESH_THROTTLE_MS) return;
      lastRefreshRef.current = now;
      void load();
    };
    // 卸载必须关闭，防 EventSource 连接泄漏
    return () => es.close();
  }, [load]);

  return (
    <PageContainer
      header={{
        title: '跨项目概览',
        subtitle: data ? `监控 ${data.projects.length} 个项目` : ' ',
      }}
    >
      {error ? (
        <Alert
          type="error"
          showIcon
          style={{ marginBottom: 16 }}
          message="概览数据加载失败"
          description={error}
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
