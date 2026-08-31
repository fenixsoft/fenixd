import { PageContainer } from '@ant-design/pro-components';
import { App, Badge, Breadcrumb, Card, Empty, Spin, Tabs } from 'antd';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { getAdminActivities } from '@/services/dashboard';
import type { AdminActivitiesData, ProjectActivities } from '@/services/dashboard';

const REFRESH_THROTTLE_MS = 500;

export default function ActivitiesPage() {
  const { message } = App.useApp();
  const [data, setData] = useState<AdminActivitiesData | null>(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);
  const [activeKey, setActiveKey] = useState<string>('all');
  const lastRefreshRef = useRef(0);

  const load = useCallback(async () => {
    try {
      const d = await getAdminActivities();
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
    // SSE 实时刷新（对齐 v1：alerts/refresh 事件触发重拉）
    const es = new EventSource('/api/stream');
    es.onmessage = (ev: MessageEvent) => {
      let msg: { type?: string } = {};
      try {
        msg = JSON.parse(ev.data);
      } catch {
        return;
      }
      if (msg.type !== 'alerts' && msg.type !== 'refresh') return;
      const now = Date.now();
      if (now - lastRefreshRef.current < REFRESH_THROTTLE_MS) return;
      lastRefreshRef.current = now;
      void load();
    };
    // 卸载必须关闭，防 EventSource 连接泄漏
    return () => es.close();
  }, [load]);

  const projects: ProjectActivities[] = useMemo(() => data?.projects ?? [], [data]);

  const totalCount = useMemo(
    () => projects.reduce((sum, p) => sum + (p.activities?.length ?? 0), 0),
    [projects],
  );

  // 项目消失时回退"全部"
  useEffect(() => {
    if (activeKey === 'all') return;
    const exists = projects.some((p) => p.name === activeKey);
    if (!exists) setActiveKey('all');
  }, [activeKey, projects]);

  const tabItems = useMemo(() => {
    const items = [
      {
        key: 'all',
        label: (
          <span>
            全部 <Badge count={totalCount} showZero style={{ marginLeft: 4 }} />
          </span>
        ),
      },
      ...projects.map((p) => ({
        key: p.name,
        label: (
          <span>
            {p.name} <Badge count={p.activities?.length ?? 0} showZero style={{ marginLeft: 4 }} />
          </span>
        ),
      })),
    ];
    return items;
  }, [projects, totalCount]);

  const renderContent = () => {
    if (loading && !data) {
      return (
        <Card>
          <div style={{ textAlign: 'center', padding: 48 }}>
            <Spin size="large" />
          </div>
        </Card>
      );
    }

    if (!data) return null;

    // 全部视图：按项目分段展示
    if (activeKey === 'all') {
      if (projects.length === 0) {
        return <Empty description="暂无运维记录" />;
      }
      return (
        <div>
          {projects.map((p) => (
            <Card
              key={p.name}
              title={`${p.name}（${p.activities?.length ?? 0} 条）`}
              style={{ marginBottom: 16 }}
            >
              {p.activities?.length === 0 ? (
                <Empty description="暂无运维记录" />
              ) : (
                <div>记录列表占位</div>
              )}
            </Card>
          ))}
        </div>
      );
    }

    // 单项目视图
    const project = projects.find((p) => p.name === activeKey);
    if (!project || project.activities?.length === 0) {
      return <Empty description="暂无运维记录" />;
    }
    return <div>记录列表占位</div>;
  };

  return (
    <PageContainer
      header={{
        extra: <Breadcrumb items={[{ title: '运维记录' }]} />,
        title: '运维记录',
        subtitle: '跨项目 Administrator 活动',
      }}
    >
      {error ? (
        <App>
          <div style={{ marginBottom: 16 }}>
            <Card>
              <div style={{ color: '#ff4d4f' }}>运维记录加载失败：{error}</div>
            </Card>
          </div>
        </App>
      ) : null}
      <Card variant="borderless">
        <Tabs activeKey={activeKey} onChange={setActiveKey} items={tabItems} />
        {renderContent()}
      </Card>
    </PageContainer>
  );
}
