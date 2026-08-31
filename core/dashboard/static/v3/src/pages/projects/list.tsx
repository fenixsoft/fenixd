import { PageContainer } from '@ant-design/pro-components';
import { Alert, Card, Input, Progress, Radio, Select, Space, Table, Tooltip, Typography } from 'antd';
import type { ColumnsType } from 'antd/es/table';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { history, useParams } from '@umijs/max';
import dayjs from 'dayjs';
import { getSpecs } from '@/services/dashboard';
import { statusMeta } from '@/services/dashboard';
import type { SpecSummary } from '@/services/dashboard';
import { OutlinedTag } from '@/components/StatusTag';

const REFRESH_THROTTLE_MS = 500;
const TRACK_LIGHT = '#e6f4ff'; // antd blue-1，与 #1677ff 同 ramp

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
  const [specs, setSpecs] = useState<SpecSummary[]>([]);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);
  const [q, setQ] = useState('');
  const [status, setStatus] = useState('');
  const [type, setType] = useState<TypeFilter>('');
  const lastRefreshRef = useRef(0);

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

  const columns: ColumnsType<SpecSummary> = [
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      width: 110,
      sorter: (a: SpecSummary, b: SpecSummary) => (a.status || '').localeCompare(b.status || ''),
      render: (v: string | null) => {
        const m = statusMeta(v || '');
        return <OutlinedTag tone={m.tone}>{m.label}</OutlinedTag>;
      },
    },
    {
      title: '名称',
      dataIndex: 'name',
      key: 'name',
      sorter: (a: SpecSummary, b: SpecSummary) => a.name.localeCompare(b.name),
      render: (v: string, record: SpecSummary) => (
        <Space size={4}>
          <Typography.Text strong>{v}</Typography.Text>
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
      width: 90,
      sorter: (a: SpecSummary, b: SpecSummary) => (a.priority ?? 999) - (b.priority ?? 999),
    },
    {
      title: '创建时间',
      dataIndex: 'created',
      key: 'created',
      width: 130,
      sorter: (a: SpecSummary, b: SpecSummary) => (a.created || '').localeCompare(b.created || ''),
      render: (v: string | null) => {
        const d = v ? dayjs(v) : null;
        return d && d.isValid() ? d.format('MM-DD HH:mm') : '';
      },
    },
    {
      title: '任务进度',
      key: 'task',
      width: 190,
      sorter: (a: SpecSummary, b: SpecSummary) =>
        pct(a.task_done, a.task_total) - pct(b.task_done, b.task_total),
      render: (_: unknown, record: SpecSummary) => (
        <Progress
          percent={pct(record.task_done, record.task_total)}
          size="small"
          strokeColor="#1677ff"
          trailColor={TRACK_LIGHT}
          format={() => `${record.task_done}/${record.task_total} · ${pct(record.task_done, record.task_total)}%`}
        />
      ),
    },
    {
      title: '验证',
      key: 'verify',
      width: 90,
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
      width: 110,
      sorter: (a: SpecSummary, b: SpecSummary) => a.total_duration - b.total_duration,
      render: (v: number) => fmtDuration(v),
    },
  ];

  return (
    <PageContainer
      header={{
        title: name,
        subtitle: `${specs.length} 个 SPEC`,
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
              ...Object.entries(statusMetaKeys()).map(([k, label]) => ({ value: k, label })),
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
          columns={columns}
          dataSource={tree}
          loading={loading}
          pagination={{ pageSize: 20, showSizeChanger: true, showTotal: (t) => `共 ${t} 条` }}
          defaultExpandAllRows
        />
      </Card>
    </PageContainer>
  );
}

// STATUS_META 的 key 顺序稳定输出状态下拉选项（label 复用中文标签）
function statusMetaKeys(): Record<string, string> {
  const out: Record<string, string> = {};
  for (const k of [
    'drafted', 'ready', 'implementing', 'implemented', 'testing',
    'verified', 'bug-found', 'blocked', 'done', 'pushed',
  ]) {
    out[k] = statusMeta(k).label;
  }
  return out;
}
