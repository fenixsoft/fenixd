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
  archiveSpec,
  clearSpecError,
  deleteSpec,
  freezeSpec,
  promoteSpec,
  setSpecFreezeConfig,
  setSpecPriority,
  setSpecStartAfter,
  statusMeta,
  unfreezeSpec,
} from '@/services/dashboard';
import type { SpecDetail, SpecSummary } from '@/services/dashboard';
import { fetchProposalWhy } from '@/utils/proposalWhy';
import SpecDocModal from './components/SpecDocModal';
import AdminInvokeModal from './components/AdminInvokeModal';

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

type TypeFilter = '' | 'req' | 'issue';

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
                <ScheduledPickupTag record={record} />
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
  // add-spec-scheduling-controls：冻结管理弹窗（冻结态 spec）
  const [freezeManage, setFreezeManage] = useState<{ spec: string } | null>(null);
  const [freezeMode, setFreezeMode] = useState<'permanent' | 'scheduled'>('permanent');
  const [freezeUntil, setFreezeUntil] = useState<dayjs.Dayjs | null>(null);

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
        if (type === 'req' && s.name.startsWith('fix-')) return false;
        if (type === 'issue' && !s.name.startsWith('fix-')) return false;
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

  // add-spec-archive：归档确认弹窗（对齐删除确认模式：确认 → 调 API → 成功提示+刷新）
  const handleArchiveSpec = (record: SpecSummary) => {
    Modal.confirm({
      title: '归档 SPEC',
      content: (
        <div style={{ whiteSpace: 'pre-wrap' }}>
          {`确认归档 SPEC「${record.name}」？\n\n`}
          将 `spec/changes/{record.name}/` 移入归档目录
          （archive/YYYY-MM-DD-{record.name}/），STATE.md 条目保留。
          {'\n'}归档后可随时在列表「已归档」视图查看。
        </div>
      ),
      okText: '归档',
      cancelText: '取消',
      onOk: async () => {
        try {
          await archiveSpec(name, record.name);
          message.success(`SPEC「${record.name}」已归档`);
          void load();
        } catch (err) {
          message.error(`归档失败：${err instanceof Error ? err.message : String(err)}`);
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

  const isFrozen = (record: SpecSummary) =>
    record.status === 'blocked' &&
    (record.error || '').startsWith('用户指令冻结：');

  const handleFreezeToggle = async (record: SpecSummary) => {
    try {
      if (isFrozen(record)) {
        await unfreezeSpec(name, record.name);
        message.success(`SPEC「${record.name}」已解冻`);
      } else {
        await freezeSpec(name, record.name);
        message.success(`SPEC「${record.name}」已冻结，daemon 停止调度`);
      }
      void load();
    } catch (err) {
      message.error(`操作失败：${err instanceof Error ? err.message : String(err)}`);
    }
  };

  // ── 手动晋升 drafted → ready（add-draft-promotion-gate D5）──────────
  const handlePromoteSpec = (record: SpecSummary) => {
    Modal.confirm({
      title: '晋升 ready',
      content: (
        <div style={{ whiteSpace: 'pre-wrap' }}>
          {`确认将 SPEC「${record.name}」从 drafted 晋升为 ready？\n\n`}
          晋升将执行声明软化与 lint 检查；lint 违规时 SPEC 停留 drafted
          并在 STATE 写入错误明细。
        </div>
      ),
      okText: '晋升',
      cancelText: '取消',
      onOk: async () => {
        try {
          const result = await promoteSpec(name, record.name);
          if (result.ok) {
            message.success(`SPEC「${record.name}」已晋升 ready，等待调度`);
            void load();
          } else {
            // lint 违规或非 drafted 拒绝
            const detail = result.violations?.join('；') || result.reason || result.error || '晋升失败';
            message.error(`晋升失败：${detail}`);
          }
        } catch (err) {
          message.error(`晋升失败：${err instanceof Error ? err.message : String(err)}`);
        }
      },
    });
  };

  // ── 设置拾取时间（add-spec-scheduling-controls D6）──────────────────
  const openStartAfterModal = (record: SpecSummary) => {
    // 预填既有定时（ISO → 本地时区展示）；无定时则为 null（清除路径）
    setSaDate(record.start_after ? dayjs(record.start_after) : null);
    setStartAfterEdit({ spec: record.name });
  };

  const handleStartAfterOk = async () => {
    if (!startAfterEdit) return;
    try {
      // DatePicker 输入为本地时区；dayjs.toISOString() 输出 UTC ISO8601（Z 后缀）
      const value = saDate ? saDate.toISOString() : null;
      await setSpecStartAfter(name, startAfterEdit.spec, value);
      message.success(saDate ? '已设置定时拾取时间' : '已清除定时，立即恢复调度');
      setStartAfterEdit(null);
      void load();
    } catch (err) {
      message.error(`设置失败：${err instanceof Error ? err.message : String(err)}`);
    }
  };

  // ── 冻结管理（add-spec-scheduling-controls D6）──────────────────────
  const openFreezeManage = (record: SpecSummary) => {
    const scheduled = !!record.frozen_until;
    setFreezeMode(scheduled ? 'scheduled' : 'permanent');
    setFreezeUntil(scheduled && record.frozen_until ? dayjs(record.frozen_until) : null);
    setFreezeManage({ spec: record.name });
  };

  const handleFreezeManageOk = async () => {
    if (!freezeManage) return;
    try {
      if (freezeMode === 'scheduled') {
        if (!freezeUntil) {
          message.error('请选择定时解冻时间');
          return;
        }
        await setSpecFreezeConfig(name, freezeManage.spec, 'scheduled', freezeUntil.toISOString());
        message.success('已设置定时解冻，到期 daemon 自动恢复');
      } else {
        await setSpecFreezeConfig(name, freezeManage.spec, 'permanent');
        message.success('已切换为永久冻结（人工解冻）');
      }
      setFreezeManage(null);
      void load();
    } catch (err) {
      message.error(`操作失败：${err instanceof Error ? err.message : String(err)}`);
    }
  };

  const handleFreezeManageUnfreeze = async () => {
    if (!freezeManage) return;
    try {
      await setSpecFreezeConfig(name, freezeManage.spec, 'unfreeze');
      message.success(`SPEC「${freezeManage.spec}」已解冻`);
      setFreezeManage(null);
      void load();
    } catch (err) {
      message.error(`解冻失败：${err instanceof Error ? err.message : String(err)}`);
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
    return [
      // add-draft-promotion-gate：drafted 状态可手动晋升
      ...(record.status === 'drafted'
        ? [{ key: 'promote' as const, label: '晋升 ready' }]
        : []),
      { key: 'admin', label: '呼叫 Admin 介入' },
      { key: 'priority', label: '调整优先级', disabled: terminal },
      // add-spec-scheduling-controls：非终态 spec 可设置定时拾取（start_after）
      { key: 'pickup-time', label: '设置拾取时间', disabled: terminal },
      // add-spec-scheduling-controls：冻结 spec 的「冻结管理」弹窗
      //（永久 ↔ 定时解冻切换、立即解冻），与既有「冻结/解冻 Spec」并存
      ...(isFrozen(record)
        ? [{ key: 'freeze-manage' as const, label: '冻结管理' }]
        : []),
      {
        key: isFrozen(record) ? 'unfreeze' : 'freeze',
        label: isFrozen(record) ? '解冻 SPEC' : '冻结 SPEC',
        disabled: terminal,
      },
      // 归档 Spec：仅终态（done/pushed）可用，非终态置灰；位于「冻结/解冻」之后
      { key: 'archive', label: '归档 SPEC', disabled: !terminal },
      { type: 'divider' as const },
      { key: 'delete', label: '删除 SPEC', danger: true },
    ];
  };

  const onSpecMenu = (record: SpecSummary, key: string) => {
    if (key === 'promote') {
      void handlePromoteSpec(record);
    } else if (key === 'admin') {
      void handleAdminInvoke(record);
    } else if (key === 'priority') {
      setPriorityEdit({ spec: record.name, value: record.priority ?? 5 });
    } else if (key === 'pickup-time') {
      openStartAfterModal(record);
    } else if (key === 'freeze-manage') {
      openFreezeManage(record);
    } else if (key === 'freeze' || key === 'unfreeze') {
      void handleFreezeToggle(record);
    } else if (key === 'archive') {
      handleArchiveSpec(record);
    } else if (key === 'delete') {
      handleDeleteSpec(record);
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
            <ScheduledPickupTag record={record} />
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
        title: (
          <Space size={8} align="baseline">
            <span>{name}</span>
            <Typography.Text type="secondary" style={{ fontSize: 14, fontWeight: 400 }}>
              共 {Object.keys(specMap).length} 个 SPEC
            </Typography.Text>
          </Space>
        ),
        onBack: () => history.push('/overview'),
      }}
    >
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
            allowClear
            placeholder="全部状态"
            maxTagCount="responsive"
            value={statusList}
            onChange={setStatusList}
            style={{ minWidth: 200, maxWidth: 300 }}
            options={[
              'drafted', 'ready', 'implementing', 'implemented', 'testing',
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
              { label: '仅需求', value: 'req' },
              { label: '仅问题', value: 'issue' },
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

      {/* add-spec-scheduling-controls：冻结管理弹窗（冻结态 spec） */}
      <Modal
        title="冻结管理"
        open={!!freezeManage}
        onOk={() => void handleFreezeManageOk()}
        onCancel={() => setFreezeManage(null)}
        okText="确定"
        cancelText="取消"
        footer={
          freezeManage ? (
            <Space>
              <Button danger onClick={() => void handleFreezeManageUnfreeze()}>
                立即解冻
              </Button>
              <Button onClick={() => setFreezeManage(null)}>取消</Button>
              <Button type="primary" onClick={() => void handleFreezeManageOk()}>
                确定
              </Button>
            </Space>
          ) : null
        }
      >
        <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
          <div>
            <Typography.Text type="secondary">当前模式：</Typography.Text>
            <Typography.Text strong>
              {freezeManage && specMap[freezeManage.spec]?.frozen_until
                ? '定时解冻'
                : '永久冻结（人工解冻）'}
            </Typography.Text>
            {freezeManage && specMap[freezeManage.spec]?.frozen_until ? (
              <div style={{ fontSize: 12, color: 'rgba(0, 0, 0, 0.45)' }}>
                目标时间：
                {dayjs(specMap[freezeManage.spec]?.frozen_until).format('YYYY-MM-DD HH:mm')}
                （本地），到期 daemon 自动解冻
              </div>
            ) : null}
          </div>
          {freezeManage && specMap[freezeManage.spec]?.error ? (
            <div>
              <Typography.Text type="secondary">冻结原因：</Typography.Text>
              <Typography.Text>{specMap[freezeManage.spec]?.error}</Typography.Text>
            </div>
          ) : null}
          <Radio.Group
            value={freezeMode}
            onChange={(e) => setFreezeMode(e.target.value as 'permanent' | 'scheduled')}
            options={[
              { label: '永久冻结（人工解冻）', value: 'permanent' },
              { label: '定时解冻', value: 'scheduled' },
            ]}
          />
          {freezeMode === 'scheduled' ? (
            <DatePicker
              showTime
              style={{ width: '100%' }}
              value={freezeUntil}
              onChange={setFreezeUntil}
              placeholder="选择自动解冻时间"
            />
          ) : null}
        </div>
      </Modal>
    </PageContainer>
  );
}
