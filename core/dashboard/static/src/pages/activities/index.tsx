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
import { getAdminActivities, getAlerts, markAlertHandled, STREAM_URL } from '@/services/dashboard';
import type {
  AdminActivitiesData,
  ActivityItem,
  AlertItem,
  AlertsData,
  ProjectActivities,
} from '@/services/dashboard';
import { useIsMobile } from '@/hooks/useIsMobile';
// 告警标题/明细/SEV 常量与 fmtDate 收敛单源（code-review item 5478d16d70c7；
// variant="page" 保留本页既有布局：spec 蓝标签、明细字段分行、完整年月日）
import { AlertLines, AlertTitle, fmtDate } from '@/components/alert-shared';

const REFRESH_THROTTLE_MS = 500;

// 服务端分页页大小：每页 15 条（add-dashboard-paging-and-etag 3.2，design D2
// 的前端切片改为服务端切片——排序与翻页单点在后端，前端只渲染当前页）
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
  stash_pop_conflict: '合并冲突改动滞留',
  mergeback_wip_overlap: '合并被主树改动阻塞',
  verify_uniform_failure: '全场景同因失败',
};

const PRE_WRAP: React.CSSProperties = { whiteSpace: 'pre-wrap' };

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
  // 由下方独立红色区块渲染一次；空 summary 兜底行只保留处置/结果，避免重复。
  const errText = a.error || '';

  // 移动端渐进披露：isMobile && summary.length > 300 时折叠
  const [expanded, setExpanded] = useState(false);
  const shouldFold = isMobile && (a.summary || '').length > 300;

  const body = a.summary ? (
    <div
      style={{
        marginBottom: 8,
        fontSize: 13,
        lineHeight: 1.9,
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
      {`（无叙述总结）处置：${a.actions_taken || '—'} · 结果：${a.result || '—'}`}
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
  total,
  current,
  onPageChange,
  onViewRun,
  isMobile,
}: {
  activities: ActivityItem[];
  /** 服务端过滤后总条数（add-dashboard-paging-and-etag 3.2：分页计数单源） */
  total: number;
  current: number;
  onPageChange: (page: number) => void;
  onViewRun?: (a: ActivityItem) => void;
  isMobile?: boolean;
}) {
  if (!activities || activities.length === 0) {
    return <Empty description="暂无运维记录" />;
  }

  // 服务端分页：activities 已是当前页切片（跨项目全局序），前端不再二次切片
  return (
    <div>
      <Timeline
        items={activities.map((a) => ({
          key: a.id,
          color: a.handled === false ? 'red' : 'gray',
          children: <ActivityCard a={a} onViewRun={onViewRun} isMobile={isMobile} />,
        }))}
      />
      {total > PAGE_SIZE ? (
        <div style={{ display: 'flex', justifyContent: 'flex-end', marginTop: 16 }}>
          <Pagination
            current={current}
            pageSize={PAGE_SIZE}
            total={total}
            onChange={onPageChange}
            showSizeChanger={false}
          />
        </div>
      ) : null}
    </div>
  );
}

type ViewMode = 'auto' | 'alert';

// 加载失败来源（fix 2ca9c5ff7be6）：alerts=人工告警接口，activities=运维记录接口。
// 两路失败共用一个 error state，但横幅按来源区分文案，避免仅告警失败时
// 运维时间线照常渲染却误报「运维记录加载失败」
type LoadError = { source: 'alerts' | 'activities'; message: string };

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
            <List.Item.Meta title={<AlertTitle item={a} variant="page" />} description={<AlertLines item={a} variant="page" />} />
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
                        title={<AlertTitle item={a} resolved variant="page" />}
                        description={<AlertLines item={a} variant="page" />}
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
  const [error, setError] = useState<LoadError | null>(null);
  const [loading, setLoading] = useState(true);
  const lastRefreshRef = useRef(0);
  // add-dashboard-paging-and-etag 3.2：服务端分页当前页（ref 供 SSE 刷新路径
  // 读取最新页码，不经 setState 闭包；与 current state 同步变更）
  const pageRef = useRef(1);
  // fix 4ffc804c77cd: 节流尾沿补拉定时器句柄（useRef 保存防闭包失效，卸载时统一清理）
  const refreshTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  // fix 01635701025b: load 自增请求序号——SSE 刷新与用户翻页触发的 load 可能并发
  // 在飞，仅最新一次请求允许落状态，旧响应到达时直接丢弃，防旧页覆盖新页
  const loadSeqRef = useRef(0);

  const load = useCallback(async () => {
    const seq = ++loadSeqRef.current;
    try {
      const fetchPage = (page: number) => getAdminActivities(undefined, undefined, page, PAGE_SIZE);
      const pageAtStart = pageRef.current;
      // fix 2ca9c5ff7be6: 告警接口的请求级失败（reject）归一到 alerts.error 通道，
      // 与响应级 error 同路径处理——只阻断告警数据上屏，不拖垮运维记录渲染
      const [first, alerts] = await Promise.all([
        fetchPage(pageAtStart),
        getAlerts().catch((e: unknown): AlertsData => ({
          alerts: [],
          error: e instanceof Error ? e.message : String(e),
        })),
      ]);
      let d = first;
      // 总条数收缩导致当前页越界时回退第 1 页重拉一次（design D5 语义保留：
      // SSE 刷新保持页码，仅越界回退；第 1 页恒 ≤ 总页数，不会循环）。
      // 在飞期间用户已翻页（pageRef 变化）则本请求已过期，回退交给新请求处理
      const totalPages = d.total != null ? Math.max(1, Math.ceil(d.total / PAGE_SIZE)) : null;
      if (totalPages != null && pageAtStart > totalPages && pageRef.current === pageAtStart) {
        pageRef.current = 1;
        setCurrent(1);
        d = await fetchPage(1);
      }
      if (seq !== loadSeqRef.current) return;
      setData(d);
      if (!alerts.error) {
        setAlertsData(alerts);
        setError(null);
      } else {
        // fix df39d8bbc138: 告警加载失败必须提示，不能静默——否则首载失败显示误导性空态
        // fix 2ca9c5ff7be6: 标注来源为告警接口，横幅不再误称「运维记录加载失败」
        setError({ source: 'alerts', message: alerts.error });
      }
    } catch (e) {
      // 过期请求的失败同样不落状态，避免旧请求错误覆盖新请求结果
      if (seq !== loadSeqRef.current) return;
      // 告警失败已归一到 alerts.error 通道，走到这里只剩运维记录接口失败
      setError({ source: 'activities', message: e instanceof Error ? e.message : String(e) });
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
    // SSE 实时刷新（对齐 v1：alerts/refresh 事件触发重拉，保持页签与滚动；
    // 端点走 services/dashboard 的 STREAM_URL 单源，不写字面量）
    const es = new EventSource(STREAM_URL);
    es.onmessage = (ev: MessageEvent) => {
      let msg: { type?: string } = {};
      try {
        msg = JSON.parse(ev.data);
      } catch {
        return;
      }
      if (msg.type !== 'alerts' && msg.type !== 'refresh') return;
      // fix 4ffc804c77cd: 节流改尾沿触发——窗口内事件不再直接丢弃，改为排一次
      // 尾沿补拉（pending 已排程则合并），避免静默期尾部变更滞留到下个事件才上屏
      if (refreshTimerRef.current !== null) return;
      const now = Date.now();
      const elapsed = now - lastRefreshRef.current;
      if (elapsed < REFRESH_THROTTLE_MS) {
        refreshTimerRef.current = setTimeout(() => {
          refreshTimerRef.current = null;
          lastRefreshRef.current = Date.now();
          void load();
        }, REFRESH_THROTTLE_MS - elapsed);
        return;
      }
      lastRefreshRef.current = now;
      void load();
    };
    // 卸载必须关闭，防 EventSource 连接泄漏；并同步清理尾沿补拉定时器
    return () => {
      es.close();
      if (refreshTimerRef.current !== null) {
        clearTimeout(refreshTimerRef.current);
        refreshTimerRef.current = null;
      }
    };
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
        // fix df39d8bbc138: 标记失败立即撤销乐观遮蔽，防止 id 滞留 optimistic 永久隐藏告警
        setOptimistic((prev) => prev.filter((id) => id !== a.id));
      }
      void load();
    },
    [load, message],
  );

  const projects: ProjectActivities[] = useMemo(() => data?.projects ?? [], [data]);

  // 分页响应的 projects[] 平铺回全局单数组（服务端已按组内全局相对顺序下发，
  // 平铺即当前页全局序）。客户端排序保留为幂等防御（handled===false 置顶 →
  // created 倒序，与后端 _sort_activities_frontend 同语义）：服务端语义漂移
  // 时显示仍正确，排序单点在服务端（add-dashboard-paging-and-etag 3.2）。
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
      // fix f6adbe97c806: created 存在但非法时 valueOf() 返回 NaN，须归一为 0 再比较
      const xt = x.created && dayjs(x.created).isValid() ? dayjs(x.created).valueOf() : 0;
      const yt = y.created && dayjs(y.created).isValid() ? dayjs(y.created).valueOf() : 0;
      return yt - xt;
    });
  }, [projects]);

  // 服务端翻页：更新页引用并重拉当前页（新页数据到达前保留旧页内容，不闪空态）
  const handlePageChange = useCallback(
    (page: number) => {
      pageRef.current = page;
      setCurrent(page);
      void load();
    },
    [load],
  );

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

    // 自动运维视图：服务端分页的当前页时间线（total 为服务端过滤后总条数）
    return (
      <ActivityTimeline
        activities={allActivities}
        total={data?.total ?? allActivities.length}
        current={current}
        onPageChange={handlePageChange}
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
            {/* fix 2ca9c5ff7be6: 按失败来源区分文案（运维记录 / 人工告警），避免误导失败范围 */}
            <div style={{ color: '#ff4d4f' }}>
              {error.source === 'alerts' ? '人工告警加载失败' : '运维记录加载失败'}：{error.message}
            </div>
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
