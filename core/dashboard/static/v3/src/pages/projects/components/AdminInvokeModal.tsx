import { AutoComplete, Button, Modal, Space, Spin, Tag, Typography, message } from 'antd';
import { useEffect, useRef, useState } from 'react';
import { getAdminActivities, invokeSpecAdmin } from '@/services/dashboard';
import { ClaudeOutputPane } from '@/components/claude-msg';

const { Text } = Typography;

interface AdminInvokeModalProps {
  project: string;
  spec: string;
  open: boolean;
  onClose: () => void;
}

const POLL_INTERVAL_MS = 3000;

export default function AdminInvokeModal({ project, spec, open, onClose }: AdminInvokeModalProps) {
  const [prompt, setPrompt] = useState('');
  const [sending, setSending] = useState(false);
  const [invoked, setInvoked] = useState(false);
  const [runId, setRunId] = useState<string | null>(null);
  const [eventCount, setEventCount] = useState(0);
  // Administrator 串行处理：发起时若上一次处置尚未完成，本次请求排队等候拾取
  const [queued, setQueued] = useState(false);
  const pollTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  // 本轮发起时刻（ms）：轮询只采用此后产生的 run，避免 daemon 尚未落 pending 时
  // 取到历史 run；409（已有处置进行中）时放宽为接受现有最新 run。
  const invokeTimeRef = useRef(0);
  const acceptAnyRunRef = useRef(false);

  // 常用问题模板（spec 名替换 XX）
  const templates = [
    { value: `检查 ${spec} 的进度` },
    { value: `调查 ${spec} 出现了什么问题并给出解决方案` },
  ];

  // 打开时重置；关闭时停轮询
  useEffect(() => {
    if (open) {
      setPrompt('');
      setSending(false);
      setInvoked(false);
      setRunId(null);
      setEventCount(0);
      setQueued(false);
      invokeTimeRef.current = 0;
      acceptAnyRunRef.current = false;
    }
  }, [open]);

  // 已发起：轮询定位本次处置的 admin run（daemon 异步启动，invoke 响应不含 run_id）
  useEffect(() => {
    if (!open || !invoked || runId) return;
    let stopped = false;
    const poll = async () => {
      try {
        const d = await getAdminActivities(project, spec);
        const latest = (d.activities || [])[0];
        const rid = latest?.admin_run_id;
        const createdMs = latest?.created ? new Date(latest.created).getTime() : 0;
        if (rid && (acceptAnyRunRef.current || createdMs >= invokeTimeRef.current - 5000)) {
          if (!stopped) setRunId(rid);
          return;
        }
        // 最新记录是发起前就在处理的 pending → 本请求排队中，更新提示文案
        if (!stopped && rid && latest?.status === 'pending') {
          setQueued(true);
        }
      } catch {
        // 解析失败保持等待态，下轮再试（与 v1 处置弹窗策略一致）
      }
      if (!stopped) {
        pollTimerRef.current = setTimeout(poll, POLL_INTERVAL_MS);
      }
    };
    void poll();
    return () => {
      stopped = true;
      if (pollTimerRef.current) {
        clearTimeout(pollTimerRef.current);
        pollTimerRef.current = null;
      }
    };
  }, [open, invoked, runId, project, spec]);

  const handleSend = async () => {
    const text = prompt.trim();
    if (!text) {
      message.warning('请输入给 Admin 的提示词');
      return;
    }
    setSending(true);
    try {
      await invokeSpecAdmin(project, spec, text);
      invokeTimeRef.current = Date.now();
      setInvoked(true);
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      if (msg.includes('409') || msg.includes('已有')) {
        // 已有处置进行中：直接进入输出视图定位该 run
        message.info('已有进行中的 Admin 处置，正在定位其输出');
        acceptAnyRunRef.current = true;
        setInvoked(true);
      } else {
        message.error(`发起失败：${msg}`);
      }
    } finally {
      setSending(false);
    }
  };

  return (
    <Modal
      title={
        <span>
          {spec} · 呼叫 Admin 介入
          {eventCount > 0 && (
            <span style={{ fontSize: 12, color: '#8c8c8c', fontWeight: 400, marginLeft: 8 }}>
              共 {eventCount} 条事件
            </span>
          )}
        </span>
      }
      open={open}
      onCancel={(e) => {
        console.log('[admin-modal-close]', e?.type, e?.target?.className || '');
        onClose(e);
      }}
      width="80vw"
      footer={null}
      destroyOnHidden
      styles={{ body: { height: '72vh', display: 'flex', flexDirection: 'column', paddingTop: 12 } }}
    >
      <div
        style={{
          flex: 1,
          minHeight: 0,
          overflow: 'auto',
          border: '1px solid #f0f0f0',
          borderRadius: 8,
          padding: 12,
          background: '#fafafa',
        }}
      >
        {runId ? (
          <ClaudeOutputPane runId={runId} project={project} onEventsCount={setEventCount} />
        ) : invoked ? (
          <div style={{ textAlign: 'center', paddingTop: 80 }}>
            <Space direction="vertical" size={12}>
              <Spin />
              <Text type="secondary">
                {queued
                  ? 'Administrator 正在处理先前的处置，本次请求已排队等候（串行处理，完成后自动开始）…'
                  : '等待 Administrator 开始处置…'}
              </Text>
            </Space>
          </div>
        ) : (
          <div style={{ textAlign: 'center', paddingTop: 80 }}>
            <Text type="secondary">
              在下方输入给 Admin 的提示词（可从输入框下拉选择常用问题），发起后此处将实时展示
              Administrator 的处置输出。
            </Text>
          </div>
        )}
      </div>
      <div style={{ marginTop: 12, display: 'flex', gap: 8 }}>
        <AutoComplete
          style={{ flex: 1 }}
          value={prompt}
          onChange={setPrompt}
          options={templates}
          placeholder="输入提示词，或点击下拉选择常用问题"
          onPressEnter={() => void handleSend()}
          disabled={invoked}
          // Modal 内浮层默认挂 body 会被 Modal 容器遮挡，挂到触发器父级
          getPopupContainer={(trigger) => trigger.parentElement || document.body}
        />
        {invoked ? (
          <Tag style={{ lineHeight: '30px' }}>处置进行中</Tag>
        ) : (
          <Button type="primary" loading={sending} onClick={() => void handleSend()}>
            发起处置
          </Button>
        )}
      </div>
    </Modal>
  );
}
