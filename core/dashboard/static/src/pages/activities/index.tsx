import { PageContainer } from '@ant-design/pro-components';
import {
  App,
  Button,
  Card,
  Collapse,
  Empty,
  List,
  Pagination,
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
import { useIsMobile } from '@/hooks/useIsMobile';

const REFRESH_THROTTLE_MS = 500;

// 前端分页：每页 15 条，翻页时再渲染其余记录（design D2）
const PAGE_SIZE = 15;

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

function ActivityCard({ a, onViewRun, isMobile }: { a: ActivityItem; onViewRun?: (a: ActivityItem) => void; isMobile?: boolean }) {
  const unhandled = a.handled === false;
  // fix-admin-disposition-empty-shell：失败处置自解释——error 携带 CLI 失败原因，
  // 空 summary 兜底文案同步附带 error，空壳卡片（仅时间+spec）不再出现。
  const errText = a.error || '';

  // 移动端渐进披露：isMobile && summary.length > 300 时折叠
  const [expanded, setExpanded] = useState(false);
  const shouldFold = isMobile && (a.summary || '').length > 300;

  const body = a.summary ? (
    <div
      style={{
        marginBottom: 8,
        fontSize: 13,
        lineHeight: 1.65,
        maxHeight: shouldFold && !expanded ? 88 : undefined,
        overflow: shouldFold && !expanded ? 'hidden' : undefined,
        position: shouldFold && !expanded ? 'relative' : undefined,
        maskImage: shouldFold && !expanded ? 'linear-gradient(to bottom, black 60%, transparent 100%)' : undefined,
        WebkitMaskImage: shouldFold && !expanded ? 'linear-gradient(to bottom, black 60%, transparent 100%)' : undefined,
      }}
    >
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
      data-testid="activity-card"
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
          <Button type="link" size="small" className="touch-expand" onClick={() => onViewRun(a)}>
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
      {shouldFold && (
        <div style={{ textAlign: 'right', marginTop: 4 }}>
          <Button type="link" size="small" className="touch-expand" onClick={() => setExpanded(!expanded)}>
            {expanded ? '收起' : '展开全文'}
          </Button>
        </div>
      )}
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
  current,
  onPageChange,
  onViewRun,
  isMobile,
}: {
  activities: ActivityItem[];
  current: number;
  onPageChange: (page: number) => void;
  onViewRun?: (a: ActivityItem) => void;
  isMobile?: boolean;
}) {
  if (!activities || activities.length === 0) {
    return <Empty description="暂无运维记录" />;
  }

  // 前端分页：仅渲染当前页对应的记录（未翻到的页不渲染）
  const start = (current - 1) * PAGE_SIZE;
  const pageItems = activities.slice(start, start + PAGE_SIZE);

  return (
    <div>
      <Timeline
        items={pageItems.map((a) => ({
          key: a.id,
          color: a.handled === false ? 'red' : 'gray',
          children: <ActivityCard a={a} onViewRun={onViewRun} isMobile={isMobile} />,
        }))}
      />
      {activities.length > PAGE_SIZE ? (
        <div style={{ display: 'flex', justifyContent: 'flex-end', marginTop: 16 }}>
          <Pagination
            current={current}
            pageSize={PAGE_SIZE}
            total={activities.length}
            onChange={onPageChange}
            showSizeChanger={false}
          />
        </div>
      ) : null}
    </div>
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
      {item.project ? <Tag>{item.project}</Tag> : null}
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
  alertsData,
  optimistic,
  onMarkHandled,
}: {
  alertsData: AlertsData | null;
  optimistic: string[];
  onMarkHandled: (a: AlertItem) => void;
}) {
  // 全局视图：不按项目过滤，仅剔除乐观移除的条目
  const visible = (a: AlertItem) => !optimistic.includes(a.id);
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
          defaultActiveKey={['resolved']}
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
  const isMobile = useIsMobile();
  const [data, setData] = useState<AdminActivitiesData | null>(null);
  const [alertsData, setAlertsData] = useState<AlertsData | null>(null);
  const [optimistic, setOptimistic] = useState<string[]>([]);
  const [viewMode, setViewMode] = useState<ViewMode>('auto');
  const [current, setCurrent] = useState(1);
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

  // 跨项目合并为全局单数组：handled===false 置顶优先，组内按 created 倒序（design D2）
  const allActivities = useMemo(() => {
    const flattened: ActivityItem[] = [];
    for (const p of projects) {
      for (const a of p.activities ?? []) {
        flattened.push({ ...a, project: a.project || p.name });
      }
    }
    return flattened.sort((x, y) => {
      if (x.handled === false && y.handled !== false) return -1;
      if (x.handled !== false && y.handled === false) return 1;
      const xt = x.created ? dayjs(x.created).valueOf() : 0;
      const yt = y.created ? dayjs(y.created).valueOf() : 0;
      return yt - xt;
    });
  }, [projects]);

  const totalPages = Math.max(1, Math.ceil(allActivities.length / PAGE_SIZE));

  // SSE 刷新重拉后保持当前页码；总页数小于当前页时回退第 1 页（design D5）
  useEffect(() => {
    setCurrent((prev) => {
      if (prev > totalPages) return 1;
      return prev;
    });
  }, [totalPages]);

  const handleViewRun = useCallback(
    (a: ActivityItem) => setViewingRun({ project: a.project || '', spec: a.spec, runId: a.admin_run_id || '' }),
    [],
  );

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

    if (viewMode === 'alert') {
      // 人工告警视图：全部项目合并展示（不按项目过滤）
      return (
        <AlertPanel
          alertsData={alertsData}
          optimistic={optimistic}
          onMarkHandled={(a) => void handleMarkHandled(a)}
        />
      );
    }

    // 自动运维视图：跨项目合并全局时间线
    return (
      <ActivityTimeline
        activities={allActivities}
        current={current}
        onPageChange={setCurrent}
        onViewRun={handleViewRun}
        isMobile={isMobile}
      />
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
        <div style={{ marginBottom: 16 }}>
          <Radio.Group
            data-testid="view-mode-switch"
            optionType="button"
            size="middle"
            value={viewMode}
            onChange={(e) => setViewMode(e.target.value as ViewMode)}
            options={[
              { label: '自动运维', value: 'auto' },
              { label: '人工告警', value: 'alert' },
            ]}
          />
        </div>
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
