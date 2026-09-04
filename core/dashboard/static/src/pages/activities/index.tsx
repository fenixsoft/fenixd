import { PageContainer } from '@ant-design/pro-components';
import {
  App,
  Button,
  Card,
  Collapse,
  Empty,
  List,
  Radio,
  Space,
  Spin,
  Tag,
  Timeline,
  Typography,
} from 'antd';
import dayjs from 'dayjs';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import Markdown from 'react-markdown';
import remarkBreaks from 'remark-breaks';
import remarkGfm from 'remark-gfm';
import AdminRunModal from './components/AdminRunModal';
import { markdownComponents } from '@/pages/projects/components/SpecDocModal';
import { getAdminActivities, getAlerts, markAlertHandled } from '@/services/dashboard';
import type {
  AdminActivitiesData,
  ActivityItem,
  AlertItem,
  AlertsData,
  ProjectActivities,
} from '@/services/dashboard';

const REFRESH_THROTTLE_MS = 500;

// 标签原始值 → 显示值（对齐 v1 RESULT_META / sevLabel；未收录值原样显示）
const RESULT_META: Record<string, { label: string; color: string }> = {
  resolved: { label: '已解决', color: 'green' },
  'partially-resolved': { label: '部分解决', color: 'orange' },
  escalated: { label: '已升级', color: 'red' },
  failed: { label: '失败', color: 'red' },
  interrupted: { label: '已中断', color: 'red' },
  pending: { label: '处置中', color: 'default' },
  'in-progress': { label: '进行中', color: 'blue' },
  diagnosed: { label: '已诊断', color: 'blue' },
};

const SIGNAL_LABEL: Record<string, string> = {
  blocked_stuck: '阻塞滞留',
  stuck: '卡滞',
  flapping: '状态抖动',
  dispatch_stalled: '派发停滞',
  merge_streak: '合并反复失败',
  'manual-intervention': '人工介入',
  repeated_failures: '连续失败',
  verify_fail_escalation: '验证失败升级',
  ready_stuck: '就绪滞留',
  family_explosion: 'SPEC 族爆炸',
  daemon_errors: '守护进程异常',
};

const SEV_LABEL: Record<string, string> = { critical: '严重', major: '较高', minor: '一般' };
const SEV_COLOR: Record<string, string> = { critical: 'red', major: 'orange', minor: 'blue' };

const PRE_WRAP: React.CSSProperties = { whiteSpace: 'pre-wrap' };

function fmtDate(v?: string) {
  if (!v) return '—';
  const d = dayjs(v);
  return d.isValid() ? d.format('YYYY-MM-DD HH:mm:ss') : v;
}

function resultPill(result?: string) {
  if (!result) return null;
  const meta = RESULT_META[result.toLowerCase()];
  if (meta) return <Tag color={meta.color}>{meta.label}</Tag>;
  // 未收录的自由文本结果：保留 v1 关键词配色兜底
  const lower = result.toLowerCase();
  let color = 'default';
  if (lower.includes('成功') || lower.includes('success')) color = 'green';
  else if (lower.includes('失败') || lower.includes('fail') || lower.includes('error')) color = 'red';
  else if (lower.includes('处理') || lower.includes('handled')) color = 'blue';
  return <Tag color={color}>{result}</Tag>;
}

function signalTag(signalType?: string) {
  if (!signalType) return null;
  return <Tag color="purple">{SIGNAL_LABEL[signalType] || signalType}</Tag>;
}

function ActivityCard({ a, onViewRun }: { a: ActivityItem; onViewRun?: (a: ActivityItem) => void }) {
  const unhandled = a.handled === false;
  // fix-admin-disposition-empty-shell：失败处置自解释——error 携带 CLI 失败原因，
  // 空 summary 兜底文案同步附带 error，空壳卡片（仅时间+spec）不再出现。
  const errText = a.error || '';

  const body = a.summary ? (
    <div style={{ marginBottom: 8, fontSize: 13, lineHeight: 1.65 }}>
      <Markdown remarkPlugins={[remarkGfm]} components={markdownComponents}>
        {a.summary}
      </Markdown>
    </div>
  ) : (
    <div style={{ ...PRE_WRAP, marginBottom: 8, color: '#8c8c8c' }}>
      {errText
        ? `（无叙述总结）失败原因：${errText} · 结果：${a.result || '—'}`
        : `（无叙述总结）处置：${a.actions_taken || '—'} · 结果：${a.result || '—'}`}
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
        {signalTag(a.signal_type)}
        {resultPill(a.result)}
        {unhandled && <Tag color="red">需人工决策</Tag>}
        {a.admin_run_id && a.project && onViewRun && (
          <Button type="link" size="small" style={{ padding: 0, height: 'auto' }} onClick={() => onViewRun(a)}>
            查看处置过程
          </Button>
        )}
      </div>
      {errText ? (
        <div style={{ ...PRE_WRAP, marginBottom: 8, fontSize: 13, lineHeight: 1.65 }}>
          <Typography.Text type="danger">失败原因：{errText}</Typography.Text>
        </div>
      ) : null}
      {body}
      {a.actions_taken && (
        <div style={{ marginBottom: 4, fontSize: 13, lineHeight: 1.65 }}>
          <Typography.Text type="secondary">处置：</Typography.Text>
          <Markdown remarkPlugins={[remarkGfm, remarkBreaks]} components={markdownComponents}>
            {a.actions_taken}
          </Markdown>
        </div>
      )}
      {a.recommended_action && (
        <div style={{ fontSize: 13, lineHeight: 1.65 }}>
          <Typography.Text type="secondary">建议：</Typography.Text>
          <Markdown remarkPlugins={[remarkGfm, remarkBreaks]} components={markdownComponents}>
            {a.recommended_action}
          </Markdown>
        </div>
      )}
    </div>
  );
}

function ActivityTimeline({
  activities,
  onViewRun,
}: {
  activities: ActivityItem[];
  onViewRun?: (a: ActivityItem) => void;
}) {
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
        children: <ActivityCard a={a} onViewRun={onViewRun} />,
      }))}
    />
  );
}

function AlertTitle({ item, resolved }: { item: AlertItem; resolved?: boolean }) {
  return (
    <Space wrap size={6}>
      <Tag color={SEV_COLOR[item.severity || ''] || 'default'} style={{ marginInlineEnd: 0 }}>
        {SEV_LABEL[item.severity || ''] || item.severity || '未知'}
      </Tag>
      {resolved ? (
        <Tag
          style={{ marginInlineEnd: 0 }}
          color={item.handled_by === 'auto-resolve' ? 'cyan' : 'geekblue'}
        >
          {item.handled_by === 'auto-resolve' ? '🤖 自动解决' : '👤 人工处理'}
        </Tag>
      ) : null}
      {item.spec ? <Tag color="blue">{item.spec}</Tag> : null}
      <Typography.Text type="secondary" style={{ fontSize: 12 }}>
        {fmtDate(resolved ? item.handled_at || item.created : item.created)}
      </Typography.Text>
    </Space>
  );
}

function AlertLines({ item }: { item: AlertItem }) {
  return (
    <div style={{ fontSize: 12, ...PRE_WRAP }}>
      {item.description ? <div>{item.description}</div> : null}
      {item.evidence ? (
        <div>
          <Typography.Text type="secondary">证据：{item.evidence}</Typography.Text>
        </div>
      ) : null}
      {item.action_taken ? (
        <div>
          <Typography.Text type="secondary">处置：</Typography.Text>
          {item.action_taken}
        </div>
      ) : null}
      {item.recommended_action ? (
        <div>
          <Typography.Text type="secondary">建议：</Typography.Text>
          {item.recommended_action}
        </div>
      ) : null}
      {item.resolve_note ? (
        <div>
          <Typography.Text type="secondary">解决依据：{item.resolve_note}</Typography.Text>
        </div>
      ) : null}
    </div>
  );
}

type ViewMode = 'auto' | 'alert';

interface ViewingRun {
  project: string;
  spec?: string;
  runId: string;
}

function AlertPanel({
  project,
  alertsData,
  optimistic,
  onMarkHandled,
}: {
  project: string;
  alertsData: AlertsData | null;
  optimistic: string[];
  onMarkHandled: (a: AlertItem) => void;
}) {
  const visible = (a: AlertItem) => a.project === project && !optimistic.includes(a.id);
  const unhandled = (alertsData?.alerts || []).filter(visible);
  const resolved = (alertsData?.resolved || []).filter(visible);

  if (!unhandled.length && !resolved.length) {
    return <Empty description="暂无人工告警" />;
  }

  return (
    <div>
      <List
        size="small"
        dataSource={unhandled}
        locale={{ emptyText: '暂无未处理告警' }}
        renderItem={(a) => (
          <List.Item
            actions={[
              <Button key="handled" size="small" onClick={() => onMarkHandled(a)}>
                标记已处理
              </Button>,
            ]}
          >
            <List.Item.Meta title={<AlertTitle item={a} />} description={<AlertLines item={a} />} />
          </List.Item>
        )}
      />
      {resolved.length ? (
        <Collapse
          ghost
          items={[
            {
              key: 'resolved',
              label: `已解决 (${resolved.length})`,
              children: (
                <List
                  size="small"
                  dataSource={resolved}
                  renderItem={(a) => (
                    <List.Item>
                      <List.Item.Meta
                        title={<AlertTitle item={a} resolved />}
                        description={<AlertLines item={a} />}
                      />
                    </List.Item>
                  )}
                />
              ),
            },
          ]}
        />
      ) : null}
    </div>
  );
}

export default function ActivitiesPage() {
  const { message } = App.useApp();
  const [data, setData] = useState<AdminActivitiesData | null>(null);
  const [alertsData, setAlertsData] = useState<AlertsData | null>(null);
  const [optimistic, setOptimistic] = useState<string[]>([]);
  const [viewModes, setViewModes] = useState<Record<string, ViewMode>>({});
  const [viewingRun, setViewingRun] = useState<ViewingRun | null>(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);
  const lastRefreshRef = useRef(0);

  const load = useCallback(async () => {
    try {
      const [d, alerts] = await Promise.all([getAdminActivities(), getAlerts()]);
      setData(d);
      if (!alerts.error) setAlertsData(alerts);
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

  // 乐观移除：后端确认已消失才真正清除，绝不永久遮蔽
  useEffect(() => {
    if (!optimistic.length || !alertsData) return;
    const stillThere = new Set((alertsData.alerts || []).map((a) => a.id));
    const next = optimistic.filter((id) => stillThere.has(id));
    if (next.length !== optimistic.length) setOptimistic(next);
  }, [alertsData, optimistic]);

  const handleMarkHandled = useCallback(
    async (a: AlertItem) => {
      setOptimistic((prev) => [...prev, a.id]);
      try {
        await markAlertHandled(a.project, a.id);
        message.success('已标记处理');
      } catch (err) {
        message.error(`标记失败：${err instanceof Error ? err.message : String(err)}`);
      }
      void load();
    },
    [load, message],
  );

  const projects: ProjectActivities[] = useMemo(() => data?.projects ?? [], [data]);

  const viewModeOf = (name: string): ViewMode => viewModes[name] || 'auto';

  const modeSwitch = (name: string) => (
    <Radio.Group
      optionType="button"
      size="middle"
      value={viewModeOf(name)}
      onChange={(e) => setViewModes((prev) => ({ ...prev, [name]: e.target.value as ViewMode }))}
      options={[
        { label: '自动运维', value: 'auto' },
        { label: '人工告警', value: 'alert' },
      ]}
    />
  );

  const renderProjectBody = (name: string, activities: ActivityItem[] | undefined) => {
    if (viewModeOf(name) === 'alert') {
      return (
        <AlertPanel
          project={name}
          alertsData={alertsData}
          optimistic={optimistic}
          onMarkHandled={(a) => void handleMarkHandled(a)}
        />
      );
    }
    return (
      <ActivityTimeline
        activities={activities ?? []}
        onViewRun={(a) => setViewingRun({ project: a.project || '', spec: a.spec, runId: a.admin_run_id || '' })}
      />
    );
  };

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

    // 单一内容区：按项目分段展示（页签已取消）
    return (
      <div>
        {projects.map((p) => (
          <Card
            key={p.name}
            title={
              <Space wrap size={8}>
                <span>{p.name}</span>
              </Space>
            }
            extra={modeSwitch(p.name)}
            style={{ marginBottom: 16 }}
          >
            {renderProjectBody(p.name, p.activities)}
          </Card>
        ))}
      </div>
    );
  };

  return (
    <PageContainer
      header={{
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
        {renderContent()}
      </Card>
      {viewingRun && (
        <AdminRunModal
          project={viewingRun.project}
          spec={viewingRun.spec}
          adminRunId={viewingRun.runId}
          open={!!viewingRun}
          onClose={() => setViewingRun(null)}
        />
      )}
    </PageContainer>
  );
}
