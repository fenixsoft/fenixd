// QualityTab.tsx — 项目页「质量」分面（add-code-review-agent-and-quality-tab D7/5.2-5.10）
//
// 承载当前代码仓的 code-review 问题台账：
// - 可复选问题表格（严重度/文件:行/标题/所属 SPEC/状态列，严重度与状态过滤排序）
// - 右上角两个手动触发按钮（全仓库审查 / 立即审查本周期）
// - 运行中真实进度条（done/total 百分比）+ 当前文件 + 取消按钮
// - 底部「生成修复 SPEC」按钮（选中 > 0 才可用）
// - 行操作：逐条「忽略」（open → ignored）、「清除归属」（in_spec → open）
//
// 配置归属（2026-09-19 用户决策）：本分面**只读触发与展示**，不再承载
// admin.code_review.enabled 开关——配置项归设置页「质量」页签统一管理
// （QualityPanel.tsx），分面承担的是「看结果 + 手动触发」。
//
// active 门控（对齐 SessionPanel）：仅在选中本分面时拉取数据与订阅 SSE，
// 未选中零请求（project-page-tabs 按需加载语义）。
import { useCallback, useEffect, useRef, useState } from 'react';
import {
  App,
  Button,
  Card,
  Progress,
  Select,
  Space,
  Table,
  Tag,
  Typography,
} from 'antd';
import type { ColumnsType } from 'antd/es/table';
import {
  cancelRun,
  generateFixSpec,
  getCodeReviewItems,
  getCodeReviewProgress,
  setCodeReviewItemStatus,
  triggerCodeReview,
} from '../../../services/dashboard';
import type { CodeReviewItem, CodeReviewProgress } from '../../../services/dashboard';

interface QualityTabProps {
  project: string;
  active: boolean;
}

const SEVERITY_COLOR: Record<string, string> = {
  critical: 'red',
  major: 'orange',
  minor: 'gold',
  info: 'blue',
};

const STATUS_TEXT: Record<string, string> = {
  open: 'open',
  in_spec: 'in_spec',
  resolved: 'resolved',
  ignored: 'ignored',
};

const STATUS_COLOR: Record<string, string> = {
  open: 'blue',
  in_spec: 'purple',
  resolved: 'green',
  ignored: 'default',
};

export default function QualityTab({ project, active }: QualityTabProps) {
  const { message, modal } = App.useApp();
  const [items, setItems] = useState<CodeReviewItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [selectedKeys, setSelectedKeys] = useState<React.Key[]>([]);
  const [severityFilter, setSeverityFilter] = useState<string | undefined>();
  const [statusFilter, setStatusFilter] = useState<string | undefined>('open');
  const [progress, setProgress] = useState<CodeReviewProgress | null>(null);
  const [polling, setPolling] = useState(false);
  const [generating, setGenerating] = useState(false);
  const pollTimerRef = useRef<number | null>(null);
  const runningRef = useRef<boolean>(false);

  // ── 数据拉取（active 门控：未选中零请求） ────────────────────────
  const loadItems = useCallback(async () => {
    if (!active || !project) return;
    try {
      setLoading(true);
      const statuses = statusFilter && statusFilter !== 'all' ? [statusFilter] : undefined;
      const data = await getCodeReviewItems(project, statuses);
      setItems(data.items || []);
    } catch (e) {
      message.error(`加载失败: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setLoading(false);
    }
  }, [active, project, statusFilter, message]);

  const loadProgress = useCallback(async () => {
    if (!active || !project) return;
    try {
      const p = await getCodeReviewProgress(project);
      setProgress(p);
      runningRef.current = Boolean(p.running);
      if (p.running) {
        // 运行中：轮询进度（2s），结束兜底刷新表格
        if (pollTimerRef.current !== null) return;
        pollTimerRef.current = window.setInterval(async () => {
          try {
            const p2 = await getCodeReviewProgress(project);
            setProgress(p2);
            if (!p2.running) {
              if (pollTimerRef.current !== null) {
                window.clearInterval(pollTimerRef.current);
                pollTimerRef.current = null;
              }
              runningRef.current = false;
              // 运行结束：刷新问题表格
              void loadItems();
            }
          } catch {
            // 轮询失败继续（下轮重试）
          }
        }, 2000);
      }
    } catch {
      // 进度读取失败静默（非关键路径）
    }
  }, [active, project, loadItems]);

  // 首次加载 + SSE 增量刷新订阅（随 /api/stream + 心跳兜底）
  useEffect(() => {
    if (!active || !project) return;
    let disposed = false;
    void loadItems();
    void loadProgress();

    const es = new EventSource('/api/stream');
    es.onmessage = (ev: MessageEvent) => {
      if (disposed) return;
      let msg: { type?: string } = {};
      try {
        msg = JSON.parse(ev.data);
      } catch {
        return;
      }
      // code-review 相关事件（run 完成/状态流转）→ 刷新表格与进度；
      // 无专用事件时由心跳/轮询兜底（loadProgress 内轮询 + 此处兜底刷新）
      if (msg.type === 'code_review_updated' || msg.type === 'code_review_run_done') {
        void loadItems();
        void loadProgress();
      }
    };
    es.onerror = () => {
      // EventSource 原生自动重连
    };

    // 心跳兜底：每 30s 刷新进度（运行中轮询已覆盖，此处只兜非运行态下的
    // 表格刷新——事件流不可达时数据仍保持新鲜）
    const heartbeat = window.setInterval(() => {
      if (!disposed) {
        void loadItems();
        void loadProgress();
      }
    }, 30000);

    return () => {
      disposed = true;
      es.close();
      window.clearInterval(heartbeat);
      if (pollTimerRef.current !== null) {
        window.clearInterval(pollTimerRef.current);
        pollTimerRef.current = null;
      }
    };
  }, [active, project, loadItems, loadProgress]);

  // 未激活时清理轮询
  useEffect(() => {
    if (!active && pollTimerRef.current !== null) {
      window.clearInterval(pollTimerRef.current);
      pollTimerRef.current = null;
      runningRef.current = false;
    }
  }, [active]);

  // ── 手动触发按钮（5.4） ────────────────────────────────────────
  const handleTrigger = async (scope: 'full' | 'window') => {
    const label = scope === 'full' ? '全仓库审查' : '立即审查本周期';
    try {
      await triggerCodeReview(project, scope);
      message.success(`${label} 已受理，daemon 将开始执行`);
      // 进入运行中态（触发成功标志，下一轮进度轮询接管）
      runningRef.current = true;
      void loadProgress();
      void loadItems();
    } catch (e) {
      const errMsg = e instanceof Error ? e.message : String(e);
      if (errMsg.includes('已有审查在进行中')) {
        message.warning('已有审查在进行中');
      } else {
        message.error(`${label}失败: ${errMsg}`);
      }
    }
  };

  // ── 取消（5.5） ───────────────────────────────────────────────
  const handleCancel = async () => {
    if (!progress?.review_id) return;
    try {
      await cancelRun(project, progress.review_id);
      message.success('已受理取消请求，审查将停止');
    } catch (e) {
      message.error(`取消失败: ${e instanceof Error ? e.message : String(e)}`);
    }
  };

  // ── 生成修复 SPEC（5.6） ────────────────────────────────────────
  const handleGenerate = async () => {
    if (selectedKeys.length === 0 || generating) return;
    setGenerating(true);
    try {
      const result = await generateFixSpec(project, selectedKeys.map(String));
      if (result.ok) {
        message.success(`已生成修复 SPEC：${result.spec_name}`);
        setSelectedKeys([]);
        void loadItems();
      } else {
        message.error(result.error || '生成失败');
      }
    } catch (e) {
      message.error(`生成失败: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setGenerating(false);
    }
  };

  // ── 行操作（5.10）：忽略 / 清除归属 ─────────────────────────────
  const handleIgnore = async (item: CodeReviewItem) => {
    try {
      await setCodeReviewItemStatus(project, item.item_id, 'ignored');
      message.success('已忽略该问题');
      void loadItems();
    } catch (e) {
      message.error(`忽略失败: ${e instanceof Error ? e.message : String(e)}`);
    }
  };

  const handleClearAttribution = async (item: CodeReviewItem) => {
    modal.confirm({
      title: '清除归属',
      content: `把「${item.title}」重置回 open 并清空所属修复 SPEC？`,
      okText: '清除',
      cancelText: '取消',
      onOk: async () => {
        try {
          await setCodeReviewItemStatus(project, item.item_id, 'open');
          message.success('已清除归属，条目回到默认列表');
          void loadItems();
        } catch (e) {
          message.error(`清除失败: ${e instanceof Error ? e.message : String(e)}`);
        }
      },
    });
  };

  const filteredItems = items.filter(
    (it) =>
      (!severityFilter || it.severity === severityFilter) &&
      (!statusFilter || statusFilter === 'all' || it.status === statusFilter),
  );

  const columns: ColumnsType<CodeReviewItem> = [
    {
      title: '严重度',
      dataIndex: 'severity',
      key: 'severity',
      width: 90,
      render: (sev: string) => <Tag color={SEVERITY_COLOR[sev] || 'default'}>{sev}</Tag>,
    },
    {
      title: '文件:行',
      dataIndex: 'file',
      key: 'file',
      width: 260,
      render: (file: string, rec: CodeReviewItem) => (
        <Typography.Text code style={{ fontSize: 12 }}>
          {file}:{rec.line}
        </Typography.Text>
      ),
    },
    {
      title: '问题标题',
      dataIndex: 'title',
      key: 'title',
      render: (title: string, rec: CodeReviewItem) => (
        <Space direction="vertical" size={0}>
          <span>{title}</span>
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            [{rec.category}] {rec.description}
          </Typography.Text>
        </Space>
      ),
    },
    {
      title: '所属 SPEC',
      dataIndex: 'spec_name',
      key: 'spec_name',
      width: 160,
      render: (specName: string | null) =>
        specName ? <Tag color="purple">{specName}</Tag> : <span style={{ color: '#999' }}>—</span>,
    },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      width: 100,
      render: (status: string) => (
        <Tag color={STATUS_COLOR[status] || 'default'}>{STATUS_TEXT[status] || status}</Tag>
      ),
    },
    {
      title: '操作',
      key: 'ops',
      width: 130,
      render: (_: unknown, rec: CodeReviewItem) =>
        rec.status === 'in_spec' ? (
          <Button size="small" type="link" onClick={() => void handleClearAttribution(rec)}>
            清除归属
          </Button>
        ) : rec.status === 'open' ? (
          <Button size="small" type="link" danger onClick={() => void handleIgnore(rec)}>
            忽略
          </Button>
        ) : null,
    },
  ];

  const progressPercent =
    progress && progress.total > 0 ? Math.round((progress.done / progress.total) * 100) : 0;

  return (
    <Card variant="borderless">
      {/* 工具栏：左对齐（严重度/状态下拉框 + 已选计数），右对齐（三个动作按钮同排） */}
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          flexWrap: 'wrap',
          gap: 8,
          marginBottom: 8,
        }}
      >
        <Space wrap>
          <Select
            placeholder="严重度"
            allowClear
            style={{ width: 110 }}
            value={severityFilter}
            onChange={setSeverityFilter}
            options={[
              { value: 'critical', label: 'critical' },
              { value: 'major', label: 'major' },
              { value: 'minor', label: 'minor' },
              { value: 'info', label: 'info' },
            ]}
          />
          <Select
            placeholder="状态"
            style={{ width: 130 }}
            value={statusFilter}
            onChange={setStatusFilter}
            options={[
              { value: 'open', label: 'open（默认）' },
              { value: 'in_spec', label: 'in_spec' },
              { value: 'resolved', label: 'resolved' },
              { value: 'ignored', label: 'ignored' },
            ]}
          />
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            已选 {selectedKeys.length} 条
          </Typography.Text>
        </Space>
        <Space wrap>
          <Button type="primary" disabled={progress?.running} onClick={() => void handleTrigger('full')}>
            全仓库审查
          </Button>
          <Button disabled={progress?.running} onClick={() => void handleTrigger('window')}>
            立即审查本周期
          </Button>
          <Button
            type="primary"
            disabled={selectedKeys.length === 0}
            loading={generating}
            onClick={() => void handleGenerate()}
          >
            生成修复 SPEC{selectedKeys.length > 0 ? `（${selectedKeys.length}）` : ''}
          </Button>
        </Space>
      </div>

      {progress?.running ? (
        <Card size="small" style={{ marginBottom: 12, background: '#fafafa' }}>
          <Space direction="vertical" style={{ width: '100%' }} size={4}>
            <Space style={{ justifyContent: 'space-between', width: '100%' }}>
              <Typography.Text strong>
                审查进行中（{progress.review_kind || 'code-review'}）
              </Typography.Text>
              <Button size="small" onClick={() => void handleCancel()}>
                取消
              </Button>
            </Space>
            <Progress percent={progressPercent} status="active" />
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              {progress.done}/{progress.total} 文件
              {progress.current ? ` · 当前：${progress.current}` : ''}
            </Typography.Text>
          </Space>
        </Card>
      ) : null}

      <Table<CodeReviewItem>
        rowKey="item_id"
        loading={loading}
        dataSource={filteredItems}
        columns={columns}
        size="small"
        rowSelection={{
          selectedRowKeys: selectedKeys,
          onChange: (keys) => setSelectedKeys(keys),
        }}
        pagination={{ pageSize: 10, showSizeChanger: false, hideOnSinglePage: true }}
        locale={{ emptyText: '暂无未处理问题' }}
      />
    </Card>
  );
}