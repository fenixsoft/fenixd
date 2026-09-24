import { AutoComplete, Button, Modal, Spin, Typography, message } from 'antd';
import { useEffect, useRef, useState } from 'react';
import { ApiError, getAdminActivities, invokeSpecAdmin } from '@/services/dashboard';
import { ClaudeOutputPane } from '@/components/claude-msg';
import { MaximizeTitle, useMaximizeModal } from '@/components/useMaximizeModal';

const { Text } = Typography;

interface AdminInvokeModalProps {
  project: string;
  spec: string;
  open: boolean;
  onClose: () => void;
}

const POLL_INTERVAL_MS = 3000;
// 事件数达到 8 才揭示输出区：LLM prefill 阶段无可见输出，过早切换会先呈现
// 一段空白面板，保持等待动画直到确有内容可看。重连已有输出的 run 时尾部
// 事件立即计入 eventCount，几乎立即揭示。
const REVEAL_EVENT_THRESHOLD = 8;

export default function AdminInvokeModal({ project, spec, open, onClose }: AdminInvokeModalProps) {
  const [prompt, setPrompt] = useState('');
  const [sending, setSending] = useState(false);
  const [invoked, setInvoked] = useState(false);
  const [runId, setRunId] = useState<string | null>(null);
  const [eventCount, setEventCount] = useState(0);
  // Administrator 串行处理：发起时若上一次处置尚未完成，本次请求排队等候拾取
  const [queued, setQueued] = useState(false);
  // 本次处置是否已到终态（done/error/missing）：终态后按钮与输入框恢复可用
  const [runDone, setRunDone] = useState(false);
  const pollTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  // 本轮发起时刻（ms）：轮询只采用此后产生的 run，避免 daemon 尚未落 pending 时
  // 取到历史 run；409（已有处置进行中）时放宽为接受现有最新 run。
  const invokeTimeRef = useRef(0);
  const acceptAnyRunRef = useRef(false);
  // 回车发送经 setTimeout 延后触发（等下拉选中项的 onChange 回写），
  // 用 ref 读取最新输入值，避免闭包拿到旧值
  const promptRef = useRef('');
  promptRef.current = prompt;
  const { modalProps, maximizeButton } = useMaximizeModal({
    defaultWidth: '80vw',
    defaultBodyHeight: '72vh',
    extraBodyStyle: { display: 'flex', flexDirection: 'column', paddingTop: 12 },
  });

  const inProgress = invoked && !runDone;
  // 输出区是否已揭示：事件数达标即揭示（重连已有输出时尾部事件立即计入，几乎立即成立）
  const revealed = eventCount >= REVEAL_EVENT_THRESHOLD;

  // 常用问题模板（spec 名替换 XX）
  const templates = [
    { value: `检查 ${spec} 的进度` },
    { value: `调查 ${spec} 出现了什么问题并给出解决方案` },
  ];

  // 打开时重置，并探测该 spec 是否已有进行中的 Admin 处置（自动重连）；
  // 关闭时无需清理（定时器均已移除）
  useEffect(() => {
    if (!open) return;
    setPrompt('');
    setSending(false);
    setInvoked(false);
    setRunId(null);
    setEventCount(0);
    setQueued(false);
    setRunDone(false);
    invokeTimeRef.current = 0;
    acceptAnyRunRef.current = false;
    // 自动重连：最新处置记录为 pending 时直接接管其输出流，避免误关弹窗后
    // 无处找回会话。若用户在探测返回前已发起（409 场景），两者定位的是同一
    // 个 pending run，结果收敛，无需加锁。
    let stopped = false;
    void (async () => {
      try {
        const d = await getAdminActivities(project, spec);
        if (stopped) return;
        const latest = (d.activities || [])[0];
        if (latest?.admin_run_id && latest?.status === 'pending') {
          acceptAnyRunRef.current = true;
          setInvoked(true);
          setRunId(latest.admin_run_id);
        }
      } catch {
        // 探测失败按无进行中处置处理，正常显示输入视图
      }
    })();
    return () => {
      stopped = true;
    };
  }, [open, project, spec]);

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
          if (!stopped) {
            setRunId(rid);
            setQueued(false);
          }
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

  const handleRunStatus = (status: string) => {
    // interrupted/cancelled：终态但非崩溃（daemon 停机/人工取消），同样解除
    // 「处置进行中」——否则被取消的 admin run 会把按钮永久锁死
    if (status === 'done' || status === 'error' || status === 'interrupted'
      || status === 'cancelled' || status === 'missing') {
      setRunDone(true);
      // 处置完成、按钮恢复可用时同步清空输入框，便于直接输入下一个提示词
      setPrompt('');
    }
  };

  const handleSend = async () => {
    // sending 在途守卫：回车经 setTimeout 延后触发且按住会连发，首个请求在途
    // （invoked 尚未置位）时后续回车会重复 POST，且第二次 409 会被误判冲突
    if (sending) return;
    const text = promptRef.current.trim();
    if (!text) {
      message.warning('请输入给 Admin 的提示词');
      return;
    }
    // 处置进行中不允许重复发起（按钮已禁用，此处拦住回车路径）
    if (invoked && !runDone) return;
    setSending(true);
    try {
      await invokeSpecAdmin(project, spec, text);
      invokeTimeRef.current = Date.now();
      acceptAnyRunRef.current = false;
      setRunId(null);
      setEventCount(0);
      setQueued(false);
      setRunDone(false);
      setInvoked(true);
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      // 已有处置进行中优先按结构化字段判定（code-review item bfc474d8431a）：
      // services 层对非 2xx 恒抛带 HTTP 状态码的 ApiError，按 err.status===409
      // 分支不再依赖错误文案措辞；文本子串匹配降级为非 ApiError 的兜底。
      const isConflict = (err instanceof ApiError && err.status === 409)
        || msg.includes('409') || msg.includes('已有');
      if (isConflict) {
        // 已有处置进行中：与成功路径同样复位输出定位状态。若 runId 仍指向已终态的
        // 旧 run，轮询 effect 的守卫会因 runId 非空直接退出，界面停留在旧输出上；
        // 清空后由轮询 effect 借 acceptAnyRunRef 重新定位到进行中的 run
        message.info('已有进行中的 Admin 处置，正在定位其输出');
        acceptAnyRunRef.current = true;
        setRunId(null);
        setEventCount(0);
        setRunDone(false);
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
        <MaximizeTitle
          text={`${spec} · 呼叫 Admin 介入`}
          extra={
            eventCount > 0 && (
              <span style={{ fontSize: 12, color: '#8c8c8c', fontWeight: 400, marginLeft: 8 }}>
                共 {eventCount} 条事件
              </span>
            )
          }
          button={maximizeButton}
        />
      }
      open={open}
      onCancel={(e) => {
        onClose(e);
      }}
      footer={null}
      destroyOnHidden
      {...modalProps}
    >
      <div
        style={{
          flex: 1,
          minHeight: 0,
          position: 'relative',
          overflow: 'hidden',
          border: '1px solid #f0f0f0',
          borderRadius: 8,
          background: '#fafafa',
        }}
      >
        {/* 输出面板：run 定位后立即挂载并开始收流；揭示前隐藏，避免 prefill 空白期露白 */}
        {runId && (
          <div
            style={{
              position: 'absolute',
              inset: 0,
              padding: 12,
              visibility: revealed ? 'visible' : 'hidden',
            }}
          >
            <ClaudeOutputPane
              key={runId}
              runId={runId}
              project={project}
              onEventsCount={setEventCount}
              onRunStatus={handleRunStatus}
            />
          </div>
        )}
        {/* 等待层：事件数达到阈值即移除 */}
        {invoked && (!runId || !revealed) && (
          <div
            style={{
              position: 'absolute',
              inset: 0,
              display: 'flex',
              flexDirection: 'column',
              alignItems: 'center',
              justifyContent: 'center',
              gap: 12,
            }}
          >
            <Spin />
            <Text type="secondary">
              {queued
                ? 'Administrator 正在处理先前的处置，本次请求已排队等候（串行处理，完成后自动开始）…'
                : '等待 Administrator 开始处置…'}
            </Text>
          </div>
        )}
        {!invoked && (
          <div
            style={{
              position: 'absolute',
              inset: 0,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              padding: 24,
            }}
          >
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
          placeholder="输入提示词，回车发起"
          disabled={inProgress}
          defaultActiveFirstOption={false}
          notFoundContent={null}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !e.nativeEvent.isComposing) {
              // antd6 AutoComplete 不支持 onPressEnter（属性被静默忽略）；
              // 延后一拍发送，让下拉中回车选中模板时的 onChange 先回写最新值
              window.setTimeout(() => {
                void handleSend();
              }, 0);
            }
          }}
          // Modal 内浮层默认挂 body 会被 Modal 容器遮挡，挂到触发器父级
          getPopupContainer={(trigger) => trigger.parentElement || document.body}
        />
        {inProgress ? (
          <Button disabled style={{ minWidth: 104 }}>
            处置进行中
          </Button>
        ) : (
          <Button
            type="primary"
            style={{ minWidth: 104 }}
            loading={sending}
            onClick={() => void handleSend()}
          >
            发起处置
          </Button>
        )}
      </div>
    </Modal>
  );
}
