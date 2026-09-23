// claude code 输出面板（自含控件）：拉取 run 尾部事件 + SSE 增量订阅，
// 以 claudecodeui 的富消息形态渲染（Markdown / 代码高亮 / 思考折叠 / 工具卡片）。
// 数据拉取逻辑与 pages/projects/components/RunStream.tsx 同源。
//
// add-run-record-readability：头部「显示思考过程」开关（默认关闭，3.2）与
// 「显示尾部 N / 共 M 条事件」计数 + 「加载更早事件」向前分页（D5）。
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { App, Button, Spin, Switch, Typography } from 'antd';
import { getRunTail, registerRunWatch } from '@/services/dashboard';
import type { RunEvent } from '@/services/dashboard';

import { runEventsToChatMessages } from './runEvents';
import ClaudeMessageList from './ClaudeMessageList';

interface ClaudeOutputPaneProps {
  runId: string;
  project: string;
  tail?: number;
  /** 事件数变化回调（供外层在标题处显示"共 N 条事件"） */
  onEventsCount?: (count: number) => void;
  /** run 终态回调：done / error / missing（供外层恢复输入与按钮状态） */
  onRunStatus?: (status: string) => void;
}

// 前置拼接对界去重（design D5）：live run 在客户端发起窗口请求与后端切片读取
// 之间可能又追加了 G 条 → 后端窗口整体后移 G 条，窗口尾部与已加载头部重叠。
// 取「older 的后缀 == loaded 的前缀」的最长重叠段剔除（归档 run 无追加、重叠为
// 0，原样前置拼接）；头部缺口接受近似，不引入事件唯一 ID（Non-Goals）。
// 序列化各做一次 O(n)（code-review item 700e560a4062）：旧实现对每个重叠候选
// 反复 JSON.stringify older 后缀项，最坏 ~n²/2 次大对象序列化卡主线程。
function prependWithoutOverlap(older: RunEvent[], loaded: RunEvent[]): RunEvent[] {
  const maxOverlap = Math.min(older.length, loaded.length);
  if (maxOverlap === 0) return older;
  const loadedHeads: string[] = new Array(maxOverlap);
  for (let i = 0; i < maxOverlap; i++) {
    loadedHeads[i] = JSON.stringify(loaded[i]);
  }
  // 只需 older 的后缀 maxOverlap 项参与比对
  const olderTails: string[] = new Array(maxOverlap);
  for (let i = 0; i < maxOverlap; i++) {
    olderTails[i] = JSON.stringify(older[older.length - maxOverlap + i]);
  }
  for (let overlap = maxOverlap; overlap > 0; overlap--) {
    let matched = true;
    for (let i = 0; i < overlap; i++) {
      if (olderTails[maxOverlap - overlap + i] !== loadedHeads[i]) {
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

// 尾部追加对界去重（code-review item 289e589fb89b）：SSE hello 重同步窗口
//（流上最后 tail 条）与已加载列表按「newer 的前缀 == loaded 的后缀」的最长
// 重叠段剔除，只把真正新增的尾部追加进来——保留用户「加载更早事件」拉到的
// 前缀历史（旧实现整体替换，每次重连都把已加载前缀塌缩回尾窗、计数跳变）。
// 流轮转/截断走 reset 分支整体重拉，不经本函数。
function appendWithoutOverlap(newer: RunEvent[], loaded: RunEvent[]): RunEvent[] {
  const maxOverlap = Math.min(newer.length, loaded.length);
  if (maxOverlap === 0) return newer;
  const loadedTails: string[] = new Array(maxOverlap);
  for (let i = 0; i < maxOverlap; i++) {
    loadedTails[i] = JSON.stringify(loaded[loaded.length - maxOverlap + i]);
  }
  const newerHeads: string[] = new Array(maxOverlap);
  for (let i = 0; i < maxOverlap; i++) {
    newerHeads[i] = JSON.stringify(newer[i]);
  }
  for (let overlap = maxOverlap; overlap > 0; overlap--) {
    let matched = true;
    for (let i = 0; i < overlap; i++) {
      if (newerHeads[i] !== loadedTails[maxOverlap - overlap + i]) {
        matched = false;
        break;
      }
    }
    if (matched) {
      return newer.slice(overlap);
    }
  }
  return newer;
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
  // 分页失败/零进展的瞬时反馈（code-review item 1717797b5fc1）：初载路径有
  // error 态兜底，「加载更早事件」此前只 console.error，点击无任何可见反馈
  const { message } = App.useApp();  // 显示思考过程开关：默认关闭（thinking 占比 14-19% 且恒为折叠态，关闭后
  // 不再以「已思考数秒」噪声行打断工具聚合）；无正文兜底见 runEvents
  const [thinkingVisible, setThinkingVisible] = useState(false);
  const eventSourceRef = useRef<EventSource | null>(null);
  const cidRef = useRef<string>(`claude-output-${Date.now()}-${Math.random().toString(36).slice(2, 9)}`);
  const isMountedRef = useRef(true);
  // 响应币值守卫（code-review item 5dbf7b6044bf）：detail.tsx / AdminRunModal.tsx
  // 等无 key 调用点在 runId 切换时复用本组件实例（不卸载），仅 isMountedRef
  // 拦不住旧 run 的在飞响应——请求时捕获 runId/project，响应回来与最新值比对，
  // 不匹配即丢弃（防止上一 run 的事件前置/覆盖进新 run 列表）。
  const activeRunIdRef = useRef(runId);
  const activeProjectRef = useRef(project);

  useEffect(() => {
    isMountedRef.current = true;
    return () => {
      isMountedRef.current = false;
    };
  }, []);

  useEffect(() => {
    activeRunIdRef.current = runId;
    activeProjectRef.current = project;
  }, [runId, project]);

  // 拉取尾部事件
  useEffect(() => {
    if (!runId || !project) return;

    const reqRunId = runId;
    const reqProject = project;
    const loadTail = async () => {
      try {
        setLoading(true);
        const data = await getRunTail(reqRunId, reqProject, tail);
        if (isMountedRef.current && activeRunIdRef.current === reqRunId && activeProjectRef.current === reqProject) {
          setEvents(data.events || []);
          setTotalEvents(data.total_events || 0);
          setError('');
          onRunStatus?.(data.status || '');
        }
      } catch (e) {
        if (isMountedRef.current && activeRunIdRef.current === reqRunId && activeProjectRef.current === reqProject) {
          setError(e instanceof Error ? e.message : String(e));
        }
      } finally {
        if (isMountedRef.current && activeRunIdRef.current === reqRunId) {
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
    const reqRunId = runId;
    const reqProject = project;
    setLoadingMore(true);
    try {
      const data = await getRunTail(reqRunId, reqProject, tail, events.length);
      if (isMountedRef.current && activeRunIdRef.current === reqRunId && activeProjectRef.current === reqProject) {
        setTotalEvents(data.total_events || 0);
        onRunStatus?.(data.status || '');
        const older = prependWithoutOverlap(data.events || [], events);
        if (older.length > 0) {
          setEvents((prev) => [...older, ...prev]);
        } else if (events.length < (data.total_events || 0)) {
          // 零进展提示（code-review item 1717797b5fc1）：快进流下后端窗口整体
          // 滑过已加载前缀 → 去重后无新内容，events.length 不增长、canLoadOlder
          // 仍为 true，静默重试会让用户反复点击同一窗口
          message.info('本轮未取到更早事件（窗口已被追加推过），请稍后重试');
        }
      }
    } catch (e) {
      console.error('Failed to load earlier events:', e);
      // 失败反馈（code-review item 1717797b5fc1）：分页失败此前只落 console，
      // 用户侧表现为点了没反应
      message.error(`加载更早事件失败：${e instanceof Error ? e.message : String(e)}`);
    } finally {
      if (isMountedRef.current && activeRunIdRef.current === reqRunId) {
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
          // 重连期间错过终态事件」的场景，否则外层永远收不到完成回调。
          // 重同步改为尾部追加合并（code-review item 289e589fb89b）：整体替换
          // 会在每次 hello（含 EventSource 自动重连）把「加载更早事件」拉到的
          // 前缀历史塌缩回尾窗、计数跳变；appendWithoutOverlap 只补真正新增的
          // 尾部。币值守卫防旧 run 的迟到响应污染新 run（item 5dbf7b6044bf）。
          try {
            const data = await getRunTail(runId, project, tail);
            if (isMountedRef.current && activeRunIdRef.current === runId && activeProjectRef.current === project) {
              setTotalEvents(data.total_events || 0);
              onRunStatus?.(data.status || '');
              const newerEvents = data.events || [];
              setEvents((prev) => {
                const newer = appendWithoutOverlap(newerEvents, prev);
                return newer.length > 0 ? [...prev, ...newer] : prev;
              });
            }
          } catch (e) {
            console.error('Failed to resync run tail:', e);
          }
        })();
        return;
      }

      if (msg.type === 'run_events' && msg.run_id === runId) {
        if (msg.reset) {
          // 产物被轮转/截断：重新拉取完整尾部（整体替换合理：旧列表已失效）
          void (async () => {
            try {
              const data = await getRunTail(runId, project, tail);
              if (isMountedRef.current && activeRunIdRef.current === runId && activeProjectRef.current === project) {
                setEvents(data.events || []);
                setTotalEvents(data.total_events || 0);
                onRunStatus?.(data.status || '');
              }
            } catch (e) {
              console.error('Failed to reload tail:', e);
            }
          })();
        } else if (msg.events && msg.events.length > 0) {
          const incoming = msg.events;
          setEvents((prev) => [...prev, ...incoming]);
          // 增量同步推进总数（code-review item 7ae6c2b659c2）：watcher 的
          // run_events 只带增量 events 不带 total，不推进会让「共 M 条」停在
          // 最近一次 REST 拉取值——live run 流入条数超过 stale total 后
          // canLoadOlder（events.length < totalEvents）恒 false，「加载更早
          // 事件」被错误禁用而更早历史仍在。reset/重同步路径整体重拉 total，
          // 不经本分支。
          setTotalEvents((prev) => prev + incoming.length);
          const terminal = incoming.find((ev) => ev.type === 'result' || ev.type === 'error');
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
