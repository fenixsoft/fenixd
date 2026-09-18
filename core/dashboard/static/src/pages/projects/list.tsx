import { ClockCircleOutlined, MoreOutlined } from '@ant-design/icons';
import { PageContainer } from '@ant-design/pro-components';
import {
  Alert,
  App,
  Badge,
  Button,
  Card,
  DatePicker,
  Dropdown,
  Empty,
  Input,
  List,
  Modal,
  Popover,
  Progress,
  Radio,
  Select,
  Slider,
  Space,
  Spin,
  Table,
  Tabs,
  Tag,
  Tooltip,
  Typography,
} from 'antd';
import type { ColumnsType } from 'antd/es/table';
import type { MenuProps } from 'antd';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { Key } from 'react';
import { history, useParams } from '@umijs/max';
import { useIsMobile } from '@/hooks/useIsMobile';
import dayjs from 'dayjs';
import Markdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { markdownComponents } from './components/SpecDocModal';
import { getSpecDetail, getSpecs } from '@/services/dashboard';
import {
  clearSpecError,
  deleteSpec,
  reReviewSpec,
  setSpecPriority,
  setSpecStartAfter,
  statusMeta,
} from '@/services/dashboard';
import type { SpecDetail, SpecSummary } from '@/services/dashboard';
import { fetchProposalWhy } from '@/utils/proposalWhy';
import SpecDocModal from './components/SpecDocModal';
import AdminInvokeModal from './components/AdminInvokeModal';
import SpecStatusModal from './components/SpecStatusModal';
import SessionPanel from './components/SessionPanel';

const REFRESH_THROTTLE_MS = 500;
// dashboard-sse-refresh：增量 patch 去重窗口（同 spec 1s 内多事件只应用最新）
const PATCH_COALESCE_MS = 1000;
// 兜底心跳间隔（30s）：SSE 断线 / 事件丢帧时仍能校准
const HEARTBEAT_MS = 30000;
// 搜索/筛选输入防抖
const SEARCH_DEBOUNCE_MS = 300;
const TRACK_LIGHT = '#e6f4ff'; // antd blue-1，与 #1677ff 同 ramp
const TRACK_GREEN = 'rgb(225, 236, 215)'; // 淡绿底轨（用户指定色），verify 阶段空条可辨
// 未完成（非 done/pushed 终态）spec 行底色：浅蓝紫提示仍在进行中
const ROW_INCOMPLETE_BG = 'rgb(250, 250, 255)';

// 状态圆点配色（table-list 风格：色点 + 文字，不用标签）
const TONE_DOT: Record<string, string> = {
  muted: '#bfbfbf',
  info: '#1677ff',
  warning: '#faad14',
  critical: '#ff4d4f',
  good: '#52c41a',
  aqua: '#13c2c2',
};

function pct(done: number, total: number) {
  return total > 0 ? Math.round((done / total) * 100) : 0;
}

// add-task-progress-verify-phase：按阶段取排序/渲染用完成度——verify 阶段用
// 验证完成度，impl 阶段用任务完成度（「显示什么按什么排」）。
function phasePct(record: SpecSummary) {
  return record.progress_phase === 'verify'
    ? pct(record.verify_done, record.verify_total)
    : pct(record.task_done, record.task_total);
}

function fmtDuration(sec?: number | null) {
  if (sec == null || Number.isNaN(sec)) return '';
  let s = Math.max(0, Math.round(sec));
  if (s < 60) return `${s}秒`;
  const m = Math.floor(s / 60);
  s %= 60;
  if (m < 60) return s ? `${m}分${s}秒` : `${m}分`;
  return `${Math.floor(m / 60)}时${m % 60}分${s ? `${s}秒` : ''}`;
}

type TypeFilter = '' | 'active' | 'completed';

// ── 名称列 Why 悬浮提示（对齐 v1 why-hint：悬停 200ms 拉取 proposal 的 ## Why 段） ──
// 提取与缓存逻辑在 src/utils/proposalWhy.ts（任务详情页「任务背景描述」共用）

function SpecNameCell({ project, record }: { project: string; record: SpecSummary }) {
  const [open, setOpen] = useState(false);
  const [why, setWhy] = useState<string | null>(null);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const onEnter = () => {
    timerRef.current = setTimeout(() => {
      void fetchProposalWhy(project, record.name).then((text) => {
        if (text) {
          setWhy(text);
          setOpen(true);
        }
      });
    }, 200);
  };
  const onLeave = () => {
    if (timerRef.current) clearTimeout(timerRef.current);
    setOpen(false);
  };

  const handleClick = () => {
    history.push(`/projects/${project}/${record.name}`);
  };

  return (
    <Popover
      open={open && !!why}
      placement="topLeft"
      content={
        <div style={{ maxWidth: 420, fontSize: 13, lineHeight: 1.65 }}>
          <Markdown remarkPlugins={[remarkGfm]} components={markdownComponents}>{why}</Markdown>
        </div>
      }
    >
      <span
        onMouseEnter={onEnter}
        onMouseLeave={onLeave}
        onClick={handleClick}
        style={{ cursor: 'pointer', fontSize: 16, fontWeight: 600, color: '#1677ff' }}
      >
        {record.name}
      </span>
    </Popover>
  );
}

// ── 验证列悬浮提示（悬浮显示验证结论，形式同名称 Why 提示） ──

const verdictCache = new Map<string, Promise<SpecDetail['verdict'] | null>>();

function fetchVerdict(project: string, spec: string): Promise<SpecDetail['verdict'] | null> {
  const key = `${project}│${spec}`;
  const cached = verdictCache.get(key);
  if (cached) return cached;
  const p = getSpecDetail(project, spec)
    .then((d) => d.verdict ?? null)
    .catch(() => null);
  verdictCache.set(key, p);
  return p;
}

function VerifyCell({ project, record }: { project: string; record: SpecSummary }) {
  const [open, setOpen] = useState(false);
  const [verdict, setVerdict] = useState<SpecDetail['verdict'] | null>(null);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // fix-verify-progress-fasttrack：无任何验证数据（verify_total 为 0）时渲染纯文本
  // 占位符 —，避免「尚无验证数据」被误读为 0/0 计数；无结论可读，不包 Popover。
  if (!record.verify_total) {
    return <span style={{ fontSize: 13, color: 'rgba(0, 0, 0, 0.45)' }}>—</span>;
  }

  const onEnter = () => {
    timerRef.current = setTimeout(() => {
      void fetchVerdict(project, record.name).then((v) => {
        if (v && v.exists) {
          setVerdict(v);
          setOpen(true);
        }
      });
    }, 200);
  };
  const onLeave = () => {
    if (timerRef.current) clearTimeout(timerRef.current);
    setOpen(false);
  };

  const sum = verdict?.summary;
  return (
    <Popover
      open={open && !!verdict?.exists}
      placement="topLeft"
      content={
        <div style={{ maxWidth: 420, fontSize: 13, lineHeight: 1.65 }}>
          <div>
            <Typography.Text strong>验证结论：</Typography.Text>
            <Typography.Text strong>{verdict?.status}</Typography.Text>
          </div>
          {verdict?.status_detail ? (
            <div style={{ whiteSpace: 'pre-wrap' }}>{verdict.status_detail}</div>
          ) : null}
          {verdict?.conclusion ? (
            <Markdown remarkPlugins={[remarkGfm]} components={markdownComponents}>
              {verdict.conclusion}
            </Markdown>
          ) : null}
          {sum ? (
            <Typography.Text type="secondary">
              通过 {sum.passed ?? 0} · 失败 {sum.failed ?? 0} · 错误 {sum.errors ?? 0}
              {sum.product_bugs ? ` · 产品 bug ${sum.product_bugs}` : ''}
            </Typography.Text>
          ) : null}
        </div>
      }
    >
      <span
        onMouseEnter={onEnter}
        onMouseLeave={onLeave}
        style={{ cursor: 'pointer', fontSize: 13, fontWeight: 600, color: '#1677ff' }}
      >
        {record.verify_done}/{record.verify_total}
      </span>
    </Popover>
  );
}

// done/pushed 为终态不再调整优先级；其余状态优先级可点击，样式与验证列一致
const PRIORITY_TERMINAL = new Set(['done', 'pushed']);

// ── 定时拾取标记（add-spec-scheduling-controls D6） ──
// start_after 未到期的 spec 渲染「定时」Tag：目标时间本地渲染 + 分钟级倒计时。
// 倒计时在渲染时刻用 dayjs() 求值，随列表既有刷新节奏（30s 心跳 / SSE 增量 /
// visibilitychange）更新，不另起秒级定时器（design D6）。
function ScheduledPickupTag({ record }: { record: SpecSummary }) {
  const sa = record.start_after;
  if (!sa) return null;
  const target = dayjs(sa);
  if (!target.isValid()) return null;
  const diffMin = Math.round(target.diff(dayjs(), 'minute', true));
  if (diffMin < 0) return null; // 已到期：交调度器正常拾取，不再展示等待标记
  const targetLocal = target.format('MM-DD HH:mm');
  const tip = `定时拾取 · ${targetLocal}（本地）启动，约 ${diffMin} 分钟后被 daemon 拾取`;
  return (
    <Tooltip title={tip}>
      <Tag icon={<ClockCircleOutlined />} color="blue" style={{ marginInlineEnd: 0 }}>
        {diffMin <= 1 ? '即将调度' : `${diffMin}分后`}
      </Tag>
    </Tooltip>
  );
}

// add-spec-manual-activation D9：start_after == 'manual'（手工激活哨兵）的 spec
// 渲染橙色「待激活」Tag——永不到期、待人工激活。不加状态门槛（渲染只看字段，
// 避免 drafted 态漏标；若后续语义变化不误伤）。ScheduledPickupTag 对 'manual'
// 由 dayjs('manual') Invalid Date 自然返回 null，二者不冲突。
function ManualActivationTag({ record }: { record: SpecSummary }) {
  if (record.start_after !== 'manual') return null;
  return (
    <Tooltip title="已设为手工激活，需人工激活后才会被拾取">
      <Tag color="orange" style={{ marginInlineEnd: 0 }}>
        待激活
      </Tag>
    </Tooltip>
  );
}

// add-spec-manual-activation D9：ready 且有前置依赖的 spec 渲染「前置依赖」Tag
// （hover 展示依赖名列表）。判据依赖后端规范化：record.depends_on 经
// _normalize_depends_on 归一，无依赖为 null/undefined——MUST NOT 用裸真值判定
// （STATE.md 里 `depends_on: null` 解析回字面量字符串 "null"，227/244 条存量
// entry 为此形态，裸真值会全线误标）。仅 ready 展示（用户明确要求：ready 时才
// 提示「为什么就绪却不派发」）；其它状态的依赖信息属详情页职责。
function DependencyTag({ record }: { record: SpecSummary }) {
  if (record.status !== 'ready') return null;
  const deps = record.depends_on;
  if (!deps) return null;
  return (
    <Tooltip title={`前置依赖：${deps}`}>
      <Tag color="geekblue" style={{ marginInlineEnd: 0 }}>
        前置依赖
      </Tag>
    </Tooltip>
  );
}

// 状态列等待标记集：定时拾取 + 待激活 + 前置依赖（桌面与移动端共用）
function StatusWaitGroup({ record }: { record: SpecSummary }) {
  return (
    <>
      <ScheduledPickupTag record={record} />
      <ManualActivationTag record={record} />
      <DependencyTag record={record} />
    </>
  );
}

function PriorityCell({
  record,
  onEdit,
  muted,
}: {
  record: SpecSummary;
  onEdit: (record: SpecSummary) => void;
  // 移动端卡片场景：不可编辑时保持灰色 secondary 字体
  muted?: boolean;
}) {
  if (PRIORITY_TERMINAL.has(record.status || '')) {
    return muted ? (
      <Typography.Text type="secondary">P{record.priority ?? '?'}</Typography.Text>
    ) : (
      <span>P{record.priority ?? '?'}</span>
    );
  }
  return (
    <span
      onClick={() => onEdit(record)}
      style={{ cursor: 'pointer', fontSize: 13, fontWeight: 600, color: '#1677ff' }}
    >
      P{record.priority ?? '?'}
    </span>
  );
}

/**
 * fix-* 规格归并成树（对齐 v1）：fix-fix-a 的父是 fix-a（若存在），再是 a；
 * 无父 fix 归入顶层。
 */
function buildTree(specs: SpecSummary[]): SpecSummary[] {
  const byName = new Map(specs.map((s) => [s.name, s]));
  const childrenMap = new Map<string, string[]>();
  const roots: SpecSummary[] = [];
  specs.forEach((s) => {
    if (!s.name.startsWith('fix-')) {
      roots.push(s);
      return;
    }
    let candidate = s.name;
    let parent: string | null = null;
    while (candidate.startsWith('fix-')) {
      const up = candidate.slice(4);
      if (up === s.name) break;
      if (byName.has(up)) {
        parent = up;
        break;
      }
      candidate = up;
    }
    if (parent == null) {
      roots.push(s);
    } else {
      const arr = childrenMap.get(parent) || [];
      arr.push(s.name);
      childrenMap.set(parent, arr);
    }
  });
  type Node = SpecSummary & { children?: Node[] };
  const attach = (s: SpecSummary): Node => {
    const kids = childrenMap.get(s.name);
    return kids ? { ...s, children: kids.map((n) => attach(byName.get(n)!)) } : { ...s };
  };
  return roots.map(attach);
}

interface SpecCardListProps {
  data: SpecSummary[];
  project: string;
  loading: boolean;
  onDocView: (spec: string) => void;
  onMenu: (record: SpecSummary, key: string) => void;
  menuItems: (record: SpecSummary) => MenuProps['items'];
  onClearError: (record: SpecSummary) => void;
}

// 移动端（<768px）卡片形态：字段与桌面表格列一一对应，扁平化树并按层级缩进。
// 仅在 md 断点以下渲染，桌面 Table 分支不受影响。
function SpecCardList({ data, project, loading, onDocView, onMenu, menuItems, onClearError }: SpecCardListProps) {
  type FlatNode = { record: SpecSummary; level: number };
  const flat = useMemo<FlatNode[]>(() => {
    const out: FlatNode[] = [];
    const walk = (nodes: SpecSummary[], level: number) => {
      nodes.forEach((n) => {
        out.push({ record: n, level });
        if (n.children) walk(n.children, level + 1);
      });
    };
    walk(data, 0);
    return out;
  }, [data]);

  return (
    <List
      loading={loading}
      dataSource={flat}
      pagination={{ pageSize: 20, showTotal: (t) => `共 ${t} 条` }}
      renderItem={({ record, level }) => {
        const m = statusMeta(record.status || '');
        const created = record.created ? dayjs(record.created) : null;
        const progress = pct(record.task_done, record.task_total);
        return (
          <List.Item style={{ paddingLeft: level > 0 ? 16 * level : undefined }}>
            <div style={{ width: '100%', minWidth: 0 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
                <Badge color={TONE_DOT[m.tone]} text={m.label} />
                <StatusWaitGroup record={record} />
                <div style={{ flex: 1, minWidth: 0 }}>
                  <SpecNameCell project={project} record={record} />
                </div>
                <Dropdown
                  menu={{ items: menuItems(record), onClick: ({ key }) => onMenu(record, key) }}
                  placement="bottomRight"
                  trigger={['click']}
                >
                  <Button type="link" size="small" icon={<MoreOutlined />} className="touch-expand">更多</Button>
                </Dropdown>
              </div>
              <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap', marginTop: 4, fontSize: 12 }}>
                <PriorityCell record={record} onEdit={(r) => onMenu(r, 'priority')} muted />
                <Typography.Text type="secondary">
                  {created && created.isValid() ? created.format('YYYY-MM-DD HH:mm') : '—'}
                </Typography.Text>
                <Typography.Text type="secondary">耗时 {fmtDuration(record.total_duration)}</Typography.Text>
              </div>
              <div style={{ marginTop: 8 }}>
                <Progress
                  percent={progress}
                  size="small"
                  showInfo={false}
                  strokeColor="#1677ff"
                  trailColor={TRACK_LIGHT}
                />
                <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12, lineHeight: '18px' }}>
                  <Typography.Text type="secondary">
                    {record.task_done}/{record.task_total}
                  </Typography.Text>
                  <Typography.Text type="secondary">{progress >= 100 ? '已完成' : `${progress}%`}</Typography.Text>
                </div>
              </div>
              <div style={{ marginTop: 8 }}>
                {record.verify_error ? (
                  <Tooltip title={record.verify_error}>
                    <Typography.Text type="danger">⚠ 验证异常</Typography.Text>
                  </Tooltip>
                ) : (
                  <VerifyCell project={project} record={record} />
                )}
              </div>
              {record.error ? (
                <div style={{ display: 'flex', alignItems: 'flex-start', gap: 8, marginTop: 8 }}>
                  <Tag color="orange" style={{ marginInlineEnd: 0 }}>信息</Tag>
                  <Typography.Text style={{ flex: 1, minWidth: 0 }}>{record.error}</Typography.Text>
                  <Button size="small" onClick={() => onClearError(record)}>清除</Button>
                </div>
              ) : null}
            </div>
          </List.Item>
        );
      }}
    />
  );
}

export default function SpecListPage() {
  const { name = '' } = useParams<{ name: string }>();
  const isMobile = useIsMobile();
  const { message } = App.useApp();
  // dashboard-sse-refresh D3：本地 spec 摘要表（Map<spec_name, summary>），
  // 首屏 /api/specs 全量建立，此后 SSE 增量事件 patch 单行（含新增/删除）。
  const [specMap, setSpecMap] = useState<Record<string, SpecSummary>>({});
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);
  const [q, setQ] = useState('');
  // 搜索/筛选输入防抖 ≥300ms（3.4），本地表过滤；本地空才回退后端
  const [debouncedQ, setDebouncedQ] = useState('');
  const [statusList, setStatusList] = useState<string[]>([]);
  const [type, setType] = useState<TypeFilter>('');
  // add-spec-archive：归档状态过滤（false=未归档默认，true=已归档）
  const [archivedOnly, setArchivedOnly] = useState(false);
  const lastRefreshRef = useRef(0);

  // 增量 patch 队列：同 spec 1s 内多事件只应用最新（3.1 去重合并）。
  const pendingPatchesRef = useRef<Record<string, SpecSummary | null>>({});
  const patchTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const specMapRef = useRef(specMap);
  specMapRef.current = specMap;

  // 文档弹窗（对齐 v1 docmodal：背景/设计/任务清单 三页签）
  const [docView, setDocView] = useState<string | null>(null);

  // 调整优先级弹窗
  const [priorityEdit, setPriorityEdit] = useState<{ spec: string; value: number } | null>(null);

  // 呼叫 Admin 介入弹窗
  const [adminInvoke, setAdminInvoke] = useState<{ spec: string } | null>(null);

  // add-spec-scheduling-controls：设置拾取时间弹窗（非终态 spec）
  const [startAfterEdit, setStartAfterEdit] = useState<{ spec: string } | null>(null);
  const [saDate, setSaDate] = useState<dayjs.Dayjs | null>(null);
  // add-spec-status-modal-budget：修改状态弹窗（归档/冻结/晋升/预算 四区块收敛入口）
  const [statusModal, setStatusModal] = useState<{ spec: string } | null>(null);

  // add-project-detail-tabs D1：项目页分面选中态（开发/质量/会话），
  // 仅存组件内存、不持久化到 URL——刷新回默认「开发」
  const [activeTab, setActiveTab] = useState<'dev' | 'quality' | 'session'>('dev');

  const load = useCallback(async () => {
    if (!name) return;
    try {
      const d = await getSpecs(name);
      if (d.error) {
        setError(d.error);
      } else {
        const next: Record<string, SpecSummary> = {};
        for (const s of d.specs || []) next[s.name] = s;
        setSpecMap(next);
        setError('');
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, [name]);

  // 刷新挂起的增量 patch（1s 去重窗口到期后统一应用）
  const flushPatches = useCallback(() => {
    patchTimerRef.current = null;
    const patches = pendingPatchesRef.current;
    pendingPatchesRef.current = {};
    setSpecMap((prev) => {
      const next = { ...prev };
      let changed = false;
      for (const [spec, summary] of Object.entries(patches)) {
        if (summary === null) {
          // 删除标记：summary:null → 从本地表移除该行
          if (spec in next) {
            delete next[spec];
            changed = true;
          }
        } else if (next[spec] !== summary) {
          next[spec] = summary;
          changed = true;
        }
      }
      return changed ? next : prev;
    });
  }, []);

  // 入队一条增量 patch；同 spec 在 1s 窗口内只保留最新值
  const enqueuePatch = useCallback((spec: string, summary: SpecSummary | null) => {
    pendingPatchesRef.current[spec] = summary;
    if (patchTimerRef.current == null) {
      patchTimerRef.current = setTimeout(flushPatches, PATCH_COALESCE_MS);
    }
  }, [flushPatches]);

  // SSE 增量驱动：state 事件入 patch 队列；run_meta/refresh 仅做节流兜底重拉
  useEffect(() => {
    void load();
    const es = new EventSource('/api/stream');
    es.onmessage = (ev: MessageEvent) => {
      let msg: {
        type?: string;
        project?: string;
        specs?: Array<{ spec?: string; summary?: SpecSummary | null }>;
      } = {};
      try {
        msg = JSON.parse(ev.data);
      } catch {
        return;
      }
      if (msg.type === 'state' && (!msg.project || msg.project === name)) {
        // 增量形态：specs 为 [{spec, summary|null}]，逐条入 patch 队列
        const items = msg.specs || [];
        for (const item of items) {
          if (item && typeof item.spec === 'string') {
            enqueuePatch(item.spec, item.summary ?? null);
          }
        }
        return;
      }
      if (msg.type === 'run_meta') {
        // run_meta（低频：仅状态转换）不携带摘要增量，节流兜底重拉校准
        // （实时任务进度/耗时字段随之刷新；refresh 为 watcher 2s 心跳，不触发
        // 全量重拉——降为 30s 兜底心跳，见下）。
        const now = Date.now();
        if (now - lastRefreshRef.current < REFRESH_THROTTLE_MS) return;
        lastRefreshRef.current = now;
        void load();
      }
    };
    return () => {
      es.close();
      if (patchTimerRef.current) clearTimeout(patchTimerRef.current);
    };
  }, [load, name, enqueuePatch]);

  // 30s 兜底心跳 + visibilitychange 立即校准（3.3）：SSE 断线 / 丢帧时列表仍刷新
  useEffect(() => {
    const hb = setInterval(() => void load(), HEARTBEAT_MS);
    const onVisible = () => {
      if (document.visibilityState === 'visible') void load();
    };
    document.addEventListener('visibilitychange', onVisible);
    return () => {
      clearInterval(hb);
      document.removeEventListener('visibilitychange', onVisible);
    };
  }, [load]);

  // 搜索/筛选输入防抖：≥300ms 后在本地表内过滤；本地表为空时才回退后端请求
  useEffect(() => {
    const t = setTimeout(() => {
      setDebouncedQ(q);
      // 本地表空（首屏未载入/失败）→ 回退请求 /api/specs
      if (q.trim() && Object.keys(specMapRef.current).length === 0) {
        void load();
      }
    }, SEARCH_DEBOUNCE_MS);
    return () => clearTimeout(t);
  }, [q, load]);

  const filtered = useMemo(() => {
    const kw = debouncedQ.trim().toLowerCase();
    // 本地表渲染：与 /api/specs 全量口径一致按 created 倒序（新增 spec 插序）
    return Object.values(specMap)
      .filter((s) => {
        if (kw && !s.name.toLowerCase().includes(kw)) return false;
        if (statusList.length && !statusList.includes(s.status || '')) return false;
        // 进度过滤：口径与行高亮一致，PRIORITY_TERMINAL（done/pushed）为已完成，其余为进行中
        if (type === 'active' && PRIORITY_TERMINAL.has(s.status || '')) return false;
        if (type === 'completed' && !PRIORITY_TERMINAL.has(s.status || '')) return false;
        // add-spec-archive：默认展示未归档（archivedOnly=false），切换后仅展示已归档
        if (!!s.archived !== archivedOnly) return false;
        return true;
      })
      .sort((a, b) => (b.created || '').localeCompare(a.created || ''));
  }, [specMap, debouncedQ, statusList, type, archivedOnly]);

  const tree = useMemo(() => buildTree(filtered), [filtered]);

  // 受控展开：数据到达时默认全部展开（树形子级 + error 信息行可见），用户可手动收起
  const [expandedKeys, setExpandedKeys] = useState<readonly Key[]>([]);
  useEffect(() => {
    setExpandedKeys(tree.map((r) => r.name));
  }, [tree]);

  const handleClearError = async (record: SpecSummary) => {
    try {
      await clearSpecError(name, record.name);
      void load();
    } catch (err) {
      console.error(err);
    }
  };

  const handleDeleteSpec = (record: SpecSummary) => {
    Modal.confirm({
      title: '删除 SPEC',
      content: (
        <div style={{ whiteSpace: 'pre-wrap' }}>
          {`确认删除 SPEC「${record.name}」？\n\n`}
          软删除：STATE.md 移除该条目，spec/changes/{record.name}/ 目录移入 archive 归档。
          {'\n'}归档路径：spec/archive/{record.name}-&lt;时间戳&gt;/
        </div>
      ),
      okText: '删除',
      okButtonProps: { danger: true },
      cancelText: '取消',
      onOk: async () => {
        await deleteSpec(name, record.name);
        void load();
      },
    });
  };

  const handleReReview = (record: SpecSummary) => {
    // add-spec-review-gate D8：重新评审入口——仅 error 前缀 spec-review-* 的
    // blocked SPEC 显示本入口；后端仍会复核开放条件（非 blocked/冻结/前缀不
    // 符任一拒绝），失败时展示后端返回的拒绝原因。
    Modal.confirm({
      title: '重新评审 SPEC',
      content: (
        <div style={{ whiteSpace: 'pre-wrap' }}>
          {`确认重新评审 SPEC「${record.name}」？\n\n`}
          将把 SPEC 从 blocked 移回 reviewing，并由评审 Agent 重新执行方案评审。
          {'\n'}（仅评审相关 blocked 可重新评审；冻结 SPEC 与担责放行请走「修改状态」）
        </div>
      ),
      okText: '重新评审',
      cancelText: '取消',
      onOk: async () => {
        try {
          const result = await reReviewSpec(name, record.name);
          message.success(`SPEC「${record.name}」已重新进入评审`);
          void load();
        } catch (err) {
          // 后端拒绝（非 blocked / 冻结 / 前缀不符等）→ 展示明确拒绝原因
          message.error(`重新评审失败：${err instanceof Error ? err.message : String(err)}`);
        }
      },
    });
  };

  const handlePriorityOk = async () => {
    if (!priorityEdit) return;
    try {
      await setSpecPriority(name, priorityEdit.spec, priorityEdit.value);
      setPriorityEdit(null);
      void load();
    } catch (err) {
      console.error(err);
    }
  };

  const handleAdminInvoke = (record: SpecSummary) => {
    setAdminInvoke({ spec: record.name });
  };

  // ── 设置拾取时间（add-spec-scheduling-controls D6 / add-spec-manual-activation 7.6）──
  const openStartAfterModal = (record: SpecSummary) => {
    // 哨兵 manual 时 MUST NOT 走 dayjs()——dayjs('manual') 为 Invalid Date，
    // DatePicker 显示异常，且 toISOString() 会抛 RangeError。降级为「预填 null +
    // 提示当前为待激活态，请用『修改状态』弹窗的『激活』按钮或重新选择时间」。
    if (record.start_after === 'manual') {
      setSaDate(null);
      message.info('该 SPEC 当前为待激活态（start_after: manual）——请用「修改状态」弹窗的「激活」按钮，或在此重新选择时间');
      setStartAfterEdit({ spec: record.name });
      return;
    }
    // 预填既有定时（ISO → 本地时区展示）；无定时则为 null（清除路径）
    setSaDate(record.start_after ? dayjs(record.start_after) : null);
    setStartAfterEdit({ spec: record.name });
  };

  const handleStartAfterOk = async () => {
    if (!startAfterEdit) return;
    try {
      // DatePicker 输入为本地时区；dayjs.toISOString() 输出 UTC ISO8601（Z 后缀）
      // 哨兵安全降级：非法/不存在日期 MUST NOT 静默把哨兵清成 null，拒绝提交并提示
      if (saDate && !saDate.isValid()) {
        message.error('所选时间无效，请重新选择');
        return;
      }
      const value = saDate ? saDate.toISOString() : null;
      await setSpecStartAfter(name, startAfterEdit.spec, value);
      message.success(saDate ? '已设置定时拾取时间' : '已清除定时，立即恢复调度');
      setStartAfterEdit(null);
      void load();
    } catch (err) {
      message.error(`设置失败：${err instanceof Error ? err.message : String(err)}`);
    }
  };

  const specMenuItems = (record: SpecSummary) => {
    const terminal = PRIORITY_TERMINAL.has(record.status || '');
    // add-spec-archive：已归档视图操作收敛——隐藏调度类操作（优先级/冻结/归档），
    // 仅保留查看类（删除保留与否依实现；归档 SPEC 不可再调度，全部调度项移除）
    if (archivedOnly) {
      return [
        { type: 'divider' as const },
        { key: 'delete', label: '删除 SPEC', danger: true },
      ];
    }
    // add-spec-status-modal-budget D2：菜单收敛——状态类操作（晋升/冻结/解冻/
    // 冻结管理/归档）全部并入「修改状态」弹窗，保留 admin/priority/pickup-time/delete。
    // 终态置灰仅作用于 priority/pickup-time（现状语义）；「修改状态」终态仍可点
    // （归档区块可用）。
    // add-spec-scheduling-controls：非终态 spec 可设置定时拾取（start_after）
    const reviewBlocked =
      (record.status === 'blocked' &&
        (record.error || '').startsWith('spec-review-rejected:')) ||
      (record.status === 'blocked' &&
        (record.error || '').startsWith('spec-review-incomplete:'));
    return [
      { key: 'status', label: '修改状态' },
      // add-spec-review-gate D8：评审相关 blocked（error 前缀 spec-review-*）
      // 增「重新评审」入口（非评审类 blocked 不显示）
      ...(reviewBlocked ? [{ key: 're-review', label: '重新评审' }] : []),
      { key: 'admin', label: '呼叫 Admin 介入' },
      { key: 'priority', label: '调整优先级', disabled: terminal },
      // add-spec-scheduling-controls：非终态 spec 可设置定时拾取（start_after）
      { key: 'pickup-time', label: '设置拾取时间', disabled: terminal },
      { type: 'divider' as const },
      { key: 'delete', label: '删除 SPEC', danger: true },
    ];
  };

  const onSpecMenu = (record: SpecSummary, key: string) => {
    if (key === 'status') {
      setStatusModal({ spec: record.name });
    } else if (key === 'admin') {
      void handleAdminInvoke(record);
    } else if (key === 'priority') {
      setPriorityEdit({ spec: record.name, value: record.priority ?? 5 });
    } else if (key === 'pickup-time') {
      openStartAfterModal(record);
    } else if (key === 'delete') {
      handleDeleteSpec(record);
    } else if (key === 're-review') {
      handleReReview(record);
    }
  };

  const columns: ColumnsType<SpecSummary> = [
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      width: '12%',
      sorter: (a: SpecSummary, b: SpecSummary) => (a.status || '').localeCompare(b.status || ''),
      onHeaderCell: () => ({ style: { whiteSpace: 'nowrap', paddingInline: 8 } }),
      onCell: () => ({ style: { whiteSpace: 'nowrap', paddingInline: 8 } }),
      render: (v: string | null, record: SpecSummary) => {
        const m = statusMeta(v || '');
        return (
          <Space size={4} wrap>
            <Badge color={TONE_DOT[m.tone]} text={m.label} />
            <StatusWaitGroup record={record} />
          </Space>
        );
      },
    },
    {
      title: '模式',
      dataIndex: 'mode',
      key: 'mode',
      width: '9%',
      sorter: (a: SpecSummary, b: SpecSummary) => (a.mode || '').localeCompare(b.mode || ''),
      onHeaderCell: () => ({ style: { whiteSpace: 'nowrap', paddingInline: 8 } }),
      onCell: () => ({ style: { whiteSpace: 'nowrap', paddingInline: 8 } }),
      // add-fast-track-mode（task 7.2）：执行模式标记——fast-track 与 full 可辨识，
      // 存量无 mode 字段的 spec 按缺省 full 展示「完整模式」等价标记
      render: (v: string | null | undefined) => (
        v === 'fast-track' ? (
          <Tag color="cyan" style={{ marginInlineEnd: 0 }}>快速模式</Tag>
        ) : (
          <Tag style={{ marginInlineEnd: 0 }}>完整模式</Tag>
        )
      ),
    },
    {
      title: '名称',
      dataIndex: 'name',
      key: 'name',
      width: '28%',
      sorter: (a: SpecSummary, b: SpecSummary) => a.name.localeCompare(b.name),
      render: (_: string, record: SpecSummary) => (
        <SpecNameCell project={name} record={record} />
      ),
    },
    {
      title: '优先级',
      dataIndex: 'priority',
      key: 'priority',
      width: '7%',
      sorter: (a: SpecSummary, b: SpecSummary) => (a.priority ?? 999) - (b.priority ?? 999),
      render: (_: number | null, record: SpecSummary) => (
        <PriorityCell
          record={record}
          onEdit={(r) => setPriorityEdit({ spec: r.name, value: r.priority ?? 5 })}
        />
      ),
    },
    {
      title: '创建时间',
      dataIndex: 'created',
      key: 'created',
      width: '13%',
      sorter: (a: SpecSummary, b: SpecSummary) => (a.created || '').localeCompare(b.created || ''),
      render: (v: string | null) => {
        const d = v ? dayjs(v) : null;
        return d && d.isValid() ? (
          d.format('YYYY-MM-DD HH:mm:ss')
        ) : (
          <Typography.Text type="secondary">—</Typography.Text>
        );
      },
    },
    {
      title: '任务进度',
      key: 'task',
      width: '15%',
      // add-task-progress-verify-phase：排序键跟随显示值——verify 阶段按验证完成度，
      // impl 阶段按任务完成度，消除「显示 A 排序按 B」错位。
      sorter: (a: SpecSummary, b: SpecSummary) => phasePct(a) - phasePct(b),
      render: (_: unknown, record: SpecSummary) => {
        // 阶段感知（add-task-progress-verify-phase）：仅 testing（progress_phase
        // = "verify"）切绿色验证进度，其余状态维持 impl 蓝色路径零回归。
        const isVerify = record.progress_phase === 'verify';
        // verification-phase-progress：执行未开始（verify_total=0）而后端已统计到
        // 出题落盘数时，进度条展示场景生成进度——出题是验证链主要耗时，不能让
        // 进度条在生成阶段长期停在 0/0。青色区分生成与执行两段。
        const gen =
          isVerify && record.verify_total === 0 && record.generation && record.generation.total > 0
            ? record.generation
            : null;
        const p = isVerify
          ? gen
            ? Math.min(100, pct(gen.done, gen.total))
            : pct(record.verify_done, record.verify_total)
          : pct(record.task_done, record.task_total);
        // run 层实时线索（fix-implementer-task-progress D3）：tasks.md 快照落后于
        // run 实际推进（subject 无编号 / agent 未勾 tasks.md）时叠加 run 完成度，
        // 任一数据源失效都不再呈现静止的 0/N；快照已覆盖时不重复打扰。
        // 仅 impl 分支参与渲染——verify 阶段 impl run 已结束，线索无意义。
        const rp = record.run_progress;
        const runAhead = !!rp && rp.done > record.task_done;
        // run-progress-current：done=0 阶段也有进行中任务的观感
        const runCurrent = rp?.current && rp.current.length > 0 ? rp.current : null;
        // 存活心跳（2026-09-15 原地补充）：run_progress 依赖 TaskCreate/TaskUpdate；
        // 该工具族虽经 CLAUDE_CODE_ENABLE_TODO_TOOLS=1 恢复，实现期间 agent 未必
        // 立刻建 Task、历史 run 也可能无事件。run_activity 用「产物是否仍在写」
        // 提供不依赖任务工具的存活线索，仅在无更细粒度线索（current）时兜底显示。
        const runActive = !isVerify && !runCurrent && !!record.run_activity?.active;
        // 对齐 v1：条下方两侧分别显示 done/total 与 百分比
        // 底轨随阶段同 ramp：verify 阶段 0/0 空条靠底轨读出「淡绿=验证未开始」，
        // 否则与 impl 蓝色空条同观感，误读成任务没完成（add-task-progress-verify-phase 补充）。
        return (
          <div style={{ minWidth: 0 }}>
            <Progress
              percent={p}
              size="small"
              showInfo={false}
              strokeColor={gen ? '#13c2c2' : isVerify ? '#52c41a' : '#1677ff'}
              trailColor={isVerify ? (gen ? TRACK_LIGHT : TRACK_GREEN) : TRACK_LIGHT}
            />
            <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12, lineHeight: '18px' }}>
              {isVerify ? (
                <Typography.Text type="secondary" data-testid="task-progress-cell">
                  {gen ? `出题 ${gen.done}/${gen.total}` : `${record.verify_done}/${record.verify_total}`}
                </Typography.Text>
              ) : (
                <Typography.Text type="secondary" data-testid="task-progress-cell">
                  {record.task_done}/{record.task_total}
                  {runAhead && rp ? (
                    <Typography.Text type="warning" style={{ marginLeft: 4 }}>
                      run {rp.done}/{rp.total} 已汇报
                    </Typography.Text>
                  ) : null}
                  {runCurrent ? (
                    <Typography.Text
                      type="warning"
                      style={{ marginLeft: 4, fontSize: 12, verticalAlign: 'text-bottom' }}
                    >
                      进行中 {runCurrent.join('、')}
                    </Typography.Text>
                  ) : null}
                  {runActive ? (
                    <Typography.Text
                      type="warning"
                      data-testid="run-activity-active"
                      style={{ marginLeft: 4, fontSize: 12, verticalAlign: 'text-bottom' }}
                    >
                      进行中
                    </Typography.Text>
                  ) : null}
                </Typography.Text>
              )}
              <Typography.Text type="secondary">{p}%</Typography.Text>
            </div>
            {isVerify && record.verify_current ? (
              <div style={{ fontSize: 12, lineHeight: '18px', color: '#52c41a' }}>
                {record.verify_current}
              </div>
            ) : null}
          </div>
        );
      },
    },
    {
      title: '验证',
      key: 'verify',
      width: '8%',
      sorter: (a: SpecSummary, b: SpecSummary) =>
        pct(a.verify_done, a.verify_total) - pct(b.verify_done, b.verify_total),
      render: (_: unknown, record: SpecSummary) =>
        record.verify_error ? (
          <Tooltip title={record.verify_error}>
            <Typography.Text type="danger">⚠ 验证异常</Typography.Text>
          </Tooltip>
        ) : (
          <VerifyCell project={name} record={record} />
        ),
    },
    {
      title: '耗时',
      dataIndex: 'total_duration',
      key: 'duration',
      width: '8%',
      sorter: (a: SpecSummary, b: SpecSummary) => a.total_duration - b.total_duration,
      render: (v: number) => fmtDuration(v),
    },
    {
      title: '操作',
      key: 'actions',
      width: '10%',
      onCell: () => ({ style: { paddingInline: 0 } }),
      render: (_: unknown, record: SpecSummary) => (
        <Space size={2}>
          <Button type="link" size="small" onClick={() => setDocView(record.name)}>
            文档
          </Button>
          <Dropdown
            menu={{ items: specMenuItems(record), onClick: ({ key }) => onSpecMenu(record, key) }}
            placement="bottomRight"
            trigger={['click']}
          >
            <Button type="link" size="small" icon={<MoreOutlined />}>更多</Button>
          </Dropdown>
        </Space>
      ),
    },
  ];

  return (
    <PageContainer
      breadcrumbRender={false}
      header={{
        // add-project-detail-tabs D4：移除标题栏右端会话按钮（会话入口由「会话」
        // 分面承载）；header 恢复为项目名 + SPEC 计数
        title: (
          <Space size={8} align="baseline" style={{ minWidth: 0 }}>
            <span>{name}</span>
            <Typography.Text type="secondary" style={{ fontSize: 14, fontWeight: 400 }}>
              共 {Object.keys(specMap).length} 个 SPEC
            </Typography.Text>
          </Space>
        ),
        onBack: () => history.push('/overview'),
      }}
    >
      {/* add-project-detail-tabs D1：项目页三分面 Tabs——开发（默认）/质量/会话；
          选中态不持久化到 URL；会话 Panel 的 active 门控见「会话」分面 children */}
      <Tabs
        activeKey={activeTab}
        onChange={setActiveTab}
        items={[
          {
            key: 'dev',
            label: '开发',
            children: (
              <>
                {error ? (
                  <Alert type="error" showIcon style={{ marginBottom: 16 }} message="SPEC 列表加载失败" description={error} />
                ) : null}
                <Card variant="borderless">
        <div
          style={{
            marginBottom: 16,
            display: 'flex',
            flexWrap: 'wrap',
            alignItems: 'center',
            gap: 8,
          }}
        >
          <Space wrap size={8}>
          <Input.Search
            placeholder="搜索名称…"
            allowClear
            value={q}
            onChange={(e) => setQ(e.target.value)}
            style={{ width: 200 }}
          />
          <Select
            mode="multiple"
            showSearch={false}
            allowClear
            placeholder="全部状态"
            maxTagCount="responsive"
            value={statusList}
            onChange={setStatusList}
            style={{ minWidth: 200, maxWidth: 300 }}
            options={[
              'drafted', 'ready', 'reviewing', 'implementing', 'implemented', 'testing',
              'verified', 'bug-found', 'blocked', 'done', 'pushed',
            ].map((k) => ({ value: k, label: statusMeta(k).label }))}
          />
          <Radio.Group
            optionType="button"
            size="middle"
            value={type}
            onChange={(e) => setType(e.target.value as TypeFilter)}
            options={[
              { label: '全部', value: '' },
              { label: '进行中', value: 'active' },
              { label: '已完成', value: 'completed' },
            ]}
          />
          </Space>
          {/* add-spec-archive：归档状态切换（未归档默认 / 已归档），与类型过滤同层客户端过滤；靠右显示 */}
          <Radio.Group
            style={{ marginLeft: 'auto' }}
            optionType="button"
            size="middle"
            value={archivedOnly}
            onChange={(e) => setArchivedOnly(Boolean(e.target.value))}
            options={[
              { label: '未归档', value: false },
              { label: '已归档', value: true },
            ]}
          />
        </div>
        {isMobile ? (
          <SpecCardList
            data={tree}
            project={name}
            loading={loading}
            onDocView={setDocView}
            onMenu={onSpecMenu}
            menuItems={specMenuItems}
            onClearError={handleClearError}
          />
        ) : (
          <Table
            rowKey="name"
            tableLayout="fixed"
            // 未完成（非 done/pushed 终态）行加浅蓝底：内联样式落在 tr 上，
            // antd 的 cell 级 hover 背景（cell-row-hover）不受影响照常生效
            onRow={(record) => ({
              style: PRIORITY_TERMINAL.has(record.status || '')
                ? undefined
                : { backgroundColor: ROW_INCOMPLETE_BG },
            })}
          columns={columns}
          dataSource={tree}
          loading={loading}
          pagination={{ pageSize: 20, showSizeChanger: true, showTotal: (t) => `共 ${t} 条` }}
          expandable={{
            columnWidth: 28,
            expandedRowKeys: expandedKeys,
            onExpandedRowsChange: (keys) => setExpandedKeys(keys),
            // 额外信息（error）行内下方展开，含清除按钮（对齐 v1 spec-info-row）
            expandedRowRender: (record: SpecSummary) =>
              record.error ? (
                <div style={{ display: 'flex', alignItems: 'flex-start', gap: 8 }}>
                  <Tag color="orange" style={{ marginInlineEnd: 0 }}>
                    信息
                  </Tag>
                  <Typography.Text style={{ flex: 1 }}>{record.error}</Typography.Text>
                  <Button size="small" onClick={() => void handleClearError(record)}>
                    清除
                  </Button>
                </div>
              ) : null,
            rowExpandable: (record: SpecSummary) => !!record.error,
          }}
        />
        )}
              </Card>
              </>
            ),
          },
          {
            key: 'quality',
            label: '质量',
            // add-project-detail-tabs：质量视图建设中——纯空态占位，不发起任何数据请求
            children: (
              <Card variant="borderless">
                <Empty description="质量视图建设中" style={{ padding: '64px 0' }} />
              </Card>
            ),
          },
          {
            key: 'session',
            label: '会话',
            // add-project-detail-tabs D2/D3：会话界面内联承载（由 SessionModal 迁移）。
            // active 门控：仅在选中本分面时拉取会话状态与订阅事件流，未选中零请求
            children: <SessionPanel project={name} active={activeTab === 'session'} />,
          },
        ]}
      />

      <SpecDocModal
        project={name}
        spec={docView}
        open={!!docView}
        onClose={() => setDocView(null)}
      />

      <AdminInvokeModal
        project={name}
        spec={adminInvoke?.spec || ''}
        open={!!adminInvoke}
        onClose={() => setAdminInvoke(null)}
      />

      <Modal
        title="调整优先级"
        open={!!priorityEdit}
        onOk={() => void handlePriorityOk()}
        onCancel={() => setPriorityEdit(null)}
        okText="确定"
        cancelText="取消"
      >
        <Space direction="vertical" style={{ width: '100%' }} size={4}>
          <span>
            优先级（P1 最高，P9 最低）：当前 <strong>P{priorityEdit?.value ?? 5}</strong>
          </span>
          <Slider
            min={1}
            max={9}
            step={1}
            value={priorityEdit?.value ?? 5}
            tooltip={{ formatter: (v) => `P${v}` }}
            marks={{ 1: 'P1', 3: 'P3', 5: 'P5', 7: 'P7', 9: 'P9' }}
            onChange={(v) =>
              setPriorityEdit((p) => (p ? { ...p, value: typeof v === 'number' ? v : p.value } : p))
            }
          />
        </Space>
      </Modal>

      {/* add-spec-scheduling-controls：设置拾取时间弹窗（非终态 spec） */}
      <Modal
        title="设置拾取时间"
        open={!!startAfterEdit}
        onOk={() => void handleStartAfterOk()}
        onCancel={() => setStartAfterEdit(null)}
        okText="确定"
        cancelText="取消"
      >
        <Space direction="vertical" style={{ width: '100%' }} size={12}>
          <Typography.Text type="secondary">
            在此时间点之前，daemon 不会拾取该 SPEC（保持当前状态等待调度）。以本地时区选择，
            提交后转为 UTC 存储；也可清除定时使其立即恢复调度。
          </Typography.Text>
          <DatePicker
            showTime
            style={{ width: '100%' }}
            value={saDate}
            onChange={(d) => setSaDate(d)}
            placeholder="选择拾取时间"
          />
          <Button danger type="link" style={{ paddingInline: 0 }} disabled={!saDate} onClick={() => setSaDate(null)}>
            清除定时（立即恢复调度）
          </Button>
        </Space>
      </Modal>

      {/* add-spec-status-modal-budget D1：修改状态弹窗（归档/冻结/晋升/预算四区块，
          桌面与移动端共用 specMenuItems 的 status 入口） */}
      <SpecStatusModal
        project={name}
        spec={statusModal?.spec || ''}
        open={!!statusModal}
        summary={statusModal ? (specMap[statusModal.spec] ?? null) : null}
        onClose={() => setStatusModal(null)}
        onDone={() => void load()}
      />

    </PageContainer>
  );
}
