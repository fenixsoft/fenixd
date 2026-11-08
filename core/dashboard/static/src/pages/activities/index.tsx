import { PageContainer } from '@ant-design/pro-components';
import { PageTitleBar } from '@/components/PageTitleBar';
import {
  App,
  Button,
  Card,
  Collapse,
  Empty,
  Input,
  List,
  Pagination,
  Popover,
  Select,
  Spin,
  Tabs,
  Tag,
  Timeline,
  Typography,
} from 'antd';
import dayjs from 'dayjs';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useModel } from '@umijs/max';
import Markdown from 'react-markdown';
import remarkBreaks from 'remark-breaks';
import remarkGfm from 'remark-gfm';
import AdminRunModal from './components/AdminRunModal';
import ChainPanel from './components/ChainPanel';
import { markdownComponents } from '@/pages/projects/components/SpecDocModal';
import { getAdminActivities, getAlerts, revertAlertSupersede, STREAM_URL } from '@/services/dashboard';
import type {
  AdminActivitiesData,
  ActivityItem,
  AlertItem,
  AlertsData,
  ProjectActivities,
} from '@/services/dashboard';
import { useIsMobile } from '@/hooks/useIsMobile';
// 裁决选择题交互单源（add-human-adjudication-choices；v2 AlertList 同源）：
// 选择态/附注/执行确认三件套随 hook 走，移植 m-ops r2 告警行形态时复用
import { AlertAdjudicationExec, useAlertAdjudication } from '@/hooks/useAlertAdjudication';
// 乐观遮蔽/标记已处理收敛共享 hook（code-review items d9c50f5bcc38、
// e673281b0b03）：与 overview AlertBanner 同源逻辑单点维护，两页复用
import { useOptimisticAlerts } from '@/hooks/useOptimisticAlerts';
// 告警标题/明细/SEV 常量与 fmtDate 收敛单源（code-review item 5478d16d70c7；
// variant="page" 保留本页既有布局：spec 蓝标签、明细字段分行、完整年月日）
import {
  AlertActionColumn,
  AlertLines,
  AlertReportButton,
  AlertTitle,
  CAUSE_LABEL,
  fmtDate,
  hasNarrativeReport,
} from '@/components/alert-shared';

const REFRESH_THROTTLE_MS = 500;

// SSE 连续重连失败阈值（fix 8fa2edf72bc5）：EventSource 自动重连期间 error 事件
// 会频繁触发，累积到阈值才展示「实时刷新已断开」提示条，避免瞬态抖动闪烁
const SSE_DOWN_THRESHOLD = 3;

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

// remarkPlugins 提为模块级常量（code-review item 4b308c9443d2）：每次渲染新建
// 数组引用会让 react-markdown 对每张卡片的 summary/actions_taken/
// recommended_action 重复 parse 与转换（SSE 节流刷新 500ms 全卡片树重渲染），
// 三处共用同一引用。
const ACTIVITY_REMARK_PLUGINS = [remarkGfm, remarkBreaks];

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
      {/* fix 17c024ffff30: summary 与 actions_taken/recommended_action 统一插件集，
          叙述文本单换行折行口径一致 */}
      <Markdown remarkPlugins={ACTIVITY_REMARK_PLUGINS} components={markdownComponents}>
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
      style={
        isMobile
          ? // 移动端直接行（2026-11-07 运维页移动定稿移植，prototype/m-ops.html r2
            // 批注「宽度有限，去卡片直接显示内容」）：去卡壳，样式交行容器
            { padding: '12px 0', borderRadius: 0 }
          : {
              padding: 12,
              borderRadius: 8,
              border: unhandled ? '1px solid #ff4d4f' : '1px solid #f0f0f0',
              background: unhandled ? '#fff2f0' : '#fafafa',
            }
      }
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
          <Markdown remarkPlugins={ACTIVITY_REMARK_PLUGINS} components={markdownComponents}>
            {a.actions_taken}
          </Markdown>
        </div>
      )}
      {a.recommended_action && (
        <div style={{ fontSize: 13, lineHeight: 1.65 }}>
          <Typography.Text type="secondary">建议：</Typography.Text>
          <Markdown remarkPlugins={ACTIVITY_REMARK_PLUGINS} components={markdownComponents}>
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
  if (isMobile) {
    // 移动端直接行呈现（2026-11-07 运维页移动定稿移植，prototype/m-ops.html r2
    // 批注「宽度有限，去卡片直接显示内容」）：去 Timeline 轨与小卡壳，行间
    // 发丝线分隔，内容净宽让给正文；桌面 Timeline+卡片形态不变
    return (
      <div>
        {activities.map((a, i) => (
          <div key={a.id} style={{ borderTop: i === 0 ? undefined : '1px solid #f0f0f0' }}>
            <ActivityCard a={a} onViewRun={onViewRun} isMobile={isMobile} />
          </div>
        ))}
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

// 页签键（2026-11-05 处置链并入运维页，用户指令）：chain=处置链观测（原
// /chain 独立页迁入）、auto=自动运维记录、alert=告警记录
type TabKey = 'chain' | 'auto' | 'alert';

// 首屏页签：URL ?tab= 预选（/chain 老深链重定向携带 tab=chain），缺省处置链
//（2026-11-05 用户定调）。hash 路由，query 位于 location.hash 的 '?' 之后
function initialTab(): TabKey {
  const tab = new URLSearchParams(window.location.hash.split('?')[1] || '').get('tab');
  return tab === 'auto' || tab === 'alert' ? tab : 'chain';
}

// 加载失败来源（fix 2ca9c5ff7be6）：alerts=人工告警接口，activities=运维记录接口。
// 两路失败共用一个 error state，但横幅按来源区分文案，避免仅告警失败时
// 运维时间线照常渲染却误报「运维记录加载失败」
type LoadError = { source: 'alerts' | 'activities'; message: string };

interface ViewingRun {
  project: string;
  spec?: string;
  runId: string;
  // add-harness-brand-projection 3.2：run meta 的 harness（admin 车道 run 经
  // run_metrics 旁路行透出；存量记录缺失 → undefined → 中性品牌（AI Assistant））
  harness?: string;
}

// 移动端告警直接行（2026-11-07 运维页移动定稿移植，prototype/m-ops.html r2
// ops-alert-list 行形态）：SEV 标题行 + AlertLines 明细单源 + 裁决 choices
// （Select 全宽 + 附注 + 执行）或标记已处理全宽；调查报告入口保留在动作区
// （原型无此件的既有功能面，移植声明的小偏离）。
function MobileAlertRow({
  a,
  onMarkHandled,
  onResolved,
}: {
  a: AlertItem;
  onMarkHandled: (a: AlertItem) => void;
  onResolved: () => void;
}) {
  const adj = useAlertAdjudication();
  const [noteOpen, setNoteOpen] = useState(false);
  const hasChoices = (a.choices || []).length > 0;
  return (
    <div style={{ padding: '10px 0' }}>
      <AlertTitle item={a} variant="page" />
      <AlertLines item={a} variant="page" />
      {hasChoices ? (
        <>
          <Select
            size="small"
            placeholder="选择处置动作"
            style={{ width: '100%', marginTop: 8 }}
            value={adj.alertChoiceSels[a.id] || undefined}
            onChange={(v) => adj.setAlertChoiceSels((s) => ({ ...s, [a.id]: v }))}
            options={(a.choices || []).map((c) => ({ value: c.id, label: c.label, title: c.desc }))}
          />
          <div style={{ display: 'flex', gap: 12, marginTop: 8, alignItems: 'center' }}>
            <Popover
              title="处置附注"
              trigger="click"
              open={noteOpen}
              onOpenChange={setNoteOpen}
              content={
                <div style={{ width: 260 }}>
                  <Input.TextArea
                    rows={2}
                    value={adj.alertNotes[a.id] || ''}
                    onChange={(e) => adj.setAlertNotes((s) => ({ ...s, [a.id]: e.target.value }))}
                    placeholder="随裁决留痕写入（可空）"
                  />
                </div>
              }
            >
              <a className="touch-expand" style={{ fontSize: 12, color: 'rgba(0,0,0,0.45)' }}>
                附注{adj.alertNotes[a.id] ? '·已填' : ''}
              </a>
            </Popover>
            {hasNarrativeReport(a) ? <AlertReportButton text={a.narrative.text} /> : null}
            <span style={{ flex: 1 }} />
            <AlertAdjudicationExec alert={a} adj={adj} onResolved={onResolved} />
          </div>
        </>
      ) : (
        <div style={{ display: 'flex', gap: 12, marginTop: 8, alignItems: 'center' }}>
          {hasNarrativeReport(a) ? <AlertReportButton text={a.narrative.text} /> : null}
          <span style={{ flex: 1 }} />
          <Button size="small" onClick={() => onMarkHandled(a)}>
            标记已处理
          </Button>
        </div>
      )}
    </div>
  );
}

// 告警记录移动 pane（prototype/m-ops.html r2）：未处理直接行 +「收起已解决」
// 紧凑行（已解决 Tag + 单行描述 + 时间；报告入口保留）；桌面 List+Collapse 不变
function MobileAlertPane({
  unhandled,
  resolved,
  onMarkHandled,
  onRevertSupersede,
  onResolved,
}: {
  unhandled: AlertItem[];
  resolved: AlertItem[];
  onMarkHandled: (a: AlertItem) => void;
  onRevertSupersede: (a: AlertItem) => void;
  onResolved: () => void;
}) {
  const [resolvedOpen, setResolvedOpen] = useState(true);
  return (
    <div>
      {unhandled.length ? (
        unhandled.map((a, i) => (
          <div key={a.id} style={i ? { borderTop: '1px solid #f0f0f0' } : undefined}>
            <MobileAlertRow a={a} onMarkHandled={onMarkHandled} onResolved={onResolved} />
          </div>
        ))
      ) : (
        <div style={{ padding: '8px 0 4px', fontSize: 12.5, color: 'rgba(0,0,0,0.45)' }}>暂无未处理告警。</div>
      )}
      {resolved.length ? (
        <div style={{ borderTop: '1px solid #f0f0f0', marginTop: 4, paddingTop: 4 }}>
          <a
            role="button"
            tabIndex={0}
            onClick={() => setResolvedOpen((o) => !o)}
            style={{ fontSize: 12, color: 'rgba(0,0,0,0.45)', display: 'inline-block', padding: '4px 2px' }}
          >
            {resolvedOpen ? '收起已解决' : `已解决 ${resolved.length} 条`}
          </a>
          {resolvedOpen
            ? resolved.map((a) => {
                const isSuperseded = a.handled_by === 'superseded';
                return (
                  <div key={a.id} style={{ display: 'flex', gap: 10, padding: '7px 0', alignItems: 'center' }}>
                    <Tag style={{ marginInlineEnd: 0, flexShrink: 0 }} color={isSuperseded ? 'default' : 'green'}>
                      {isSuperseded ? '已失效' : '已解决'}
                    </Tag>
                    <span
                      style={{
                        fontSize: 12.5,
                        minWidth: 0,
                        flex: 1,
                        overflow: 'hidden',
                        textOverflow: 'ellipsis',
                        whiteSpace: 'nowrap',
                      }}
                    >
                      {a.description || a.id}
                    </span>
                    {hasNarrativeReport(a) ? <AlertReportButton text={a.narrative.text} /> : null}
                    {isSuperseded ? (
                      <a role="button" tabIndex={0} onClick={() => onRevertSupersede(a)} style={{ fontSize: 12, flexShrink: 0 }}>
                        撤销失效
                      </a>
                    ) : null}
                    <span style={{ fontSize: 12, color: 'rgba(0,0,0,0.45)', flexShrink: 0 }}>
                      {fmtDate(a.handled_at || a.created, { withYear: false })}
                    </span>
                  </div>
                );
              })
            : null}
        </div>
      ) : null}
    </div>
  );
}

function AlertPanel({
  alertsData,
  optimistic,
  onMarkHandled,
  onRevertSupersede,
  onResolved,
  isMobile,
}: {
  alertsData: AlertsData | null;
  optimistic: string[];
  onMarkHandled: (a: AlertItem) => void;
  onRevertSupersede: (a: AlertItem) => void;
  onResolved: () => void;
  isMobile?: boolean;
}) {
  // 全局视图：不按项目过滤，仅剔除乐观移除的条目
  const visible = (a: AlertItem) => !optimistic.includes(a.id);
  // 根因筛选（add-provider-validation-alert-governance 4.3）：'' = 全部；
  // cause 缺席的存量记录按 unknown 归组（后端 4.6 首轮回填前的旧账本）
  const [causeFilter, setCauseFilter] = useState('');
  const byCause = (a: AlertItem) => !causeFilter || (a.cause || 'unknown') === causeFilter;
  const unhandled = (alertsData?.alerts || []).filter(visible).filter(byCause);
  const resolvedAll = (alertsData?.resolved || []).filter(visible).filter(byCause);
  // superseded（同根因批量失效）拆独立折叠组：默认收起、灰态呈现 + 撤销入口，
  // 与真正的「已解决」终态视觉区分（误失效可纠错，不与解决语义混淆）
  const superseded = resolvedAll.filter((a) => a.handled_by === 'superseded');
  const resolved = resolvedAll.filter((a) => a.handled_by !== 'superseded');

  const collapseItems = [];
  if (resolved.length) {
    collapseItems.push({
      key: 'resolved',
      label: `已解决 (${resolved.length})`,
      children: (
        <List
          size="small"
          dataSource={resolved}
          renderItem={(a) => (
            <List.Item
              /* 已解决告警保留调查报告入口（处置后补叙照常落盘，
                 历史完整性）；无报告时不传 actions，不出空壳列 */
              actions={
                hasNarrativeReport(a)
                  ? [
                      <AlertActionColumn key="report">
                        <AlertReportButton text={a.narrative.text} />
                      </AlertActionColumn>,
                    ]
                  : undefined
              }
            >
              <List.Item.Meta
                title={<AlertTitle item={a} resolved variant="page" />}
                description={<AlertLines item={a} variant="page" />}
              />
            </List.Item>
          )}
        />
      ),
    });
  }
  if (superseded.length) {
    collapseItems.push({
      key: 'superseded',
      label: `已失效 (${superseded.length})`,
      children: (
        <List
          size="small"
          dataSource={superseded}
          renderItem={(a) => (
            <List.Item
              /* 已失效条目：撤销入口（误失效人工纠错面，恢复未处理态）+
                 调查报告入口照常保留（失效不影响历史可读性） */
              actions={[
                <AlertActionColumn key="ops">
                  {hasNarrativeReport(a) && <AlertReportButton text={a.narrative.text} />}
                  <Button size="small" onClick={() => onRevertSupersede(a)} data-testid="alert-revert-supersede">
                    撤销失效
                  </Button>
                </AlertActionColumn>,
              ]}
            >
              <List.Item.Meta
                title={<AlertTitle item={a} resolved variant="page" />}
                description={<AlertLines item={a} variant="page" />}
              />
            </List.Item>
          )}
        />
      ),
    });
  }

  if (!unhandled.length && !resolvedAll.length) {
    return <Empty description={causeFilter ? '该根因下暂无告警' : '暂无人工告警'} />;
  }

  const causeSelect = (
    <Select
      size="small"
      value={causeFilter}
      onChange={setCauseFilter}
      style={{ minWidth: 140 }}
      data-testid="alert-cause-filter"
      options={[
        { value: '', label: '全部根因' },
        ...Object.entries(CAUSE_LABEL).map(([value, label]) => ({ value, label })),
      ]}
    />
  );

  if (isMobile) {
    return (
      <div>
        <div style={{ padding: '4px 0' }}>{causeSelect}</div>
        <MobileAlertPane
          unhandled={unhandled}
          resolved={resolvedAll}
          onMarkHandled={onMarkHandled}
          onRevertSupersede={onRevertSupersede}
          onResolved={onResolved}
        />
      </div>
    );
  }

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'flex-end', padding: '4px 0' }}>{causeSelect}</div>
      <List
        size="small"
        dataSource={unhandled}
        locale={{ emptyText: causeFilter ? '该根因下暂无未处理告警' : '暂无未处理告警' }}
        renderItem={(a) => (
          <List.Item
            actions={[
              /* 操作按钮竖排列（查看调查报告/标记已处理同列、随最宽者等宽），
                 与 overview 横幅同形态。桌面裁决入口有意收敛在 overview 横幅：
                 横幅消费同一全局告警数据面，含 choices 的告警在横幅侧走
                 Select+附注+执行完整闭环，桌面面板不重复内嵌；本页仅移动端
                 由 MobileAlertRow 行内补齐同款闭环（code-review item 86a887e5e554） */
              <AlertActionColumn key="ops">
                {hasNarrativeReport(a) && <AlertReportButton text={a.narrative.text} />}
                <Button size="small" onClick={() => onMarkHandled(a)}>
                  标记已处理
                </Button>
              </AlertActionColumn>,
            ]}
          >
            <List.Item.Meta title={<AlertTitle item={a} variant="page" />} description={<AlertLines item={a} variant="page" />} />
          </List.Item>
        )}
      />
      {collapseItems.length ? (
        <Collapse
          ghost
          /* 已解决组默认展开（既有行为）；已失效组默认收起（弱化呈现，
             展开后才有逐条撤销入口） */
          defaultActiveKey={['resolved']}
          items={collapseItems}
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
  // 乐观遮蔽单源（items d9c50f5bcc38、e673281b0b03）：optimistic、收敛 effect
  //（确认消失/超时兜底）与 markHandled 包装都在共享 hook 内，与横幅同源
  const { optimistic, markHandled } = useOptimisticAlerts(alertsData);
  const [activeTab, setActiveTab] = useState<TabKey>(initialTab);
  // 处置链页签的单项目聚合筛选：state 提升到宿主页——Select 在标题栏筛选槽
  // 渲染（页签失活即卸载 ChainPanel，提升后筛选选择跨页签切换保持）
  const [project, setProject] = useState<string | undefined>(undefined);
  // 项目选择器选项取全局 initialState.projects（原 /chain 页同源口径）
  const { initialState } = useModel('@@initialState');
  const projectOptions = initialState?.projects || [];
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
  // fix 8fa2edf72bc5: SSE 断流失败态——es 只挂 onmessage 时持续重连失败（代理故障、
  // daemon 停止）期间页面无任何提示，运维记录可能长时间停在陈旧数据而用户无感知。
  // 连续失败达 SSE_DOWN_THRESHOLD 才置位；连接恢复由 onopen / onmessage 自动消除
  const [streamDown, setStreamDown] = useState(false);
  const sseFailCountRef = useRef(0);

  const load = useCallback(async () => {
    const seq = ++loadSeqRef.current;
    try {
      const fetchPage = (page: number) => getAdminActivities(undefined, undefined, page, PAGE_SIZE);
      const pageAtStart = pageRef.current;
      // fix 2ca9c5ff7be6: 告警接口的请求级失败（reject）归一到 alerts.error 通道，
      // 与响应级 error 同路径处理——只阻断告警数据上屏，不拖垮运维记录渲染
      // code-review item 7dc0791dcba5: 改 Promise.allSettled 双 settle——运维记录
      // 接口同时失败时不再让 Promise.all 短路进外层 catch、把已归一的告警错误
      // 整体丢弃；双失败横幅合并两侧来源文案
      const [activitiesRes, alertsRes] = await Promise.allSettled([
        fetchPage(pageAtStart),
        getAlerts(),
      ]);
      // fix 7d23b9e8d1bc: 过期检查提前到所有 await 之后、越界回退之前——过期请求
      // 直接丢弃，不改写 pageRef/setCurrent、不触发补拉，避免旧响应把页码改成 1
      // 而破坏新请求的 `pageRef.current === pageAtStart` 守卫，致越界页被直接上屏
      if (seq !== loadSeqRef.current) return;
      // 告警侧失败归一（原 getAlerts().catch 形态等价搬移）
      const alerts: AlertsData =
        alertsRes.status === 'fulfilled'
          ? alertsRes.value
          : {
              alerts: [],
              error:
                alertsRes.reason instanceof Error ? alertsRes.reason.message : String(alertsRes.reason),
            };
      if (activitiesRes.status === 'rejected') {
        // 运维记录接口失败：合并透出两侧原因（双失败时告警侧不再被整体丢弃）
        // fix 5d51d0d16083: 落横幅前先上屏告警一路已成功拉取的数据——否则告警
        // fulfilled 时数据随 rejected 分支整体丢弃，告警视图误渲染空态
        if (!alerts.error) setAlertsData(alerts);
        const actMsg =
          activitiesRes.reason instanceof Error
            ? activitiesRes.reason.message
            : String(activitiesRes.reason);
        setError({
          source: 'activities',
          message: alerts.error ? `${actMsg}；告警加载失败：${alerts.error}` : actMsg,
        });
        return;
      }
      let d = activitiesRes.value;
      // 总条数收缩导致当前页越界时回退第 1 页重拉一次（design D5 语义保留：
      // SSE 刷新保持页码，仅越界回退；第 1 页恒 ≤ 总页数，不会循环）。
      // 在飞期间用户已翻页（pageRef 变化）则本请求已过期，回退交给新请求处理
      const totalPages = d.total != null ? Math.max(1, Math.ceil(d.total / PAGE_SIZE)) : null;
      if (totalPages != null && pageAtStart > totalPages && pageRef.current === pageAtStart) {
        pageRef.current = 1;
        setCurrent(1);
        try {
          d = await fetchPage(1);
        } catch (e) {
          // fix af1b26684e93: 补拉第 1 页失败时按进入 load 时的快照回滚页码——
          // setData 不会执行、时间线仍上屏 pageAtStart 的旧页内容，分页指示须与
          // 其保持一致；pageRef 已非 1 说明用户在飞翻页，回滚交新请求处理勿覆盖。
          // 回滚后 rethrow，错误横幅仍由外层 catch 统一落位
          if (pageRef.current === 1) {
            pageRef.current = pageAtStart;
            setCurrent(pageAtStart);
          }
          throw e;
        }
      }
      // 二次检查保留：越界补拉第 1 页是第二个 await，期间可能有新请求启动，
      // 状态写入前仍需复核序号（非越界路径为幂等复查，无窗口）
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
      // fix 9fc948945fc7: 收尾置 false 同样纳入序号守卫——旧请求先完成时
      // 不抢在并发中的新请求之前撤掉加载指示，避免首屏短暂闪空态
      if (seq === loadSeqRef.current) setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
    // SSE 实时刷新（对齐 v1：alerts/refresh 事件触发重拉，保持页签与滚动；
    // 端点走 services/dashboard 的 STREAM_URL 单源，不写字面量）
    const es = new EventSource(STREAM_URL);
    // fix 8fa2edf72bc5: 连接（重新）建立即复位失败计数并消除断流提示条
    es.onopen = () => {
      sseFailCountRef.current = 0;
      setStreamDown(false);
    };
    es.onmessage = (ev: MessageEvent) => {
      let msg: { type?: string } = {};
      try {
        msg = JSON.parse(ev.data);
      } catch {
        return;
      }
      // fix 8fa2edf72bc5: 能收到消息即连接存活——复位计数并消除断流提示条
      sseFailCountRef.current = 0;
      setStreamDown(false);
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
    // fix 8fa2edf72bc5: 自动重连期间 error 频繁触发（readyState===CONNECTING 表示
    // 正在重连），累积连续失败达阈值才提示，避免瞬态抖动闪烁；CLOSED（非 200 响应
    // 等浏览器已放弃重连）直接提示。恢复由上方 onopen / onmessage 自动消除。
    es.onerror = () => {
      sseFailCountRef.current += 1;
      if (es.readyState === EventSource.CLOSED || sseFailCountRef.current >= SSE_DOWN_THRESHOLD) {
        setStreamDown(true);
      }
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

  const handleMarkHandled = useCallback(
    async (a: AlertItem) => {
      // markHandled（hook 单源）：成功返回 null、失败已回滚并返回错误文案
      const err = await markHandled(a);
      if (err == null) message.success('已标记处理');
      else message.error(`标记失败：${err}`);
      void load();
    },
    [load, markHandled, message],
  );

  // add-provider-validation-alert-governance 4.3：superseded 失效标记撤销
  // （误失效人工纠错面，恢复未处理态）。a.project 全局视图必有（后端聚合
  // 下发），缺失走 requireProject 的显式报错而非静默发失败请求。
  const handleRevertSupersede = useCallback(
    async (a: AlertItem) => {
      try {
        await revertAlertSupersede(a.project, a.id);
        message.success('已撤销失效标记，告警恢复未处理');
      } catch (e) {
        message.error(`撤销失败：${e instanceof Error ? e.message : String(e)}`);
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
    (a: ActivityItem) => setViewingRun({ project: a.project || '', spec: a.spec, runId: a.admin_run_id || '', harness: a.harness }),
    [],
  );

  // 自动运维记录页签内容：首载转圈 + 服务端分页的当前页时间线（total 为服务端
  // 过滤后总条数）。原嵌套 Card 已随 Radio→Tabs 改版去掉——页签容器本身在 Card 内
  const renderAutoPane = () => {
    if (loading && !data) {
      return (
        <div style={{ textAlign: 'center', padding: 48 }}>
          <Spin size="large" />
        </div>
      );
    }
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
    <>
      {/* 统一标题栏声明（unified-page-title-bar 2.1）：副标题罩住三页签数据面；
          处置链页签激活时筛选槽放单项目聚合 Select（原 /chain 页顶栏筛选位形态） */}
      <PageTitleBar
        title="运维"
        subtitle="跨项目 Administrator 活动与处置链观测"
        filters={
          activeTab === 'chain' ? (
            <Select
              allowClear
              placeholder="全部项目"
              style={{ minWidth: 200 }}
              value={project}
              onChange={(v) => setProject(v)}
              options={projectOptions.map((name) => ({ value: name, label: name }))}
            />
          ) : undefined
        }
      />
      <PageContainer title={false} breadcrumbRender={false} pageHeaderRender={false}>
      {/* fix 8fa2edf72bc5: SSE 连续重连失败提示条——断连期间实时刷新静默失效，
          运维记录/告警可能停留在陈旧数据；连接恢复后由 onopen / onmessage 自动消除。
          两横幅仅属自动运维记录/告警记录两路数据（处置链有独立 fail-soft Alert，
          数据不同源不混报），处置链页签激活时不展示 */}
      {activeTab !== 'chain' && streamDown ? (
        <div style={{ marginBottom: 16 }}>
          <Card styles={{ body: isMobile ? { padding: '12px 4px' } : undefined }}>
            <Typography.Text type="warning">
              实时刷新已断开：页面数据可能不是最新，正在尝试重连
            </Typography.Text>
          </Card>
        </div>
      ) : null}
      {activeTab !== 'chain' && error ? (
        <div style={{ marginBottom: 16 }}>
          <Card styles={{ body: isMobile ? { padding: '12px 4px' } : undefined }}>
            {/* fix 2ca9c5ff7be6: 按失败来源区分文案（运维记录 / 人工告警），避免误导失败范围 */}
            <div style={{ color: '#ff4d4f' }}>
              {error.source === 'alerts' ? '人工告警加载失败' : '运维记录加载失败'}：{error.message}
            </div>
          </Card>
        </div>
      ) : null}
      {/* 三页签（2026-11-05 处置链并入，用户指令）：页签内容按激活态条件渲染——
          处置链页签失活即卸载（30s 轮询随卸载停止，项目筛选在宿主页保持），
          自动运维/告警状态本就在宿主页，重挂零成本 */}
      {/* 卡体顶 24px 归零（2026-11-05 用户指令「页签上方空白减少 24px」）：
          该空白恰为 Card body 默认 padding-top（实测页头带 56→页签栏 80），
          页签栏贴卡体顶沿即可。移动端每侧 16px（2026-11-07 用户指令两段收敛：
          「左右边距太宽」24→12 后「改到 16px」——antd body 缺省 24 + 外层
          容器 12，body 左右收到 4px 使每侧合计 16px）；桌面 24px 惯例不变 */}
      <Card variant="borderless" styles={{ body: isMobile ? { padding: '0 4px 12px' } : { paddingTop: 0 } }}>
        <Tabs
          data-testid="view-mode-switch"
          activeKey={activeTab}
          onChange={(k) => setActiveTab(k as TabKey)}
          items={[
            {
              key: 'chain',
              label: '处置链',
              children: activeTab === 'chain' ? <ChainPanel project={project} /> : null,
            },
            {
              key: 'auto',
              label: '自动运维记录',
              children: activeTab === 'auto' ? renderAutoPane() : null,
            },
            {
              key: 'alert',
              label: '告警记录',
              children:
                activeTab === 'alert' ? (
                  <AlertPanel
                    alertsData={alertsData}
                    optimistic={optimistic}
                    onMarkHandled={(a) => void handleMarkHandled(a)}
                    onRevertSupersede={(a) => void handleRevertSupersede(a)}
                    onResolved={() => void load()}
                    isMobile={isMobile}
                  />
                ) : null,
            },
          ]}
        />
      </Card>
      {viewingRun && (
        <AdminRunModal
          project={viewingRun.project}
          spec={viewingRun.spec}
          adminRunId={viewingRun.runId}
          harness={viewingRun.harness}
          open={!!viewingRun}
          onClose={() => setViewingRun(null)}
        />
      )}
      </PageContainer>
    </>
  );
}
