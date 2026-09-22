// claude code 输出面板（自含控件）：拉取 run 尾部事件 + SSE 增量订阅，
// 以 claudecodeui 的富消息形态渲染（Markdown / 代码高亮 / 思考折叠 / 工具卡片）。
// 数据拉取逻辑与 pages/projects/components/RunStream.tsx 同源。
//
// add-run-record-readability：头部「显示思考过程」开关（默认关闭，3.2）与
// 「显示尾部 N / 共 M 条事件」计数 + 「加载更早事件」向前分页（D5）。
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Button, Spin, Switch, Typography } from 'antd';
import { getRunTail, registerRunWatch } from '@/services/dashboard';
import type { RunEvent } from '@/services/dashboard';

import { runEventsToChatMessages } from './runEvents';
import ClaudeMessageList from './ClaudeMessageList';

interface ClaudeOutputPaneProps {
  runId: string;
  project: string;
  tail?: number;
  /** 兼容保留（add-run-record-readability 3.2）：思考显示改由面板头部开关控制
   * （组件内 state，默认关闭），该 prop 不再作为初值；全程无正文形态由
   * runEventsToChatMessages 兜底强制渲染 thinking */
  showThinking?: boolean;
  /** 事件数变化回调（供外层在标题处显示"共 N 条事件"） */
  onEventsCount?: (count: number) => void;
  /** run 终态回调：done / error / missing（供外层恢复输入与按钮状态） */
  onRunStatus?: (status: string) => void;
}

// 前置拼接对界去重（design D5）：live run 在客户端发起窗口请求与后端切片读取
// 之间可能又追加了 G 条 → 后端窗口整体后移 G 条，窗口尾部与已加载头部重叠。
// 取「older 的后缀 == loaded 的前缀」的最长重叠段剔除（归档 run 无追加、重叠为
// 0，原样前置拼接）；头部缺口接受近似，不引入事件唯一 ID（Non-Goals）。
function prependWithoutOverlap(older: RunEvent[], loaded: RunEvent[]): RunEvent[] {
  const maxOverlap = Math.min(older.length, loaded.length);
  if (maxOverlap === 0) return older;
  const loadedHeads: string[] = [];
  for (let i = 0; i < maxOverlap; i++) {
    loadedHeads.push(JSON.stringify(loaded[i]));
  }
  for (let overlap = maxOverlap; overlap > 0; overlap--) {
    let matched = true;
    for (let i = 0; i < overlap; i++) {
      if (JSON.stringify(older[older.length - overlap + i]) !== loadedHeads[i]) {
        matched = false;
        break;
      }
    }
    if (matched) {
      return older.slice(0, older.length - overlap);
    }
  }
  return older;
}

export default function ClaudeOutputPane({
  runId,
  project,
  tail = 300,
  onEventsCount,
  onRunStatus,
}: ClaudeOutputPaneProps) {
  const [events, setEvents] = useState<RunEvent[]>([]);
  const [totalEvents, setTotalEvents] = useState(0);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState('');
  // 显示思考过程开关：默认关闭（thinking 占比 14-19% 且恒为折叠态，关闭后
  // 不再以「已思考数秒」噪声行打断工具聚合）；无正文兜底见 runEvents
  const [thinkingVisible, setThinkingVisible] = useState(false);
  const eventSourceRef = useRef<EventSource | null>(null);
  const cidRef = useRef<string>(`claude-output-${Date.now()}-${Math.random().toString(36).slice(2, 9)}`);
  const isMountedRef = useRef(true);

  useEffect(() => {
    isMountedRef.current = true;
    return () => {
      isMountedRef.current = false;
    };
  }, []);

  // 拉取尾部事件
  useEffect(() => {
    if (!runId || !project) return;

    const loadTail = async () => {
      try {
        setLoading(true);
        const data = await getRunTail(runId, project, tail);
        if (isMountedRef.current) {
          setEvents(data.events || []);
          setTotalEvents(data.total_events || 0);
          setError('');
          onRunStatus?.(data.status || '');
        }
      } catch (e) {
        if (isMountedRef.current) {
          setError(e instanceof Error ? e.message : String(e));
        }
      } finally {
        if (isMountedRef.current) {
          setLoading(false);
        }
      }
    };

    void loadTail();
  }, [runId, project, tail]);

  // 向前分页（design D5）：以 offset_from_end=当前已加载条数重拉并前置拼接，
  // SSE 增量只追加尾部互不冲突；已加载 ≥ total 时按钮禁用
  const loadOlder = useCallback(async () => {
    if (!runId || !project || loadingMore) return;
    setLoadingMore(true);
    try {
      const data = await getRunTail(runId, project, tail, events.length);
      if (isMountedRef.current) {
        setTotalEvents(data.total_events || 0);
        onRunStatus?.(data.status || '');
        const older = prependWithoutOverlap(data.events || [], events);
        if (older.length > 0) {
          setEvents((prev) => [...older, ...prev]);
        }
      }
    } catch (e) {
      console.error('Failed to load earlier events:', e);
    } finally {
      if (isMountedRef.current) {
        setLoadingMore(false);
      }
    }
  }, [runId, project, tail, events, loadingMore]);

  // run watch 注册移入 SSE onmessage 的 hello 分支（需要服务端分配的连接 cid）

  // 监听 SSE 事件（run_events）
  useEffect(() => {
    if (!runId || !project) return;

    const eventSource = new EventSource('/api/stream');
    eventSourceRef.current = eventSource;

    eventSource.onmessage = (ev: MessageEvent) => {
      if (!isMountedRef.current) return;

      let msg: { type?: string; cid?: string; run_id?: string; events?: RunEvent[]; reset?: boolean } = {};
      try {
        msg = JSON.parse(ev.data);
      } catch {
        return;
      }

      // 服务端在 hello 中分配连接 cid —— watch 注册必须用它，否则 _conns.get(cid)
      // 匹配不到连接、订阅静默失效（自造 cid 是无效的）
      if (msg.type === 'hello' && msg.cid) {
        cidRef.current = msg.cid;
        void (async () => {
          try {
            await registerRunWatch(runId, project, msg.cid!);
          } catch (e) {
            console.error('Failed to register run watch:', e);
          }
          // 注册后重拉一次尾部：兜底「run 在 watch 注册前已结束」或「SSE 断线
          // 重连期间错过终态事件」的场景，否则外层永远收不到完成回调
          try {
            const data = await getRunTail(runId, project, tail);
            if (isMountedRef.current) {
              setEvents(data.events || []);
              setTotalEvents(data.total_events || 0);
              onRunStatus?.(data.status || '');
            }
          } catch (e) {
            console.error('Failed to resync run tail:', e);
          }
        })();
        return;
      }

      if (msg.type === 'run_events' && msg.run_id === runId) {
        if (msg.reset) {
          // 产物被轮转/截断：重新拉取完整尾部
          void (async () => {
            try {
              const data = await getRunTail(runId, project, tail);
              if (isMountedRef.current) {
                setEvents(data.events || []);
                setTotalEvents(data.total_events || 0);
                onRunStatus?.(data.status || '');
              }
            } catch (e) {
              console.error('Failed to reload tail:', e);
            }
          })();
        } else if (msg.events && msg.events.length > 0) {
          setEvents((prev) => [...prev, ...msg.events!]);
          const terminal = msg.events.find((ev) => ev.type === 'result' || ev.type === 'error');
          if (terminal) onRunStatus?.(terminal.type === 'result' ? 'done' : 'error');
        }
      }
    };

    eventSource.onerror = () => {
      // EventSource 原生自动重连
    };

    return () => {
      eventSource.close();
      eventSourceRef.current = null;
    };
  }, [runId, project, tail]);

  // 事件数变化通知外层（必须在条件 return 之前调用 hook，否则 loading 翻转时
  // hook 数量变化触发 "Rendered more hooks" 崩溃）
  useEffect(() => {
    onEventsCount?.(events.length);
  }, [events, onEventsCount]);

  const messages = useMemo(
    () => runEventsToChatMessages(events, thinkingVisible),
    [events, thinkingVisible],
  );

  const canLoadOlder = totalEvents > 0 && events.length < totalEvents;

  if (loading) {
    return (
      <div className="flex h-full items-center justify-center">
        <Spin size="small" />
        <Typography.Text type="secondary" style={{ marginLeft: 8 }}>
          加载运行记录...
        </Typography.Text>
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex h-full items-center justify-center">
        <Typography.Text type="danger">加载失败: {error}</Typography.Text>
      </div>
    );
  }

  // run 定位成功但 agent 尚未产出事件：明确提示 loading，避免误以为功能未生效
  if (events.length === 0) {
    return (
      <div className="flex h-full flex-col items-center justify-center">
        <Spin size="small" />
        <Typography.Text type="secondary" style={{ marginTop: 12 }}>
          Administrator 已唤起，等待输出…
        </Typography.Text>
      </div>
    );
  }

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex flex-shrink-0 flex-wrap items-center gap-x-3 gap-y-1 border-b border-border/60 px-3 py-1.5 text-xs text-muted-foreground">
        <span>
          显示尾部 {events.length} / 共 {totalEvents} 条事件
        </span>
        <Button
          size="small"
          disabled={!canLoadOlder}
          loading={loadingMore}
          onClick={() => void loadOlder()}
        >
          加载更早事件
        </Button>
        <span className="ml-auto flex items-center gap-1.5">
          显示思考过程
          <Switch size="small" checked={thinkingVisible} onChange={setThinkingVisible} />
        </span>
      </div>
      <ClaudeMessageList messages={messages} showThinking={thinkingVisible} />
    </div>
  );
}
