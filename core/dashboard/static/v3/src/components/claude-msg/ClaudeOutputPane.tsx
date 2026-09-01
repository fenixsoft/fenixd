// claude code 输出面板（自含控件）：拉取 run 尾部事件 + SSE 增量订阅，
// 以 claudecodeui 的富消息形态渲染（Markdown / 代码高亮 / 思考折叠 / 工具卡片）。
// 数据拉取逻辑与 pages/projects/components/RunStream.tsx 同源。
import { useEffect, useRef, useState } from 'react';
import { Spin, Typography } from 'antd';
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
}

export default function ClaudeOutputPane({ runId, project, tail = 300, onEventsCount }: ClaudeOutputPaneProps) {
  const [events, setEvents] = useState<RunEvent[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
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
          setError('');
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
              }
            } catch (e) {
              console.error('Failed to reload tail:', e);
            }
          })();
        } else if (msg.events && msg.events.length > 0) {
          setEvents((prev) => [...prev, ...msg.events!]);
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
      <ClaudeMessageList messages={runEventsToChatMessages(events)} />
    </div>
  );
}
