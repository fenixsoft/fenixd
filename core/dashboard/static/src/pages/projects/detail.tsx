import { PageContainer } from '@ant-design/pro-components';
import { Alert, App, Badge, Button, Card, Checkbox, Collapse, Descriptions, Dropdown, Empty, Image, Progress, Space, Spin, Tabs, Tag, Timeline, Tooltip, Typography } from 'antd';
import { CloseOutlined, DownOutlined, ExclamationCircleFilled, FullscreenOutlined, InfoCircleFilled } from '@ant-design/icons';
import { useCallback, useEffect, useRef, useState } from 'react';
import { history, useParams } from '@umijs/max';
import dayjs from 'dayjs';
import Markdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { clearSpecError, getAlerts, getSpecDetail, getSpecs, markAlertHandled, statusMeta } from '@/services/dashboard';
import type { AlertItem, SpecDetail, SpecSummary } from '@/services/dashboard';
import { markdownComponents } from './components/SpecDocModal';
import SpecDocModal from './components/SpecDocModal';
import type { DocType } from './components/SpecDocModal';
import RunRecordModal from './components/RunRecordModal';
import { ClaudeOutputPane } from '@/components/claude-msg';
import { OutlinedTag } from '@/components/StatusTag';
import { useIsMobile } from '@/hooks/useIsMobile';
import { fetchProposalWhy } from '@/utils/proposalWhy';

// 与 v2 static/app.js renderVerdict 保持同一判定逻辑：
// parse_verdict 的 status 串自带 emoji 前缀（如 "❌ 未通过（Bug Found）"），先剥离再判定，
// 避免与 AntD Tag 的配色语义重复；产品Bug>0 → error，环境问题>0 → warning，其余 → success。
const VERDICT_EMOJI_RE = /^[\s\u{1F300}-\u{1FAFF}\u{2600}-\u{27BF}\u{2190}-\u{21FF}\u{2B00}-\u{2BFF}\u{FE0F}\u{2705}\u{274C}\u{26A0}]+/u;

function verdictTone(v: NonNullable<SpecDetail['verdict']>): { color: 'success' | 'warning' | 'error'; label: string } {
  const s = v.summary || {};
  const num = (x: string | null | undefined) => parseInt(x || '', 10) || 0;
  const status = (v.status || '').replace(VERDICT_EMOJI_RE, '');
  if (num(s.product_bugs) > 0 || /未通过|Bug Found|失败/.test(status)) {
    return { color: 'error', label: '❌ 未通过' };
  }
  if (num(s.env_issues) > 0 || /环境|无法验证|不可达|unreachable/i.test(status)) {
    return { color: 'warning', label: '⚠️ 有环境差异' };
  }
  return { color: 'success', label: '✅ 通过' };
}

const VERDICT_COUNTS: Array<[keyof NonNullable<SpecDetail['verdict']>['summary'] & string, string]> = [
  ['passed', '通过'],
  ['failed', '失败'],
  ['errors', '错误'],
  ['product_bugs', '产品Bug'],
  ['env_issues', '环境问题'],
];

// 断言类型中文标签（对齐 core/verify_engine/scenarios.py 的 18 种 type；未收录值原样显示）
const ASSERTION_LABELS: Record<string, string> = {
  element_visible: '元素可见',
  element_count: '元素数量',
  element_not_exist: '元素不存在',
  element_focused: '元素聚焦',
  element_enabled: '元素可用',
  no_click_interception: '点击不被拦截',
  no_overlap: '无元素重叠',
  in_viewport: '在视口内',
  z_index_order: '层叠顺序正确',
  text_match: '文本匹配',
  text_contains: '包含文本',
  attribute_match: '属性匹配',
  no_console_error: '无控制台报错',
  no_network_error: '无网络错误',
  no_auth_error: '无认证错误',
  dom_structure: 'DOM 结构正确',
  no_overflow: '无溢出',
  alignment: '对齐正常',
};

// 断言类型值 → 中文标签；bug.assertion 可能是「type + 附加说明」自由文本，命中前缀时仅替换前缀
function assertionLabel(type?: string): string {
  if (!type) return '?';
  if (ASSERTION_LABELS[type]) return ASSERTION_LABELS[type];
  const hit = Object.keys(ASSERTION_LABELS).find((k) => type.startsWith(k));
  return hit ? `${ASSERTION_LABELS[hit]} ${type.slice(hit.length)}` : type;
}

type AssertionResultItem = NonNullable<
  NonNullable<SpecDetail['scenarios']>[number]['assertion_results']
>[number];

// 断言行明细摘要：优先设计 label / 结果 message；通过断言常缺省这两者，
// 按引擎输出字段（core/verify_engine/assertions.py 口径）分类型组装可读文本
function assertionDetail(a: AssertionResultItem): string {
  if (a.label) return a.label;
  if (a.message) return a.message;
  switch (a.type) {
    case 'element_count':
      return `期望 ${a.expected ?? 1} 个，实际 ${a.actual ?? '?'} 个`;
    case 'element_not_exist':
      return a.actual_count != null ? `页面残留 ${a.actual_count} 个` : '';
    case 'text_match': {
      const modeWord = a.mode === 'regex' ? '匹配正则' : a.mode === 'contains' ? '包含' : '等于';
      const actual = a.actual != null && a.actual !== '' ? `，实际「${a.actual}」` : '';
      return `${modeWord}「${a.expected ?? ''}」${actual}`;
    }
    case 'text_contains':
      return a.text ? `包含「${a.text}」` : '';
    case 'attribute_match': {
      const actual = a.actual != null ? `，实际「${a.actual}」` : '';
      return `${a.attribute || '属性'} ${a.expected != null ? `期望「${a.expected}」` : ''}${actual}`;
    }
    case 'no_console_error': {
      const filtered = (a.filtered_network || []).length;
      return `错误 ${(a.errors || []).length} 条${filtered ? `（已过滤网络类 ${filtered} 条）` : ''}`;
    }
    case 'no_network_error':
      return `错误请求 ${(a.errors || []).length} 条`;
    case 'no_auth_error': {
      const m = a.matched || [];
      return m.length ? `命中关键词: ${m.join('、')}` : '关键词 0 命中';
    }
    case 'dom_structure':
      return `${a.parent || '?'} ${a.relation === 'direct-child' ? '直接包含' : '包含'} ${a.child || '?'}`;
    case 'z_index_order':
      return `${a.selector || '?'} 的 z-index ${a.z_index_self ?? '?'} ${a.operator || '>'} ${a.z_index_compare ?? '?'}（对比 ${a.compare_selector || '?'}）`;
    default:
      return a.selector || '';
  }
}

// overview「任务进度」同款进度条控件：大百分比 + 已完成 x/y + 渐变进度条（验证进度/任务清单共用）
function ProgressBarTile({ done, total }: { done: number; total: number }) {
  const p = total > 0 ? Math.round((done / total) * 100) : 0;
  return (
    <>
      <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', margin: '4px 0 10px', flexWrap: 'wrap' }}>
        <span style={{ fontSize: 28, fontWeight: 600, lineHeight: '40px' }}>{p}%</span>
        <span>
          <Typography.Text type="secondary">已完成 </Typography.Text>
          <Typography.Text strong>
            {done} / {total}
          </Typography.Text>
        </span>
      </div>
      <Progress
        percent={p}
        strokeColor={{ '0%': '#108ee9', '100%': '#87d068' }}
        status="active"
        style={{ marginBottom: 12 }}
      />
    </>
  );
}

function VerdictPanel({ verdict }: { verdict: NonNullable<SpecDetail['verdict']> }) {
  const tone = verdictTone(verdict);
  const s = verdict.summary || {};
  const counts = VERDICT_COUNTS.filter(([k]) => s[k] != null).map(([k, label]) => `${label} ${s[k]}`);
  const status = (verdict.status || '').replace(VERDICT_EMOJI_RE, '');
  return (
    <div>
      <Space size={8} style={{ marginBottom: 8 }} wrap>
        <Tag color={tone.color}>{tone.label}</Tag>
        {status && <Typography.Text strong>{status}</Typography.Text>}
        {verdict.status_detail && <Typography.Text type="secondary">{verdict.status_detail}</Typography.Text>}
      </Space>
      {counts.length > 0 && (
        <div style={{ marginBottom: 8 }}>
          {counts.map((c) => (
            <Tag key={c}>{c}</Tag>
          ))}
        </div>
      )}
      {verdict.conclusion && (
        <div style={{ marginBottom: 0 }}>
          <Markdown remarkPlugins={[remarkGfm]} components={markdownComponents}>
            {verdict.conclusion}
          </Markdown>
        </div>
      )}
    </div>
  );
}

// 告警严重度标签/配色（与 overview AlertBanner 同语义）
const SEV_LABEL: Record<string, string> = { critical: '严重', major: '较高', minor: '一般' };
const SEV_COLOR: Record<string, string> = { critical: 'red', major: 'orange', minor: 'blue' };

// Agent 中文名（与设置页 Agent 模型角色中文名对应；implementer 沿用「开发」）。
// agent_type 为泛型 'agent' 或缺失时，按 run_id 前缀（admin-/impl-/test-/verify-）判别。
const AGENT_LABEL: Record<string, string> = {
  implementer: '开发 Agent',
  planner: '规划 Agent',
  'planner-plan': '生成场景 Agent',
  'planner-judge': '判定结果 Agent',
  verifier: '验证 Agent',
  tester: '测试 Agent',
  administrator: '运维 Agent',
};

const RUN_ID_PREFIX_LABEL: Record<string, string> = {
  impl: '开发 Agent',
  admin: '运维 Agent',
  test: '测试 Agent',
  verify: '验证 Agent',
};

function agentLabel(item: { agent_type?: string; run_id?: string }): string {
  const t = (item.agent_type || '').toLowerCase();
  if (t && AGENT_LABEL[t]) return AGENT_LABEL[t];
  const prefix = (item.run_id || '').toLowerCase().split('-')[0];
  if (prefix && RUN_ID_PREFIX_LABEL[prefix]) return RUN_ID_PREFIX_LABEL[prefix];
  return t || '未知 Agent';
}

// 回退原因含「verification report」时渲染为链接（点击打开验证报告弹窗）
const VERIFICATION_LINK_RE = /^(.*?)verification report(.*)$/i;

function ReasonText({ reason, onOpenReport }: { reason: string; onOpenReport: () => void }) {
  const m = reason.match(VERIFICATION_LINK_RE);
  if (!m) return <Typography.Text type="secondary">{reason}</Typography.Text>;
  return (
    <Typography.Text type="secondary">
      {m[1]}
      <a onClick={onOpenReport}>verification report</a>
      {m[2]}
    </Typography.Text>
  );
}

export default function SpecDetailPage() {
  const { name = '', spec = '' } = useParams<{ name: string; spec: string }>();
  const isMobile = useIsMobile();
  const [detail, setDetail] = useState<SpecDetail | null>(null);
  const [specAlerts, setSpecAlerts] = useState<AlertItem[]>([]);
  const [docModalOpen, setDocModalOpen] = useState(false);
  // SPEC 下拉快速切换：项目下所有 SPEC 列表（复用列表页 getSpecs，失败静默为空）
  const [specList, setSpecList] = useState<SpecSummary[]>([]);
  const [switchOpen, setSwitchOpen] = useState(false);
  const [recordRunId, setRecordRunId] = useState<string | null>(null);
  // 文档弹窗打开时定位的页签（时间轴报告链接 → 验证报告；项目信息「文档」→ 需求背景）
  const [docInitial, setDocInitial] = useState<DocType>('proposal');
  // 告警内容默认折叠（只显示标题），展开后的告警 id 集合
  const [expandedAlerts, setExpandedAlerts] = useState<Set<string>>(new Set());
  // 场景结果状态过滤（'' = 全部）
  const [scenarioFilter, setScenarioFilter] = useState<'pass' | 'warning' | 'fail' | 'error' | ''>('');
  // 任务背景描述 = proposal 文档 ## Why 段（spec 列表悬停同名内容），懒加载
  const [proposalWhy, setProposalWhy] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  const toggleAlert = (id: string) => {
    setExpandedAlerts((prev) => {
      const next = new Set(prev);
      if (next.has(id)) {
        next.delete(id);
      } else {
        next.add(id);
      }
      return next;
    });
  };

  useEffect(() => {
    if (!name || !spec) return;

    // SSE 热更新：后台刷新必须静默原位进行——不能走 setLoading（整页被
    // Spin 替换再重建，交互状态全丢、agent 运行期间页面持续闪烁）。
    // applyDetail 以 JSON 内容判等，数据无变化时跳过 setState 避免无谓重渲染。
    const lastDetailRef = { current: '' };
    const applyDetail = (data: SpecDetail) => {
      const serialized = JSON.stringify(data);
      if (serialized === lastDetailRef.current) return;
      lastDetailRef.current = serialized;
      setDetail(data);
    };

    const load = async (initial = false) => {
      try {
        if (initial) setLoading(true);
        const data = await getSpecDetail(name, spec);
        applyDetail(data);
        if (initial) setError('');
      } catch (e) {
        // 后台刷新失败静默保留旧视图，只有首次加载才呈现错误页
        if (initial) setError(e instanceof Error ? e.message : String(e));
      } finally {
        if (initial) setLoading(false);
      }
    };

    void load(true);

    // watcher 的 detail/state 事件自带完整详情可直接采用；
    // run_meta/refresh 只带轻量通知，节流后重拉 REST（与 list.tsx 同策略）。
    const REFRESH_THROTTLE_MS = 500;
    let lastRefresh = 0;
    const throttledLoad = () => {
      const now = Date.now();
      if (now - lastRefresh < REFRESH_THROTTLE_MS) return;
      lastRefresh = now;
      void load();
    };
    const es = new EventSource('/api/stream');
    es.onmessage = (ev: MessageEvent) => {
      let msg: {
        type?: string; project?: string; spec?: string;
        data?: SpecDetail; details?: Record<string, SpecDetail>;
      } = {};
      try {
        msg = JSON.parse(ev.data);
      } catch {
        return;
      }
      if (msg.type === 'detail' && msg.project === name && msg.spec === spec && msg.data) {
        applyDetail(msg.data);
        return;
      }
      if (msg.type === 'state' && msg.project === name) {
        const d = msg.details?.[spec];
        if (d) {
          applyDetail(d);
          return;
        }
        // 本 SPEC 条目未变但项目有变化（如日志新增/其他 SPEC 变更）：
        // 时间轴取自日志，节流重拉兜底（与 list.tsx 同策略）
        throttledLoad();
      }
      if (msg.type === 'run_meta' || msg.type === 'refresh') {
        throttledLoad();
      }
    };
    return () => es.close();
  }, [name, spec]);

  const { message } = App.useApp();

  // 本 SPEC 的人工升级告警（未处理），拉取失败静默不影响主视图
  const loadSpecAlerts = useCallback(() => {
    getAlerts()
      .then((d) => {
        setSpecAlerts((d.alerts || []).filter((a) => a.project === name && a.spec === spec));
      })
      .catch(() => {});
  }, [name, spec]);

  useEffect(() => {
    loadSpecAlerts();
  }, [loadSpecAlerts]);

  // 任务背景描述懒加载（proposal ## Why），spec 切换时重取
  useEffect(() => {
    let cancelled = false;
    if (!name || !spec) return;
    fetchProposalWhy(name, spec).then((text) => {
      if (!cancelled) setProposalWhy(text);
    });
    return () => {
      cancelled = true;
    };
  }, [name, spec]);

  // 下拉快速切换数据源：项目变化时拉一次 SPEC 列表（复用列表页 getSpecs）。
  // 下拉是低频辅助信息，不为其建立 SSE 通道；失败时静默保持为空（箭头不展示），不影响详情页主体。
  useEffect(() => {
    let cancelled = false;
    if (!name) return;
    getSpecs(name)
      .then((d) => {
        if (!cancelled) setSpecList(d.specs || []);
      })
      .catch(() => {
        if (!cancelled) setSpecList([]);
      });
    return () => {
      cancelled = true;
    };
  }, [name]);

  const statusInfo = statusMeta(detail?.status || '');

  // 下拉快速切换项：项目下除当前 SPEC 外的其他 SPEC（只有当前一个时不展示箭头）
  const otherSpecs = specList.filter((s) => s.name !== spec);

  // 下拉快速切换面板（表格形式）：SPEC 名称（过长截断 + 悬停提示） + 状态标签（statusMeta 同列表页语义）。
  // 面板宽度上限 300px 且移动端不超出视口（max-width: calc(100vw - 32px)），内容区限高滚动。
  const renderSpecSwitch = () => (
    <div
      className="spec-quick-switch-panel"
      style={{
        width: 300,
        maxWidth: 'calc(100vw - 32px)',
        background: '#fff',
        border: '1px solid #f0f0f0',
        borderRadius: 8,
        boxShadow: '0 6px 16px 0 rgba(0, 0, 0, 0.08), 0 3px 6px -4px rgba(0, 0, 0, 0.12)',
        overflow: 'hidden',
      }}
    >
      <div style={{ maxHeight: '60vh', overflow: 'auto', padding: 4 }}>
        {otherSpecs.map((s) => {
          const m = statusMeta(s.status || '');
          return (
            <div
              key={s.name}
              className="spec-quick-switch-row"
              onClick={() => {
                setSwitchOpen(false);
                history.push(`/projects/${name}/${s.name}`);
              }}
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: 12,
                padding: '8px 10px',
                borderRadius: 6,
                cursor: 'pointer',
                color: 'inherit',
              }}
            >
              <Typography.Text ellipsis={{ tooltip: s.name }} style={{ flex: 1, minWidth: 0, fontSize: 13 }}>
                {s.name}
              </Typography.Text>
              <OutlinedTag tone={m.tone}>{m.label}</OutlinedTag>
            </div>
          );
        })}
      </div>
    </div>
  );

  // 位置由顶栏全局面包屑指示；这里关闭 PageContainer 默认左上面包屑
  const headerCfg = {
    title: (
      <Space size={8} align="baseline">
        <span>{spec}</span>
        {/* add-fast-track-mode（task 7.2）：执行模式标记——fast-track 单 run 全包，
            其余（含存量无 mode 字段的 spec）统一展示「完整模式」，可辨识两条路径 */}
        <Tag color={detail?.mode === 'fast-track' ? 'cyan' : 'default'} style={{ marginInlineEnd: 0 }}>
          {detail?.mode === 'fast-track' ? '快速模式' : '完整模式'}
        </Tag>
        {detail?.status && (
          <Tag color={statusInfo.tone === 'good' ? 'success' : statusInfo.tone === 'critical' ? 'error' : 'processing'}>
            {statusInfo.label}
          </Tag>
        )}
        {otherSpecs.length > 0 && (
          <Dropdown trigger={['click']} placement="bottomLeft" popupRender={renderSpecSwitch} open={switchOpen} onOpenChange={setSwitchOpen}>
            <Button
              type="text"
              size="small"
              icon={<DownOutlined />}
              title="切换 SPEC"
              aria-label="切换 SPEC"
              style={{ paddingInline: 4, minWidth: 24, minHeight: 24 }}
            />
          </Dropdown>
        )}
      </Space>
    ),
    onBack: () => history.push(`/projects/${name}`),
  };

  if (loading) {
    return (
      <PageContainer breadcrumbRender={false} header={headerCfg}>
        <div style={{ textAlign: 'center', padding: '50px 0' }}>
          <Spin size="large" />
        </div>
      </PageContainer>
    );
  }

  if (error) {
    return (
      <PageContainer breadcrumbRender={false} header={headerCfg}>
        <Alert type="error" showIcon message="加载失败" description={error} />
      </PageContainer>
    );
  }

  // 格式化 token 数量
  const fmtMillions = (tokens: number) => {
    const m = (tokens || 0) / 1e6;
    return m >= 1000 ? (m / 1000).toFixed(2) + 'G' : m.toFixed(1) + 'M';
  };

  // 输入 Token 展示：有缓存命中分项（cache_read_input_tokens 非 null）时附加括号，
  // 命中率 = 缓存命中 / 输入 Token（输入已含缓存写入+命中，口径与 STATE 累计一致）；
  // 分项为 null（历史 spec 未记录）时不显示括号，避免伪 0%
  const fmtInputTokens = (usage: NonNullable<SpecDetail['token_usage']>) => {
    const base = fmtMillions(usage.tokens_in);
    const cacheRead = usage.cache_read_input_tokens;
    if (cacheRead == null || !usage.tokens_in) return base;
    const pct = ((cacheRead / usage.tokens_in) * 100).toFixed(1);
    return `${base}（缓存命中 ${fmtMillions(cacheRead)}，命中率 ${pct}%）`;
  };

  // 告警标记人工已处理（同 overview 横幅）；成功后刷新本 SPEC 告警
  const handleMarkAlertHandled = async (a: AlertItem) => {
    try {
      await markAlertHandled(a.project, a.id);
      message.success('已标记处理');
    } catch (err) {
      message.error(`标记失败：${err instanceof Error ? err.message : String(err)}`);
    }
    loadSpecAlerts();
  };

  // 清除 spec 信息（同列表页清除 error）；成功后重拉详情使信息条消失
  const handleClearInfo = async () => {
    try {
      await clearSpecError(name, spec);
      message.success('已清除');
      setDetail(await getSpecDetail(name, spec));
    } catch (err) {
      message.error(`清除失败：${err instanceof Error ? err.message : String(err)}`);
    }
  };

  const openDocModal = (doc: DocType) => {
    setDocInitial(doc);
    setDocModalOpen(true);
  };

  // 计算任务进度
  const taskGroups = detail?.tasks || [];
  const allTasks = taskGroups.flatMap((g) => g.tasks || []);
  const completedTasks = allTasks.filter((t) => t.done).length;
  const totalTasks = allTasks.length;

  // 格式化时长
  const fmtDuration = (seconds: number) => {
    if (seconds == null || Number.isNaN(seconds)) return '';
    let s = Math.max(0, Math.round(seconds));
    if (s < 60) return `${s}秒`;
    const m = Math.floor(s / 60);
    s %= 60;
    if (m < 60) return s ? `${m}分${s}秒` : `${m}分`;
    return `${Math.floor(m / 60)}时${m % 60}分${s ? `${s}秒` : ''}`;
  };

  // 渲染时间轴内容 — 复用运维记录页的时间轴控件（Timeline + 盒式卡片子项：头部时间+标签行，正文着色边框）
  const renderTimeline = () => {
    const timeline = detail?.timeline || [];
    if (!timeline.length) {
      return <Empty description="暂无运行时间轴" />;
    }

    const cardBox = (urgent: boolean): React.CSSProperties => ({
      padding: isMobile ? 8 : 12,
      borderRadius: 8,
      border: urgent ? '1px solid #ff4d4f' : '1px solid #f0f0f0',
      background: urgent ? '#fff2f0' : '#fafafa',
    });
    const headRow: React.CSSProperties = {
      display: 'flex',
      alignItems: 'center',
      gap: 8,
      marginBottom: 8,
      flexWrap: 'wrap',
    };
    const fmtTime = (v: string) => {
      const d = dayjs(v);
      return d.isValid() ? d.format('YYYY-MM-DD HH:mm:ss') : v;
    };

    return (
      <Timeline
        items={timeline.map((item) => {
          if (item.kind === 'state') {
            // 状态节点：头部保留「状态转移」标签，from → to 中文标签（同 SPEC 列表 statusMeta）换行显示在内容区
            const isRollback = !!item.reason;
            const fromLabel = item.from ? statusMeta(item.from).label : '?';
            const toLabel = item.to ? statusMeta(item.to).label : '?';
            return {
              color: isRollback ? '#ec835a' : 'gray',
              children: (
                <div style={cardBox(false)}>
                  <div style={headRow}>
                    <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                      {fmtTime(item.time)}
                    </Typography.Text>
                    <Tag>状态转移</Tag>
                    {isRollback && <Tag color="orange">↩ 状态回退</Tag>}
                  </div>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
                    <OutlinedTag tone={statusMeta(item.from || '').tone}>{fromLabel}</OutlinedTag>
                    <Typography.Text type="secondary">→</Typography.Text>
                    <OutlinedTag tone={statusMeta(item.to || '').tone}>{toLabel}</OutlinedTag>
                  </div>
                  {isRollback && (
                    <div style={{ whiteSpace: 'pre-wrap' }}>
                      <ReasonText reason={item.reason || '状态回退'} onOpenReport={() => openDocModal('verification')} />
                    </div>
                  )}
                </div>
              ),
            };
          }

          // 运行节点
          const st = item.status || '';
          const isErr = st === 'error';
          const isRunning = st === 'running' || st === 'empty';
          const dotColor = isErr ? 'red' : isRunning ? 'blue' : 'green';
          const dur = item.duration_seconds != null ? fmtDuration(item.duration_seconds) : '';
          const isFix = item.spec && String(item.spec).startsWith('fix-');

          return {
            color: dotColor,
            children: (
              <div style={cardBox(isErr)}>
                <div style={headRow}>
                  <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                    {fmtTime(item.time)}
                  </Typography.Text>
                  <Typography.Text>{agentLabel(item)}</Typography.Text>
                  {item.llm && <Tag color="blue" style={{ marginInlineEnd: 0 }}>{item.llm}</Tag>}
                  <Tag color={isErr ? 'red' : isRunning ? 'blue' : 'green'} style={{ marginInlineEnd: 0 }}>
                    {st || '未知状态'}
                  </Tag>
                  {isFix && <Tag color="orange">🔧 {item.spec}</Tag>}
                  {dur && (
                    <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                      耗时 {dur}
                    </Typography.Text>
                  )}
                </div>
                {/* ClaudeCode 最后一条总结（result 字段，markdown）：不展开运行记录即可掌握结论 */}
                {item.summary && (
                  <div
                    style={{
                      marginBottom: 8,
                      padding: '8px 12px',
                      border: '1px solid #f0f0f0',
                      borderRadius: 8,
                      background: '#fff',
                      fontSize: 13,
                    }}
                  >
                    <Markdown remarkPlugins={[remarkGfm]} components={markdownComponents}>
                      {item.summary}
                    </Markdown>
                  </div>
                )}
                {item.run_id && (
                  <Collapse
                    ghost
                    size="small"
                    items={[
                      {
                        key: 'run-stream',
                        label: (
                          <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}>
                            查看运行记录
                            <Button
                              type="text"
                              size="small"
                              title="最大化查看"
                              icon={<FullscreenOutlined />}
                              onClick={(e) => {
                                e.stopPropagation();
                                setRecordRunId(item.run_id!);
                              }}
                            />
                          </span>
                        ),
                        // ClaudeOutputPane 依赖父容器高度约束，这里限高滚动避免时间轴被长运行拉穿
                        children: (
                          <div style={{ maxHeight: 480, overflow: 'auto', border: '1px solid #f0f0f0', borderRadius: 8, padding: isMobile ? 4 : 8, background: '#fafafa' }}>
                            <ClaudeOutputPane runId={item.run_id!} project={name} />
                          </div>
                        ),
                      },
                    ]}
                  />
                )}
              </div>
            ),
          };
        })}
      />
    );
  };

  // 页签配置
  const tabItems = [
    {
      key: 'timeline',
      label: '运行时间轴',
      children: (
        <div style={{ padding: '20px 0' }} className="spec-detail-timeline">
          {renderTimeline()}
        </div>
      ),
    },
    {
      key: 'scenarios',
      label: (
        <span>
          场景结果
          <Badge count={detail?.scenarios?.length ?? 0} style={{ marginLeft: 4, marginTop: -5 }} />
        </span>
      ),
      children: (
        <div style={{ padding: '20px 0' }}>
          {detail?.scenarios?.length ? (
            <div>
              {/* 状态过滤条（点击筛选，再点取消；计数取自场景数组本身） */}
              <div style={{ marginBottom: 16 }}>
                <Space size={8} wrap>
                  {(
                    [
                      { key: 'pass', label: '通过', color: 'success' },
                      { key: 'warning', label: '警告', color: 'warning' },
                      { key: 'fail', label: '失败', color: 'error' },
                      { key: 'error', label: '错误', color: 'error' },
                    ] as const
                  ).map((c) => {
                    const active = scenarioFilter === c.key;
                    return (
                      <Tag
                        key={c.key}
                        color={active ? c.color : 'default'}
                        style={{ cursor: 'pointer' }}
                        onClick={() => setScenarioFilter(active ? '' : c.key)}
                      >
                        {c.label} {detail.scenarios.filter((s) => s.status === c.key).length}
                      </Tag>
                    );
                  })}
                </Space>
              </div>

              {/* 场景卡片列表（v1 scenarioCard 同款：状态 + 场景 ID + 描述 + 失败步骤/断言明细） */}
              {(scenarioFilter
                ? detail.scenarios.filter((s) => s.status === scenarioFilter)
                : detail.scenarios
              ).map((scenario, idx) => {
                const failedSteps = (scenario.step_results || []).filter((s) => !s.success);
                const assertions = scenario.assertion_results || [];
                return (
                  <Card
                    key={idx}
                    size="small"
                    style={{ marginBottom: 12 }}
                    title={
                      <Space size={8}>
                        <Tag
                          color={
                            scenario.status === 'pass'
                              ? 'success'
                              : scenario.status === 'warning'
                                ? 'warning'
                                : 'error'
                          }
                        >
                          {scenario.status === 'pass'
                            ? '✅ 通过'
                            : scenario.status === 'warning'
                              ? '⚠️ 警告'
                              : scenario.status === 'fail'
                                ? '✗ 失败'
                                : '✗ 错误'}
                        </Tag>
                        <Typography.Text strong>{scenario.scenario_id}</Typography.Text>
                      </Space>
                    }
                  >
                    {/* 场景内容放正文，14px */}
                    {scenario.description && (
                      <Typography.Text style={{ fontSize: 14, display: 'block', marginBottom: 8 }}>
                        {scenario.description}
                      </Typography.Text>
                    )}

                    {/* 失败步骤明细（仅未成功步骤，v1 同款） */}
                    {failedSteps.length > 0 && (
                      <div style={{ marginBottom: assertions.length ? 8 : 0 }}>
                        <Typography.Text style={{ display: 'block', marginBottom: 4 }}>
                          失败步骤:
                        </Typography.Text>
                        {failedSteps.map((step, sIdx) => (
                          <div
                            key={sIdx}
                            style={{
                              padding: '4px 8px',
                              marginBottom: 4,
                              background: '#fff2f0',
                              border: '1px solid #ffccc7',
                              borderRadius: 4,
                            }}
                          >
                            <Typography.Text type="danger">
                              ✗ {step.action || '?'} {step.description || ''} {step.error || step.detail || ''}
                            </Typography.Text>
                          </div>
                        ))}
                      </div>
                    )}

                    {/* 断言明细（失败标红，v1 同款） */}
                    {assertions.length > 0 && (
                      <div>
                        <Typography.Text style={{ display: 'block', marginBottom: 4 }}>
                          断言:
                        </Typography.Text>
                        {assertions.map((a, aIdx) => {
                          const ok = a.pass !== false;
                          return (
                            <div
                              key={aIdx}
                              style={{
                                padding: '4px 8px',
                                marginBottom: 4,
                                background: ok ? '#f6ffed' : '#fff2f0',
                                border: `1px solid ${ok ? '#b7eb8f' : '#ffccc7'}`,
                                borderRadius: 4,
                              }}
                            >
                              <Typography.Text type={ok ? undefined : 'danger'}>
                                {ok ? '✓' : '✗'}{' '}
                                <Tooltip title={`断言类型: ${a.type || '?'}`}>
                                  {assertionLabel(a.type)}
                                </Tooltip>
                                : {assertionDetail(a)}{' '}
                                {ok ? '' : `— ${a.message || a.detail || a.error || ''}`}
                              </Typography.Text>
                            </div>
                          );
                        })}
                      </div>
                    )}
                  </Card>
                );
              })}
            </div>
          ) : detail?.report?.error ? (
            <Empty description="report.json 损坏或不可读" />
          ) : (
            <Empty description="暂无场景结果" />
          )}
        </div>
      ),
    },
    {
      key: 'bugs',
      label: (
        <span>
          Bug 列表
          <Badge count={detail?.bugs?.length ?? 0} style={{ marginLeft: 4, marginTop: -5 }} />
        </span>
      ),
      children: (
        <div style={{ padding: '20px 0' }}>
          {detail?.bugs && detail.bugs.length > 0 ? (
            <div>
              {detail.bugs.map((bug, idx) => (
                <Card
                  key={idx}
                  size="small"
                  style={{ marginBottom: 12 }}
                  title={
                    <Space size={8}>
                      <Tag
                        color={
                          bug.severity === 'critical'
                            ? 'error'
                            : bug.severity === 'major'
                              ? 'orange'
                              : bug.severity === 'minor'
                                ? 'default'
                                : 'blue'
                        }
                      >
                        {bug.severity || 'major'}
                      </Tag>
                      <Typography.Text type="secondary">{bug.source || 'report'}</Typography.Text>
                    </Space>
                  }
                >
                  <Typography.Paragraph style={{ marginBottom: 8 }}>
                    {bug.description}
                  </Typography.Paragraph>

                  {/* 关联场景 */}
                  {bug.scenario && (
                    <div style={{ marginBottom: 8 }}>
                      <Typography.Text type="secondary">关联场景: </Typography.Text>
                      <Typography.Text>{bug.scenario}</Typography.Text>
                    </div>
                  )}

                  {/* 断言类型 */}
                  {bug.assertion && (
                    <div style={{ marginBottom: 8 }}>
                      <Typography.Text type="secondary">断言类型: </Typography.Text>
                      <Tooltip title={assertionLabel(bug.assertion) !== bug.assertion ? bug.assertion : ''}>
                        <Typography.Text>{assertionLabel(bug.assertion)}</Typography.Text>
                      </Tooltip>
                    </div>
                  )}

                  {/* 证据 */}
                  {bug.evidence && (
                    <div
                      style={{
                        padding: '8px 12px',
                        marginBottom: 8,
                        background: '#f5f5f5',
                        borderRadius: 4,
                        fontFamily: 'monospace',
                        fontSize: 13,
                      }}
                    >
                      <Typography.Text>{bug.evidence}</Typography.Text>
                    </div>
                  )}

                  {/* 截图缩略图 */}
                  {bug.screenshots && bug.screenshots.length > 0 && (
                    <div style={{ marginTop: 8, display: 'flex', flexWrap: 'wrap', gap: 8 }}>
                      {bug.screenshots.map((file, sIdx) => (
                        <Image
                          key={sIdx}
                          src={`/screenshots/${encodeURIComponent(name)}/${encodeURIComponent(spec)}/${encodeURIComponent(file)}`}
                          alt={`Bug ${idx + 1} 截图 ${sIdx + 1}`}
                          width={150}
                          height={100}
                          style={{
                            objectFit: 'cover',
                            border: '1px solid #d9d9d9',
                            borderRadius: 4,
                          }}
                          preview={{ mask: '点击预览' }}
                        />
                      ))}
                    </div>
                  )}
                </Card>
              ))}
            </div>
          ) : (
            <Empty description="暂无 Bug" />
          )}
        </div>
      ),
    },
    {
      key: 'screenshots',
      label: (
        <span>
          失败截图
          <Badge count={detail?.screenshots?.length ?? 0} style={{ marginLeft: 4, marginTop: -5 }} />
        </span>
      ),
      children: (
        <div style={{ padding: '20px 0' }}>
          {detail?.screenshots && detail.screenshots.length > 0 ? (
            <div>
              <div style={{ marginBottom: 12 }}>
                <Typography.Text type="secondary">
                  共 {detail.screenshots.length} 张截图（点击放大）
                </Typography.Text>
              </div>
              <Image.PreviewGroup
                items={detail.screenshots.map((s) => ({
                  src: `/screenshots/${encodeURIComponent(name)}/${encodeURIComponent(spec)}/${encodeURIComponent(s.file)}`,
                  alt: s.file,
                }))}
              >
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
                  {detail.screenshots.map((s, idx) => (
                    <Image
                      key={idx}
                      src={`/screenshots/${encodeURIComponent(name)}/${encodeURIComponent(spec)}/${encodeURIComponent(s.file)}`}
                      alt={s.file}
                      width={150}
                      height={100}
                      style={{
                        objectFit: 'cover',
                        border: '1px solid #d9d9d9',
                        borderRadius: 4,
                        cursor: 'pointer',
                      }}
                      preview={{
                        mask: '点击预览',
                      }}
                    />
                  ))}
                </div>
              </Image.PreviewGroup>
            </div>
          ) : (
            <Empty description="暂无失败截图" />
          )}
        </div>
      ),
    },
  ];

  return (
    <PageContainer breadcrumbRender={false} header={headerCfg}>
      {/* 项目信息（置顶）：基础元信息 + 累计 Token 消耗（只展示输入/输出，成本不回传不准不算） */}
      <Card
        title={
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <span>项目信息</span>
            <Typography.Link onClick={() => openDocModal('proposal')}>文档</Typography.Link>
          </div>
        }
        size="small"
        style={{ marginBottom: 16 }}
      >
        <Descriptions column={{ xs: 1, sm: 2, md: 3 }} size="small">
          <Descriptions.Item label="优先级">
            <span>P{detail?.priority ?? '?'}</span>
          </Descriptions.Item>
          <Descriptions.Item label="创建时间">
            {detail?.created ? dayjs(detail.created).format('YYYY-MM-DD HH:mm:ss') : '—'}
          </Descriptions.Item>
          <Descriptions.Item label="更新时间">
            {detail?.updated ? dayjs(detail.updated).format('YYYY-MM-DD HH:mm:ss') : '—'}
          </Descriptions.Item>
          <Descriptions.Item label="依赖">
            {detail?.depends_on || '—'}
          </Descriptions.Item>
          <Descriptions.Item label="输入 Token">
            {detail?.token_usage ? fmtInputTokens(detail.token_usage) : '—'}
          </Descriptions.Item>
          <Descriptions.Item label="输出 Token">
            {detail?.token_usage ? fmtMillions(detail.token_usage.tokens_out) : '—'}
          </Descriptions.Item>
        </Descriptions>
      </Card>

      {/* 告警与信息：仅在有内容时展示（spec.error 语义是需知会的信息而非错误，按 info 样式渲染）。
          标题统一 14px、图标固定 16px（覆盖 antd 带 description 时 16px 标题/24px 图标的默认样式）；
          告警内容默认折叠，右侧箭头展开；操作统一为右侧 X 清除链接 */}
      {(detail?.error || specAlerts.length > 0) && (
        <div style={{ marginBottom: 16, display: 'flex', flexDirection: 'column', gap: 8 }}>
          {specAlerts.map((a) => {
            const hasContent = !!(a.recommended_action || a.evidence);
            const expanded = expandedAlerts.has(a.id);
            return (
              <Alert
                key={a.id}
                className="spec-detail-alert"
                type={a.severity === 'critical' ? 'error' : 'warning'}
                showIcon
                icon={<ExclamationCircleFilled style={{ fontSize: 16 }} />}
                /* padding 钉在收缩态基准值上：展开/收起外边距恒定，箭头与叉号不移位 */
                style={{ padding: '8px 12px' }}
                message={
                  <Space size={6} wrap>
                    <span style={{ fontSize: 14 }}>告警：{a.description || a.action_taken || '人工升级告警'}</span>
                    <Tag color={SEV_COLOR[a.severity || ''] || 'default'} style={{ marginInlineEnd: 0 }}>
                      {SEV_LABEL[a.severity || ''] || a.severity || '未知'}
                    </Tag>
                  </Space>
                }
                description={
                  hasContent ? (
                    /* description 常驻（折叠时仅 display:none）：Alert 始终保持 with-description
                       变体，展开/收起不再触发布局切换导致箭头与叉号移位 */
                    <div style={expanded ? { fontSize: 12, whiteSpace: 'pre-wrap', marginTop: 8 } : { display: 'none' }}>
                      {a.recommended_action && (
                        <div>
                          <Typography.Text type="secondary">建议：{a.recommended_action}</Typography.Text>
                        </div>
                      )}
                      {a.evidence && (
                        <div>
                          <Typography.Text type="secondary">证据：{a.evidence}</Typography.Text>
                        </div>
                      )}
                    </div>
                  ) : undefined
                }
                action={
                  <Space size={12}>
                    {hasContent && (
                      <a onClick={() => toggleAlert(a.id)} title={expanded ? '收起' : '展开'}>
                        <DownOutlined rotate={expanded ? 180 : 0} />
                      </a>
                    )}
                    <Typography.Link onClick={() => void handleMarkAlertHandled(a)} title="清除">
                      <CloseOutlined />
                    </Typography.Link>
                  </Space>
                }
              />
            );
          })}
          {detail?.error && (
            <Alert
              type="info"
              showIcon
              icon={<InfoCircleFilled style={{ fontSize: 16 }} />}
              message={<span style={{ fontSize: 14 }}>信息：{detail.error}</span>}
              action={
                <Typography.Link onClick={() => void handleClearInfo()} title="清除">
                  <CloseOutlined />
                </Typography.Link>
              }
            />
          )}
        </div>
      )}

      {/* 任务清单（overview 任务进度同款控件 + 分组勾选） */}
      <Card title="任务清单" size="small" style={{ marginBottom: 16 }}>
        {taskGroups.length > 0 ? (
          <>
            <ProgressBarTile done={completedTasks} total={totalTasks} />
            {/* run 层实时线索（fix-implementer-task-progress D3）：tasks.md 快照
                落后于 run 实际推进时叠加显示，不再静止 0/N */}
            {detail?.run_progress && detail.run_progress.done > completedTasks ? (
              <Typography.Text
                type="warning"
                data-testid="run-progress-hint"
                style={{ display: 'block', marginTop: 6, fontSize: 12 }}
              >
                run {detail.run_progress.done}/{detail.run_progress.total} 已汇报
              </Typography.Text>
            ) : null}
            {proposalWhy ? (
              <div
                style={{
                  fontSize: 13,
                  lineHeight: 1.65,
                  color: 'rgba(0, 0, 0, 0.65)',
                  marginBottom: 10,
                }}
              >
                <Markdown remarkPlugins={[remarkGfm]} components={markdownComponents}>
                  {proposalWhy}
                </Markdown>
              </div>
            ) : null}
            {taskGroups.map((group, idx) => (
              <div key={idx} style={{ marginBottom: idx === taskGroups.length - 1 ? 0 : 12 }}>
                <Typography.Text strong style={{ display: 'block', marginBottom: 10 }}>
                  {group.title} ({group.done}/{group.total})
                </Typography.Text>
                {group.tasks.map((task, taskIdx) => (
                  <div key={taskIdx} style={{ display: 'flex', alignItems: 'flex-start', marginBottom: 10 }}>
                    <Checkbox checked={task.done} disabled style={{ marginRight: 8 }} />
                    <Typography.Text
                      style={{
                        textDecoration: task.done ? 'line-through' : 'none',
                        color: task.done ? '#999' : 'inherit',
                      }}
                    >
                      <code style={{ marginRight: 6 }}>{task.id}</code>
                      {task.desc}
                    </Typography.Text>
                  </div>
                ))}
              </div>
            ))}
          </>
        ) : (
          <Typography.Text type="secondary">暂无任务清单</Typography.Text>
        )}
      </Card>

      {/* 验证进度（overview 任务进度同款控件 + 当前步骤） */}
      <Card title="验证进度" size="small" style={{ marginBottom: 16 }}>
        {detail?.verify_progress?.exists ? (
          <>
            {detail.verify_progress.error && (
              <Alert type="error" showIcon message="进度文件损坏" style={{ marginBottom: 8 }} />
            )}
            <ProgressBarTile done={detail.verify_progress.done} total={detail.verify_progress.total} />
            {detail.verify_progress.current && (
              <Typography.Text type="secondary">当前：{detail.verify_progress.current}</Typography.Text>
            )}
          </>
        ) : (
          <Typography.Text type="secondary">暂无验证进度</Typography.Text>
        )}
      </Card>

      {/* 验证结论 */}
      <Card title="验证结论" size="small" style={{ marginBottom: 16 }}>
        {detail?.verdict?.exists ? (
          <VerdictPanel verdict={detail.verdict} />
        ) : (
          <Typography.Text type="secondary">暂无验证结论</Typography.Text>
        )}
      </Card>

      {/* 页签区 */}
      <Card className="spec-detail-card">
        <Tabs items={tabItems} />
      </Card>

      {/* SPEC 文档弹窗（时间轴报告链接 → 验证报告；项目信息「文档」→ 需求背景） */}
      <SpecDocModal
        project={name}
        spec={spec}
        open={docModalOpen}
        onClose={() => setDocModalOpen(false)}
        initialDoc={docInitial}
      />

      {/* 运行记录最大化弹窗（时间轴「查看运行记录」旁全屏入口） */}
      <RunRecordModal runId={recordRunId} project={name} onClose={() => setRecordRunId(null)} />
    </PageContainer>
  );
}