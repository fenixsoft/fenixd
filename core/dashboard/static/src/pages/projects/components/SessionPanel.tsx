// SessionPanel.tsx — 项目级自由会话内联分面面板（add-project-detail-tabs D2）
//
// 由项目级会话全屏 Modal 迁移（Modal 外壳 → 「会话」分面内联容器），会话行为契约零变更：
// 打开流程：GET 拉全量缓冲 → EventSource('/api/stream') → hello 分支用服务端
// cid 注册 watch → 再 GET 重拉一次（兜住注册前窗口），与 ClaudeOutputPane 同构。
// 会话不存在（首次进入）→ 显示「开始会话」空态，点击后显式 POST /api/session/start。
// 分面无会话项目不注册 watch（注册必然 404 → console.error，污染 no_console_error
// 断言；验证 BUG-01 实证，迁移源为合入 main 的 5f5d5846 修复形态）。
// 切离分面（active=false）：unregister watch + eventSource.close() + 清空本地状态，
// 切回分面时重新执行 loadAll() 接回；MUST NOT 终止会话进程本身。
import { useEffect, useRef, useState } from 'react';
import {
  App,
  Button,
  Input,
  Spin,
  Typography,
} from 'antd';
import {
  MessageOutlined,
  SendOutlined,
  StopOutlined,
} from '@ant-design/icons';
import {
  getSession,
  sendSessionMessage,
  startSession,
  stopSession,
  registerSessionWatch,
  unregisterSessionWatch,
} from '@/services/dashboard';
import type { SessionEvent } from '@/services/dashboard';
import { runEventsToChatMessages } from '@/components/claude-msg/runEvents';
import ClaudeMessageList from '@/components/claude-msg/ClaudeMessageList';

interface SessionPanelProps {
  project: string;
  /** 「会话」分面是否被选中：激活时拉取会话状态并订阅事件流，切离即释放订阅 */
  active: boolean;
}

export default function SessionPanel({ project, active }: SessionPanelProps) {
  const { message } = App.useApp();
  const [events, setEvents] = useState<SessionEvent[]>([]);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [sending, setSending] = useState(false);
  const [text, setText] = useState('');
  const [ended, setEnded] = useState(false);
  const [started, setStarted] = useState(false); // 会话是否已启动（session: null 时空态）
  const [truncated, setTruncated] = useState(false);
  const [error, setError] = useState('');
  // 事件 uuid 去重集合：GET 全量重拉时清空重建，SSE 增量跳过已见项；
  // 无 uuid 的事件（stderr / session_ended 本地合成）不进集合
  const seenUuidsRef = useRef<Set<string>>(new Set());
  const eventSourceRef = useRef<EventSource | null>(null);
  // cid 由服务端在 SSE hello 中分配（design D3：自造 cid 会静默失效）。初值必须为
  // null——分面未激活时无任何订阅可注销；若预置自造 cid，下方 [active] 清理
  // effect 会在挂载当帧发出 DELETE /api/session/watch（服务端查不到该 cid 对应
  // 会话）→ 404 → 控制台错误，污染所有访问项目列表页的 no_console_error 断言
  // （2026-09-18 admin 处置 add-spec-manual-activation 时实证）。
  const cidRef = useRef<string | null>(null);
  const sessionIdRef = useRef<string | null>(null);

  const syncEvents = (next: SessionEvent[]) => {
    // 全量重拉：清空重建去重集合（design D6——重拉是唯一可能重复的路径）
    seenUuidsRef.current.clear();
    setEvents(next);
  };

  const appendEvents = (incoming: SessionEvent[]) => {
    const seen = seenUuidsRef.current;
    const fresh: SessionEvent[] = [];
    for (const ev of incoming) {
      if (!ev) continue;
      const uuid = ev.uuid as string | undefined;
      if (uuid) {
        if (seen.has(uuid)) continue;
        seen.add(uuid);
      }
      fresh.push(ev);
    }
    if (fresh.length > 0) {
      setEvents((prev) => [...prev, ...fresh]);
    }
  };

  // 拉全量 + 建立 SSE（分面激活时执行；切离后重新接回）
  useEffect(() => {
    if (!active || !project) return;
    let disposed = false;

    const loadAll = async (): Promise<string | null> => {
      try {
        setLoading(true);
        const data = await getSession(project);
        if (disposed) return null;
        if (data.session) {
          sessionIdRef.current = data.session.id;
          setSessionId(data.session.id);
          setStarted(true);
          setEnded(false);
          syncEvents(data.events || []);
          setTruncated(Boolean(data.truncated));
          setError('');
        } else {
          // 会话未启动：空态，等待「开始会话」
          sessionIdRef.current = null;
          setSessionId(null);
          setStarted(false);
          syncEvents([]);
          setTruncated(false);
        }
        return data.session?.id ?? null;
      } catch (e) {
        if (!disposed) setError(e instanceof Error ? e.message : String(e));
        return null;
      } finally {
        if (!disposed) setLoading(false);
      }
    };

    // 注册 watch 后重拉一次（兜住注册前的窗口）。
    // 无会话项目（空态）不注册 watch：注册必然 404 → console.error，
    // 污染 web 场景 no_console_error 断言（验证 BUG-01 实证）。
    const afterHello = async (cid: string) => {
      try {
        const data = await getSession(project);
        if (disposed) return;
        if (data.session) {
          sessionIdRef.current = data.session.id;
          setSessionId(data.session.id);
          setStarted(true);
          setEnded(false);
          syncEvents(data.events || []);
          setTruncated(Boolean(data.truncated));
          // 会话存在：用服务端 hello 分配的 cid 注册 watch
          try {
            await registerSessionWatch(project, cid);
          } catch (e) {
            console.error('Failed to register session watch:', e);
          }
          // 注册后重拉一次（兜住注册前的窗口，design D6）
          const again = await getSession(project);
          if (disposed) return;
          if (again.session) {
            syncEvents(again.events || []);
            setTruncated(Boolean(again.truncated));
          }
        } else {
          // 无会话（空态）：跳过注册，仅设空态（避免 404 + console.error）
          sessionIdRef.current = null;
          setSessionId(null);
          setStarted(false);
          syncEvents([]);
        }
      } catch (e) {
        if (!disposed) setError(e instanceof Error ? e.message : String(e));
      }
    };

    void loadAll();

    const es = new EventSource('/api/stream');
    eventSourceRef.current = es;
    es.onmessage = (ev: MessageEvent) => {
      if (disposed) return;
      let msg: { type?: string; cid?: string; session_id?: string; events?: SessionEvent[] } = {};
      try {
        msg = JSON.parse(ev.data);
      } catch {
        return;
      }
      // 服务端在 hello 分配连接 cid——watch 注册必须用它
      if (msg.type === 'hello' && msg.cid) {
        cidRef.current = msg.cid;
        void afterHello(msg.cid!);
        return;
      }
      const sid = sessionIdRef.current;
      if (!sid) return;
      if (msg.type === 'session_events' && msg.session_id === sid && msg.events) {
        // 终态事件先置状态（输入区禁用）
        for (const e of msg.events) {
          if (e.type === 'session_ended') {
            setEnded(true);
          }
        }
        appendEvents(msg.events);
      }
    };
    es.onerror = () => {
      // EventSource 原生自动重连
    };

    return () => {
      disposed = true;
      es.close();
      eventSourceRef.current = null;
    };
  }, [active, project]);

  // 切离分面：注销 watch（需服务端 cid）+ 清空本地状态，切回重新接回；
  // 仅释放订阅，MUST NOT 终止会话进程本身
  useEffect(() => {
    if (!active) {
      const cid = cidRef.current;
      // 异步注销，不阻塞切面
      if (cid && project) {
        void unregisterSessionWatch(project, cid).catch(() => {});
        // 注销后清空：卸载时本 effect 会再跑一次，cid 不清会被重复 DELETE（404）
        cidRef.current = null;
      }
      // 切离时清空本地状态，切回重新接回（events/started 由 loadAll 重置）
      sessionIdRef.current = null;
      setSessionId(null);
      setEnded(false);
      setSending(false);
      setText('');
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [active]);

  // 开始会话：显式创建（唯一允许启动进程的端点），成功后拉全量
  const handleStart = async () => {
    try {
      setLoading(true);
      const res = await startSession(project);
      sessionIdRef.current = res.session.id;
      setSessionId(res.session.id);
      setStarted(true);
      setEnded(false);
      const data = await getSession(project);
      if (data.session) {
        syncEvents(data.events || []);
        setTruncated(Boolean(data.truncated));
      }
      setError('');
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  };

  const handleSend = async () => {
    const t = text.trim();
    if (!t || sending || ended) return;
    if (!sessionIdRef.current) {
      message.error('会话尚未启动');
      return;
    }
    setSending(true);
    setText('');
    try {
      await sendSessionMessage(project, t);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setSending(false);
    }
  };

  const handleStop = async () => {
    try {
      await stopSession(project);
      setEnded(true);
    } catch (e) {
      message.error(`停止失败：${e instanceof Error ? e.message : String(e)}`);
    }
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', minHeight: 480, maxHeight: 'calc(100vh - 320px)' }}>
      {loading ? (
        <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
          <Spin size="small" />
          <Typography.Text type="secondary" style={{ marginLeft: 8 }}>
            加载会话...
          </Typography.Text>
        </div>
      ) : error ? (
        <div style={{ flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', gap: 12 }}>
          <Typography.Text type="danger">加载失败: {error}</Typography.Text>
          <Button onClick={() => setError('')}>重试</Button>
        </div>
      ) : !started ? (
        <div style={{ flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', gap: 12 }}>
          <Typography.Text type="secondary">尚未接入会话</Typography.Text>
          <Button type="primary" icon={<MessageOutlined />} onClick={() => void handleStart()}>
            开始会话
          </Button>
        </div>
      ) : (
        <>
          <div style={{ flex: 1, minHeight: 0, position: 'relative' }}>
            <ClaudeMessageList messages={runEventsToChatMessages(events)} showThinking />
            {truncated ? (
              <div style={{ position: 'absolute', top: 8, left: 0, right: 0, textAlign: 'center' }}>
                <Typography.Text type="secondary" style={{ fontSize: 12, background: '#fff', padding: '0 8px' }}>
                  更早的消息已省略
                </Typography.Text>
              </div>
            ) : null}
          </div>
          <div style={{ display: 'flex', alignItems: 'flex-start', gap: 8, marginTop: 12 }}>
            <Input.TextArea
              value={text}
              onChange={(e) => setText(e.target.value)}
              placeholder={ended ? '会话已结束' : '输入消息…（Enter 发送，Shift+Enter 换行）'}
              autoSize={{ minRows: 1, maxRows: 5 }}
              disabled={ended || sending}
              onPressEnter={(e) => {
                if (!e.shiftKey) {
                  e.preventDefault();
                  void handleSend();
                }
              }}
              style={{ flex: 1 }}
            />
            <Button
              type="primary"
              icon={<SendOutlined />}
              disabled={ended || sending || !text.trim()}
              loading={sending}
              onClick={() => void handleSend()}
            >
              发送
            </Button>
            <Button
              danger
              icon={<StopOutlined />}
              disabled={ended}
              onClick={() => void handleStop()}
            >
              停止会话
            </Button>
          </div>
          {ended ? (
            <Typography.Text type="secondary" style={{ display: 'block', marginTop: 8, fontSize: 12 }}>
              会话已结束。切离本分面再切回可开始新会话。
            </Typography.Text>
          ) : null}
        </>
      )}
    </div>
  );
}