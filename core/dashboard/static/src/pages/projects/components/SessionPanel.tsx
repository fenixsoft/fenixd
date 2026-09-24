// SessionPanel.tsx — 项目级自由会话内联分面面板（add-project-detail-tabs D2）
//
// 由项目级会话全屏 Modal 迁移（Modal 外壳 → 「会话接入」分面内联容器），会话行为契约零变更：
// 打开流程：GET 拉全量缓冲 → EventSource('/api/stream') → hello 分支用服务端
// cid 注册 watch → 再 GET 重拉一次（兜住注册前窗口），与 ClaudeOutputPane 同构。
// 会话不存在（首次进入）→ 显示「开始会话」空态，点击后显式 POST /api/session/start。
// 分面无会话项目不注册 watch（注册必然 404 → console.error，污染 no_console_error
// 断言；验证 BUG-01 实证，迁移源为合入 main 的 5f5d5846 修复形态）。
// 切离分面（active=false）：unregister watch + eventSource.close() + 清空本地状态，
// 切回分面时重新执行 loadAll() 接回；MUST NOT 终止会话进程本身。
import { useEffect, useRef, useState } from 'react';
import type { CSSProperties } from 'react';
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
  /** 「会话接入」分面是否被选中：激活时拉取会话状态并订阅事件流，切离即释放订阅 */
  active: boolean;
}

// 静态布局样式常量（code-review item d42f28cde496）：内联对象原在渲染体每
// 渲染重建。分面高度 = 视口 − 页面 chrome，纯 CSS 计算（无 JS 量算）：
// 内联分面的父链（ant-pro 布局 / antd Tabs 内部 holder）不被拉伸到视口高度，
// 故 flex:1 撑不满——必须显式给出视口填充高度，否则回落到内容高度（旧的
// minHeight 480 独占），输入区停在视口中部（本项目实测：1000px 视口停在 670）。
// 顶部 190 = 布局顶栏 56 + 页头 72 + Tabs 导航 46 + Tabs 内容上边距 16；
// 底部 32 = 内容容器 padding-bottom。两者在 375~1920 宽 / 700~1440 高下实测恒定。
// 超短视口（<542）由 minHeight 保底，退化为页面滚动。
const PANEL_LAYOUT_STYLE: CSSProperties = {
  display: 'flex',
  flexDirection: 'column',
  height: 'calc(100vh - 222px)',
  minHeight: 320,
};
// 空态/错误分支的视口居中容器（loading 与 error/空态两种主轴方向）
const FILL_CENTER_STYLE: CSSProperties = {
  flex: 1,
  display: 'flex',
  flexDirection: 'column',
  alignItems: 'center',
  justifyContent: 'center',
  gap: 12,
};
const LOADING_ROW_STYLE: CSSProperties = {
  flex: 1,
  display: 'flex',
  alignItems: 'center',
  justifyContent: 'center',
};
const MESSAGE_AREA_STYLE: CSSProperties = { flex: 1, minHeight: 0, position: 'relative' };
const TRUNCATED_BAR_STYLE: CSSProperties = {
  position: 'absolute',
  top: 8,
  left: 0,
  right: 0,
  textAlign: 'center',
};
const INPUT_ROW_STYLE: CSSProperties = {
  display: 'flex',
  alignItems: 'flex-start',
  gap: 8,
  marginTop: 12,
};

export default function SessionPanel({ project, active }: SessionPanelProps) {
  const { message } = App.useApp();
  const [events, setEvents] = useState<SessionEvent[]>([]);
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
  // watch 是否实际注册过：无会话项目（空态）跳过注册但 hello 仍分配 cid，
  // 若照 cid 无条件注销会对「从未注册的 cid」发 DELETE /api/session/watch →
  // 服务端无会话返回 404 → console.error，污染所有访问项目页的
  // no_console_error 断言（本项目验证实测）。仅注册过才注销。
  const watchRegisteredRef = useRef(false);
  // 重试入口（code-review item ca2aab0e3956）：effect 内 loadAll 闭包经本 ref
  // 暴露给 error 分支「重试」按钮——旧实现只清 error，不重跑失败的加载，
  // 用户掉回空/旧面板而无任何重试发生。
  const reloadRef = useRef<(() => void) | null>(null);

  const syncEvents = (next: SessionEvent[]) => {
    // 全量重拉：以快照 uuids 重建去重集合（code-review item 12c190b15530）——
    // 旧实现只 clear，重拉后到达的 SSE session_events 帧若携带快照中已有的
    // 事件（「reload 兜注册窗口」设计必然制造的重叠）会被再次 append 成重复
    // 消息。重建集合后 SSE 增量照旧跳过已见项（design D6）。
    seenUuidsRef.current = new Set(
      next
        .map((ev) => (ev ? (ev.uuid as string | undefined) : undefined))
        .filter((u): u is string => Boolean(u)),
    );
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

  // 快照应用单源（code-review item a4bbea6af729）：会话状态更新块曾在
  // loadAll / afterHello / handleStart 三处复制粘贴，易漂移——抽单一 helper。
  // 会话存在 → 记 cid、置已启动、全量替换事件；不存在 → 空态。
  const applySnapshot = (data: Awaited<ReturnType<typeof getSession>>) => {
    if (data.session) {
      sessionIdRef.current = data.session.id;
      setStarted(true);
      setEnded(false);
      syncEvents(data.events || []);
      setTruncated(Boolean(data.truncated));
      setError('');
    } else {
      // 会话未启动：空态，等待「开始会话」。清 error（item 232d40e20d0c）：
      // 成功获取快照即代表当前真实状态——此前瞬态故障（如重连前 afterHello
      // 失败）落下的「加载失败」不清除会永久遮住空态入口。
      sessionIdRef.current = null;
      setStarted(false);
      syncEvents([]);
      setTruncated(false);
      setError('');
    }
  };

  // 拉全量 + 建立 SSE（分面激活时执行；切离后重新接回）
  useEffect(() => {
    if (!active || !project) return;
    let disposed = false;

    // 快照加载串行化（code-review item 112623f4c6ed）：挂载时 loadAll 与
    // hello 触发的 afterHello 重载并发执行、各自带全量快照调 syncEvents、无
    // 排序守卫——早发出者后返回时旧快照覆盖新快照，中间送达的事件从渲染
    // 列表丢失。经 promise 链按发起顺序串行应用快照（后应用的必然是更晚
    // 发起的加载，包含更新的服务端状态）。
    let loadChain: Promise<void> = Promise.resolve();
    const enqueueSnapshotLoad = (task: () => Promise<void>): Promise<void> => {
      loadChain = loadChain.then(task).catch(() => {});
      return loadChain;
    };

    const loadAll = () =>
      enqueueSnapshotLoad(async () => {
        try {
          setLoading(true);
          const data = await getSession(project);
          if (disposed) return;
          applySnapshot(data);
        } catch (e) {
          if (!disposed) setError(e instanceof Error ? e.message : String(e));
        } finally {
          if (!disposed) setLoading(false);
        }
      });

    // 注册 watch 后重拉一次（兜住注册前的窗口）。
    // 无会话项目（空态）不注册 watch：注册必然 404 → console.error，
    // 污染 web 场景 no_console_error 断言（验证 BUG-01 实证）。
    // 错误分支「重试」按钮的重跑入口（code-review item ca2aab0e3956）
    reloadRef.current = () => {
      void loadAll();
    };

    const afterHello = (cid: string) =>
      enqueueSnapshotLoad(async () => {
        try {
          const data = await getSession(project);
          if (disposed) return;
          applySnapshot(data);
          if (data.session) {
            // 会话存在：用服务端 hello 分配的 cid 注册 watch
            try {
              await registerSessionWatch(project, cid);
              watchRegisteredRef.current = true;
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
          }
          // 无会话（空态）：跳过注册，避免 404 + console.error
        } catch (e) {
          if (!disposed) setError(e instanceof Error ? e.message : String(e));
        }
      });

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
            // 会话已终止（用户停止 / 空闲超时回收 / 进程退出）：服务端会话
            // 已移除，此后注销 watch 必 404（服务端无会话判定）→ 标记未注册，
            // 切离分面不再发 DELETE，避免污染 no_console_error 断言
            watchRegisteredRef.current = false;
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
      reloadRef.current = null;
      es.close();
      eventSourceRef.current = null;
    };
  }, [active, project]);

  // 切离分面：注销 watch（需服务端 cid）+ 清空本地状态，切回重新接回；
  // 仅释放订阅，MUST NOT 终止会话进程本身
  useEffect(() => {
    if (!active) {
      const cid = cidRef.current;
      // 异步注销，不阻塞切面；仅对实际注册过的 watch 注销——
      // 无会话项目从未注册，注销未注册 cid 会 404（服务端无会话判定）
      if (watchRegisteredRef.current && cid && project) {
        void unregisterSessionWatch(project, cid).catch(() => {});
        watchRegisteredRef.current = false;
      }
      // 注销后清空：active→false 转换路径下方清理函数已先行注销（标记已否），
      // cid 不清会在再次切离时被重复 DELETE（404）
      cidRef.current = null;
      // 切离时清空本地状态，切回重新接回（events/started 由 loadAll 重置）
      sessionIdRef.current = null;
      setEnded(false);
      setSending(false);
      setText('');
    }
    // 卸载守卫（code-review item e71b2c2de7cf）：组件在 active===true 且已注册
    // watch 时被销毁，本 effect 主体不会「再跑」（React 卸载只执行清理函数，
    // 旧注释声称的「卸载时本 effect 会再跑」不成立）——服务端订阅泄漏，只剩
    // 显式 !active 转换才释放。清理函数覆盖 unmount（及 active 翻转重建）：
    // 仅注销实际注册过的 watch，并先行清标记，防 active→false 路径主体重复
    // DELETE（404 污染 no_console_error 断言）。
    return () => {
      if (watchRegisteredRef.current) {
        const cid = cidRef.current;
        watchRegisteredRef.current = false;
        if (cid && project) {
          void unregisterSessionWatch(project, cid).catch(() => {});
        }
      }
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [active]);

  // 开始会话：显式创建（唯一允许启动进程的端点），成功后拉全量
  const handleStart = async () => {
    try {
      setLoading(true);
      const res = await startSession(project);
      sessionIdRef.current = res.session.id;
      setStarted(true);
      setEnded(false);
      // 会话由无变有：此前空态 when hello 到达时 afterHello 跳过了 watch 注册
      // （无会话注册必然 404），若此刻不补注册，SSE 将永不推送本会话事件——
      // 发送消息后用户消息不回显、消息流无反馈（本项目验证实测）。用当前
      // hello 分配的连接 cid 补注册；EventSource 自动重连后 afterHello 也会
      // 以新 cid 兜底注册（会话已存在分支），二者不冲突。
      if (!watchRegisteredRef.current && cidRef.current && sessionIdRef.current) {
        try {
          await registerSessionWatch(project, cidRef.current);
          watchRegisteredRef.current = true;
        } catch (e) {
          console.error('Failed to register session watch:', e);
        }
      }
      const data = await getSession(project);
      if (data.session) {
        applySnapshot(data);
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
      // 瞬态发送失败经 message.error 呈现（同 handleStop 口径），不落 error
      // state——error 分支会替换整块对话视图+输入区（转录被隐藏、无法就地
      // 重试，code-review item b1609f78d29c）。并把已乐观清空的草稿还原，
      // 避免失败后用户输入丢失。
      message.error(`发送失败：${e instanceof Error ? e.message : String(e)}`);
      setText(t);
    } finally {
      setSending(false);
    }
  };

  const handleStop = async () => {
    try {
      await stopSession(project);
      setEnded(true);
      // 会话已终止：服务端会话已移除，后续注销 watch 必 404——
      // 标记未注册，切离分面不再发 DELETE（避免污染 no_console_error 断言）
      watchRegisteredRef.current = false;
    } catch (e) {
      message.error(`停止失败：${e instanceof Error ? e.message : String(e)}`);
    }
  };

  // 渲染分支抽具名 helper（code-review item d42f28cde496）：渲染体原为
  // loading→error→!started→默认会话视图的链式嵌套三元（项目规则禁止），
  // 分支语义不可读；改 if/else 早返回，样式引用模块级常量。
  const renderBody = () => {
    if (loading) {
      return (
        <div style={LOADING_ROW_STYLE}>
          <Spin size="small" />
          <Typography.Text type="secondary" style={{ marginLeft: 8 }}>
            加载会话...
          </Typography.Text>
        </div>
      );
    }
    if (error) {
      return (
        <div style={FILL_CENTER_STYLE}>
          <Typography.Text type="danger">加载失败: {error}</Typography.Text>
          {/* 重试 = 清 error + 重跑加载路径（code-review item ca2aab0e3956：
              loadAll 经 reloadRef 从 effect 内暴露；旧实现只清 error，
              不发生任何实际重试） */}
          <Button
            onClick={() => {
              setError('');
              reloadRef.current?.();
            }}
          >
            重试
          </Button>
        </div>
      );
    }
    if (!started) {
      return (
        <div style={FILL_CENTER_STYLE}>
          <Typography.Text type="secondary">尚未接入会话</Typography.Text>
          <Button type="primary" icon={<MessageOutlined />} onClick={() => void handleStart()}>
            开始会话
          </Button>
        </div>
      );
    }
    return (
      <>
        <div style={MESSAGE_AREA_STYLE}>
          <ClaudeMessageList messages={runEventsToChatMessages(events)} showThinking />
          {truncated ? (
            <div style={TRUNCATED_BAR_STYLE}>
              <Typography.Text type="secondary" style={{ fontSize: 12, background: '#fff', padding: '0 8px' }}>
                更早的消息已省略
              </Typography.Text>
            </div>
          ) : null}
        </div>
        <div style={INPUT_ROW_STYLE}>
          <Input.TextArea
            value={text}
            onChange={(e) => setText(e.target.value)}
            placeholder={ended ? '会话已结束' : '输入消息…（Enter 发送，Shift+Enter 换行）'}
            autoSize={{ minRows: 1, maxRows: 5 }}
            disabled={ended || sending}
            onPressEnter={(e) => {
              if (e.nativeEvent.isComposing) return;
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
    );
  };

  return <div style={PANEL_LAYOUT_STYLE}>{renderBody()}</div>;
}