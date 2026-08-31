import { MoreOutlined } from '@ant-design/icons';
import { PageContainer } from '@ant-design/pro-components';
import {
  Alert,
  App,
  Badge,
  Breadcrumb,
  Button,
  Card,
  Dropdown,
  Input,
  InputNumber,
  Modal,
  Popover,
  Progress,
  Radio,
  Select,
  Space,
  Spin,
  Table,
  Tabs,
  Tag,
  Tooltip,
  Typography,
} from 'antd';
import type { ColumnsType } from 'antd/es/table';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { Key } from 'react';
import { history, useParams } from '@umijs/max';
import dayjs from 'dayjs';
import { getSpecs } from '@/services/dashboard';
import {
  clearSpecError,
  deleteSpec,
  getSpecDoc,
  invokeSpecAdmin,
  setSpecPriority,
  statusMeta,
} from '@/services/dashboard';
import type { SpecSummary } from '@/services/dashboard';
import SpecDocModal from './components/SpecDocModal';

const REFRESH_THROTTLE_MS = 500;
const TRACK_LIGHT = '#e6f4ff'; // antd blue-1，与 #1677ff 同 ramp

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

function extractWhy(markdown: string): string | null {
  if (!markdown) return null;
  const lines = String(markdown).split('\n');
  let start = -1;
  for (let i = 0; i < lines.length; i++) {
    if (/^##\s+why\s*$/i.test(lines[i])) {
      start = i + 1;
      break;
    }
  }
  if (start === -1) return null;
  const collected: string[] = [];
  for (let i = start; i < lines.length; i++) {
    if (/^##\s/.test(lines[i])) break; // 下一个二级标题即段尾（### 子标题不影响）
    collected.push(lines[i]);
  }
  const text = collected.join('\n').trim();
  return text || null;
}

const whyCache = new Map<string, { status: 'loading' | 'done' | 'empty'; promise?: Promise<string | null>; text?: string }>();

function fetchWhyText(project: string, spec: string): Promise<string | null> {
  const key = `${project}│${spec}`;
  const cached = whyCache.get(key);
  if (cached) {
    return cached.status === 'loading' && cached.promise
      ? cached.promise
      : Promise.resolve(cached.text || null);
  }
  const p = getSpecDoc(project, spec, 'proposal')
    .then((d) => {
      const why = d.found ? extractWhy(d.content) : null;
      whyCache.set(key, { status: why ? 'done' : 'empty', text: why || undefined });
      return why;
    })
    .catch(() => {
      whyCache.delete(key); // 失败不缓存，下次 hover 自动重试
      return null;
    });
  whyCache.set(key, { status: 'loading', promise: p });
  return p;
}

function SpecNameCell({ project, record }: { project: string; record: SpecSummary }) {
  const [open, setOpen] = useState(false);
  const [why, setWhy] = useState<string | null>(null);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const onEnter = () => {
    timerRef.current = setTimeout(() => {
      void fetchWhyText(project, record.name).then((text) => {
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
        <div style={{ maxWidth: 420, whiteSpace: 'pre-wrap', fontSize: 13, lineHeight: 1.65 }}>{why}</div>
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

export default function SpecListPage() {
  const { name = '' } = useParams<{ name: string }>();
  const { message } = App.useApp();
  const [specs, setSpecs] = useState<SpecSummary[]>([]);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);
  const [q, setQ] = useState('');
  const [status, setStatus] = useState('');
  const [type, setType] = useState<TypeFilter>('');
  const lastRefreshRef = useRef(0);

  // 文档弹窗（对齐 v1 docmodal：背景/设计/任务清单 三页签）
  const [docView, setDocView] = useState<string | null>(null);

  // 调整优先级弹窗
  const [priorityEdit, setPriorityEdit] = useState<{ spec: string; value: number } | null>(null);

  const load = useCallback(async () => {
    if (!name) return;
    try {
      const d = await getSpecs(name);
      if (d.error) {
        setError(d.error);
      } else {
        setSpecs(d.specs || []);
        setError('');
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, [name]);

  useEffect(() => {
    void load();
    const es = new EventSource('/api/stream');
    es.onmessage = (ev: MessageEvent) => {
      let msg: { type?: string; project?: string } = {};
      try {
        msg = JSON.parse(ev.data);
      } catch {
        return;
      }
      const relevant =
        (msg.type === 'state' && (!msg.project || msg.project === name)) ||
        msg.type === 'run_meta' ||
        msg.type === 'refresh';
      if (!relevant) return;
      const now = Date.now();
      if (now - lastRefreshRef.current < REFRESH_THROTTLE_MS) return;
      lastRefreshRef.current = now;
      void load();
    };
    return () => es.close();
  }, [load, name]);

  const filtered = useMemo(() => {
    const kw = q.trim().toLowerCase();
    return specs.filter((s) => {
      if (kw && !s.name.toLowerCase().includes(kw)) return false;
      if (status && s.status !== status) return false;
      if (type === 'req' && s.name.startsWith('fix-')) return false;
      if (type === 'issue' && !s.name.startsWith('fix-')) return false;
      return true;
    });
  }, [specs, q, status, type]);

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
      title: '删除 Spec',
      content: (
        <div style={{ whiteSpace: 'pre-wrap' }}>
          {`确认删除 Spec「${record.name}」？\n\n`}
          软删除：STATE.md 移除该条目，openspec/changes/{record.name}/ 目录移入 archive 归档。
          {'\n'}归档路径：openspec/changes/archive/{record.name}-&lt;时间戳&gt;/
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

  const handleAdminInvoke = async (record: SpecSummary) => {
    try {
      await invokeSpecAdmin(name, record.name);
      void message.success('已呼叫 Admin 介入');
    } catch (err) {
      void message.warning(err instanceof Error ? err.message : String(err));
    }
  };

  const specMenuItems = [
    { key: 'admin', label: '呼叫 Admin 介入' },
    { key: 'priority', label: '调整优先级' },
    { type: 'divider' as const },
    { key: 'delete', label: '删除 Spec', danger: true },
  ];

  const onSpecMenu = (record: SpecSummary, key: string) => {
    if (key === 'admin') {
      void handleAdminInvoke(record);
    } else if (key === 'priority') {
      setPriorityEdit({ spec: record.name, value: record.priority ?? 5 });
    } else if (key === 'delete') {
      handleDeleteSpec(record);
    }
  };

  const columns: ColumnsType<SpecSummary> = [
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      width: '8%',
      sorter: (a: SpecSummary, b: SpecSummary) => (a.status || '').localeCompare(b.status || ''),
      onHeaderCell: () => ({ style: { whiteSpace: 'nowrap', paddingInline: 8 } }),
      onCell: () => ({ style: { whiteSpace: 'nowrap', paddingInline: 8 } }),
      render: (v: string | null) => {
        const m = statusMeta(v || '');
        return <Badge color={TONE_DOT[m.tone]} text={m.label} />;
      },
    },
    {
      title: '名称',
      dataIndex: 'name',
      key: 'name',
      width: '30%',
      sorter: (a: SpecSummary, b: SpecSummary) => a.name.localeCompare(b.name),
      render: (_: string, record: SpecSummary) => (
        <Space size={4}>
          <SpecNameCell project={name} record={record} />
          {record.error ? (
            <Tooltip title={record.error}>
              <Typography.Text type="danger">⚠</Typography.Text>
            </Tooltip>
          ) : null}
        </Space>
      ),
    },
    {
      title: '优先级',
      dataIndex: 'priority',
      key: 'priority',
      width: '8%',
      sorter: (a: SpecSummary, b: SpecSummary) => (a.priority ?? 999) - (b.priority ?? 999),
      render: (v: number | null) => <span>P{v ?? '?'}</span>,
    },
    {
      title: '创建时间',
      dataIndex: 'created',
      key: 'created',
      width: '10%',
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
      sorter: (a: SpecSummary, b: SpecSummary) =>
        pct(a.task_done, a.task_total) - pct(b.task_done, b.task_total),
      render: (_: unknown, record: SpecSummary) => {
        const p = pct(record.task_done, record.task_total);
        // 对齐 v1：条下方两侧分别显示 done/total 与 百分比
        return (
          <div style={{ minWidth: 0 }}>
            <Progress
              percent={p}
              size="small"
              showInfo={false}
              strokeColor="#1677ff"
              trailColor={TRACK_LIGHT}
            />
            <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12, lineHeight: '18px' }}>
              <Typography.Text type="secondary">
                {record.task_done}/{record.task_total}
              </Typography.Text>
              <Typography.Text type="secondary">{p}%</Typography.Text>
            </div>
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
          <span>
            {record.verify_done}/{record.verify_total}
          </span>
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
            menu={{ items: specMenuItems, onClick: ({ key }) => onSpecMenu(record, key) }}
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
      header={{
        extra: <Breadcrumb items={[{ title: '概览', href: '#/overview' }, { title: name }]} />,
        title: (
          <Space size={8} align="baseline">
            <span>{name}</span>
            <Typography.Text type="secondary" style={{ fontSize: 14, fontWeight: 400 }}>
              共 {specs.length} 个 SPEC
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
        <Space wrap style={{ marginBottom: 16 }}>
          <Input.Search
            placeholder="搜索名称…"
            allowClear
            value={q}
            onChange={(e) => setQ(e.target.value)}
            style={{ width: 200 }}
          />
          <Select
            value={status}
            onChange={setStatus}
            style={{ width: 140 }}
            options={[
              { value: '', label: '全部状态' },
              ...[
                'drafted', 'ready', 'implementing', 'implemented', 'testing',
                'verified', 'bug-found', 'blocked', 'done', 'pushed',
              ].map((k) => ({ value: k, label: statusMeta(k).label })),
            ]}
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
        <Table
          rowKey="name"
          tableLayout="fixed"
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
      </Card>

      <SpecDocModal
        project={name}
        spec={docView}
        open={!!docView}
        onClose={() => setDocView(null)}
      />

      <Modal
        title="调整优先级"
        open={!!priorityEdit}
        onOk={() => void handlePriorityOk()}
        onCancel={() => setPriorityEdit(null)}
        okText="确定"
        cancelText="取消"
      >
        <Space size={8}>
          <span>优先级（P1 最高，P9 最低）：</span>
          <InputNumber
            min={1}
            max={9}
            value={priorityEdit?.value ?? 5}
            onChange={(v) =>
              setPriorityEdit((p) => (p ? { ...p, value: typeof v === 'number' ? v : p.value } : p))
            }
          />
        </Space>
      </Modal>
    </PageContainer>
  );
}
