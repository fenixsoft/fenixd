import { useEffect, useRef, useState } from 'react';
import { Spin, Typography } from 'antd';
import { getRunTail, registerRunWatch, unregisterRunWatch } from '@/services/dashboard';
import type { RunEvent } from '@/services/dashboard';

interface RunStreamProps {
  runId: string;
  project: string;
  tail?: number;
  onEventsUpdate?: (events: RunEvent[]) => void;
}

// 折叠连续的 thinking_tokens 事件
function collapseThinkingTokens(events: RunEvent[]): RunEvent[] {
  const out: RunEvent[] = [];
  let count = 0;
  for (const ev of events) {
    if (ev && ev.type === 'system' && ev.subtype === 'thinking_tokens') {
      count++;
      if (count === 1) out.push({ ...ev, _merged: count });
      continue;
    }
    if (count > 1 && out.length) out[out.length - 1]._merged = count;
    count = 0;
    out.push(ev);
  }
  if (count > 1 && out.length) out[out.length - 1]._merged = count;
  return out;
}

// 格式化单个事件
function formatEvent(ev: RunEvent): string {
  if (ev.type === 'system') {
    if (ev.subtype === 'thinking_tokens') {
      return `[思考] ${ev.content || ''}`;
    }
    return `[系统] ${ev.content || ''}`;
  }
  if (ev.type === 'assistant') {
    return `[助手] ${ev.content || ''}`;
  }
  if (ev.type === 'user') {
    return `[用户] ${ev.content || ''}`;
  }
  return `[${ev.type}] ${ev.content || ''}`;
}

export default function RunStream({ runId, project, tail = 300, onEventsUpdate }: RunStreamProps) {
  const [events, setEvents] = useState<RunEvent[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [totalEvents, setTotalEvents] = useState(0);
  const eventSourceRef = useRef<EventSource | null>(null);
  const cidRef = useRef<string>(`run-stream-${Date.now()}-${Math.random().toString(36).slice(2, 9)}`);
  const isMountedRef = useRef(true);

  // 初始化：拉取尾部事件
  useEffect(() => {
    if (!runId || !project) return;

    const loadTail = async () => {
      try {
        setLoading(true);
        const data = await getRunTail(runId, project, tail);
        if (isMountedRef.current) {
          setEvents(data.events || []);
          setTotalEvents(data.total_events || data.events?.length || 0);
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

  // 注册 SSE watch（用于增量推送）
  useEffect(() => {
    if (!runId || !project) return;

    const register = async () => {
      try {
        await registerRunWatch(runId, project, cidRef.current);
      } catch (e) {
        console.error('Failed to register run watch:', e);
      }
    };

    void register();

    return () => {
      const unregister = async () => {
        try {
          await unregisterRunWatch(runId, project, cidRef.current);
        } catch (e) {
          console.error('Failed to unregister run watch:', e);
        }
      };
      void unregister();
    };
  }, [runId, project]);

  // 监听 SSE 事件（run_events）
  useEffect(() => {
    if (!runId || !project) return;

    // 创建 EventSource 监听 run_events
    const eventSource = new EventSource('/api/stream');
    eventSourceRef.current = eventSource;

    eventSource.onmessage = (ev: MessageEvent) => {
      if (!isMountedRef.current) return;

      let msg: { type?: string; run_id?: string; events?: RunEvent[]; reset?: boolean } = {};
      try {
        msg = JSON.parse(ev.data);
      } catch {
        return;
      }

      // 只处理匹配当前 run_id 的 run_events
      if (msg.type === 'run_events' && msg.run_id === runId) {
        if (msg.reset) {
          // 产物被轮转/截断：重新拉取完整尾部
          void (async () => {
            try {
              const data = await getRunTail(runId, project, tail);
              if (isMountedRef.current) {
                setEvents(data.events || []);
                setTotalEvents(data.total_events || data.events?.length || 0);
              }
            } catch (e) {
              console.error('Failed to reload tail:', e);
            }
          })();
        } else if (msg.events && msg.events.length > 0) {
          // 增量追加事件
          setEvents((prev) => {
            const newEvents = [...prev, ...msg.events!];
            return newEvents;
          });
          setTotalEvents((prev) => prev + msg.events!.length);
        }
      }
    };

    eventSource.onerror = () => {
      // EventSource 原生自动重连，无需手动处理
    };

    return () => {
      eventSource.close();
      eventSourceRef.current = null;
    };
  }, [runId, project, tail]);

  // 卸载清理
  useEffect(() => {
    return () => {
      isMountedRef.current = false;
    };
  }, []);

  // 通知父组件事件更新
  useEffect(() => {
    if (onEventsUpdate) {
      onEventsUpdate(events);
    }
  }, [events, onEventsUpdate]);

  if (loading) {
    return (
      <div style={{ textAlign: 'center', padding: '20px 0' }}>
        <Spin size="small" />
        <div style={{ marginTop: 8 }}>
          <Typography.Text type="secondary">加载运行记录...</Typography.Text>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div style={{ textAlign: 'center', padding: '20px 0' }}>
        <Typography.Text type="danger">加载失败: {error}</Typography.Text>
      </div>
    );
  }

  // 折叠 thinking_tokens 事件
  const collapsedEvents = collapseThinkingTokens(events);

  return (
    <div style={{ maxHeight: 400, overflow: 'auto' }}>
      {collapsedEvents.length === 0 ? (
        <div style={{ textAlign: 'center', padding: '20px 0' }}>
          <Typography.Text type="secondary">暂无运行事件</Typography.Text>
        </div>
      ) : (
        <div>
          {collapsedEvents.map((event, index) => (
            <div
              key={index}
              style={{
                padding: '8px 12px',
                borderBottom: '1px solid #f0f0f0',
                fontFamily: 'monospace',
                fontSize: 13,
              }}
            >
              <Typography.Text style={{ whiteSpace: 'pre-wrap' }}>
                {formatEvent(event)}
                {event._merged && event._merged > 1 && (
                  <Typography.Text type="secondary" style={{ marginLeft: 8 }}>
                    (已合并 {event._merged} 个思考事件)
                  </Typography.Text>
                )}
              </Typography.Text>
            </div>
          ))}
          <div style={{ padding: '8px 12px', textAlign: 'center' }}>
            <Typography.Text type="secondary">
              共 {totalEvents} 条事件
            </Typography.Text>
          </div>
        </div>
      )}
    </div>
  );
}