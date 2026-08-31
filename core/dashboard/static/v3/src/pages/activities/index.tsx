import { PageContainer } from '@ant-design/pro-components';
import {
  App,
  Badge,
  Breadcrumb,
  Button,
  Card,
  Empty,
  Space,
  Spin,
  Tabs,
  Tag,
  Timeline,
  Typography,
} from 'antd';
import dayjs from 'dayjs';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { getAdminActivities } from '@/services/dashboard';
import type { AdminActivitiesData, ActivityItem, ProjectActivities } from '@/services/dashboard';

const REFRESH_THROTTLE_MS = 500;

function fmtDate(v?: string) {
  if (!v) return '—';
  const d = dayjs(v);
  return d.isValid() ? d.format('YYYY-MM-DD HH:mm:ss') : v;
}

function resultPill(result?: string) {
  if (!result) return null;
  const lower = result.toLowerCase();
  let color = 'default';
  if (lower.includes('成功') || lower.includes('success')) color = 'green';
  else if (lower.includes('失败') || lower.includes('fail') || lower.includes('error')) color = 'red';
  else if (lower.includes('处理') || lower.includes('handled')) color = 'blue';
  return <Tag color={color}>{result}</Tag>;
}

function ActivityCard({ a }: { a: ActivityItem }) {
  const unhandled = a.handled === false;
  const severity = a.severity || 'major';

  const body = a.summary ? (
    <div style={{ marginBottom: 8 }}>{a.summary}</div>
  ) : (
    <div style={{ marginBottom: 8, color: '#8c8c8c' }}>
      （无叙述总结）处置：{a.actions_taken || '—'} · 结果：{a.result || '—'}
    </div>
  );

  return (
    <div
      style={{
        padding: 12,
        borderRadius: 8,
        border: unhandled ? '1px solid #ff4d4f' : '1px solid #f0f0f0',
        background: unhandled ? '#fff2f0' : '#fafafa',
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8, flexWrap: 'wrap' }}>
        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
          {fmtDate(a.created)}
        </Typography.Text>
        {a.project && <Tag>{a.project}</Tag>}
        {a.spec && <Tag color="blue">{a.spec}</Tag>}
        {a.signal_type && <Tag color="purple">{a.signal_type}</Tag>}
        {resultPill(a.result)}
        {unhandled && <Tag color="red">需人工决策</Tag>}
      </div>
      {body}
      {a.actions_taken && (
        <div style={{ marginBottom: 4 }}>
          <Typography.Text type="secondary">处置：</Typography.Text> {a.actions_taken}
        </div>
      )}
      {a.recommended_action && (
        <div>
          <Typography.Text type="secondary">建议：</Typography.Text> {a.recommended_action}
        </div>
      )}
    </div>
  );
}

function ActivityTimeline({ activities }: { activities: ActivityItem[] }) {
  if (!activities || activities.length === 0) {
    return <Empty description="暂无运维记录" />;
  }

  // 未处理升级置顶
  const sorted = [...activities].sort((a, b) => {
    if (a.handled === false && b.handled !== false) return -1;
    if (a.handled !== false && b.handled === false) return 1;
    return 0;
  });

  return (
    <Timeline
      items={sorted.map((a) => ({
        color: a.handled === false ? 'red' : 'gray',
        children: <ActivityCard a={a} />,
      }))}
    />
  );
}

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
    // SSE 实时刷新（对齐 v1：alerts/refresh 事件触发重拉，保持页签与滚动）
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

  // 项目消失时回退"全部"（跨刷新保持选中，除非项目已消失）
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

    if (!data || !data.projects || data.projects.length === 0) {
      return <Empty description="暂无运维记录" />;
    }

    // 全部视图：按项目分段展示
    if (activeKey === 'all') {
      return (
        <div>
          {projects.map((p) => (
            <Card
              key={p.name}
              title={
                <Space>
                  <span>{p.name}</span>
                  <Badge count={p.activities?.length ?? 0} showZero />
                </Space>
              }
              style={{ marginBottom: 16 }}
            >
              <ActivityTimeline activities={p.activities ?? []} />
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
    return (
      <Card
        title={
          <Space>
            <span>{project.name}</span>
            <Badge count={project.activities?.length ?? 0} showZero />
          </Space>
        }
      >
        <ActivityTimeline activities={project.activities ?? []} />
      </Card>
    );
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
        <div style={{ marginBottom: 16 }}>
          <Card>
            <div style={{ color: '#ff4d4f' }}>运维记录加载失败：{error}</div>
          </Card>
        </div>
      ) : null}
      <Card variant="borderless">
        <Tabs activeKey={activeKey} onChange={setActiveKey} items={tabItems} />
        {renderContent()}
      </Card>
    </PageContainer>
  );
}
