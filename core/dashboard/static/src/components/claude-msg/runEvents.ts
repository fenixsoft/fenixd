// RunEvent 流 → ChatMessage 数组转换（fenixd run 产物 → claudecodeui 消息形态）
//
// run 事件携带原始 claude message（message.content 为块数组：thinking / text /
// tool_use；user 侧 tool_result 回填前序工具调用结果）。顶层 content 为字符串时
// 是旧的纯文本事件形态，作为 fallback 处理。
import type { RunEvent } from '@/services/dashboard';
import type { ChatMessage, ToolResult } from './types';

function resultContentToText(content: unknown): string {
  if (content == null) return '';
  if (typeof content === 'string') return content;
  if (Array.isArray(content)) {
    return content
      .map((block) => {
        if (typeof block === 'string') return block;
        if (block && typeof block === 'object') {
          const b = block as Record<string, unknown>;
          if (typeof b.text === 'string') return b.text;
        }
        return '';
      })
      .join('');
  }
  if (typeof content === 'object') {
    const c = content as Record<string, unknown>;
    if (typeof c.text === 'string') return c.text;
  }
  return String(content);
}

function toolResultFromUserMessage(ev: RunEvent): Array<{ toolUseId: string; result: ToolResult }> {
  const out: Array<{ toolUseId: string; result: ToolResult }> = [];
  const message = (ev as Record<string, unknown>).message as
    | { content?: Array<Record<string, unknown>> }
    | undefined;
  const blocks = message?.content;
  if (!Array.isArray(blocks)) return out;
  for (const block of blocks) {
    if (block && block.type === 'tool_result') {
      out.push({
        toolUseId: String(block.tool_use_id || ''),
        result: {
          content: resultContentToText(block.content),
          isError: Boolean(block.is_error),
        },
      });
    }
  }
  return out;
}

/**
 * 取 user 事件的文本：优先顶层 content 字符串；否则从 message.content 块数组
 * 提取 text 块拼接（--replay-user-messages 的 isReplay 回显事件是块数组形态，
 * 顶层无 content，若不提取会渲染成空气泡——design D1「对应前端义务」）。
 * 均无 → 空串（tool_result 消息不含文本，交由调用方跳过）。
 */
function userMessageText(ev: RunEvent): string {
  if (typeof ev.content === 'string') return ev.content;
  const message = (ev as Record<string, unknown>).message as
    | { content?: Array<Record<string, unknown>> }
    | undefined;
  const blocks = message?.content;
  if (!Array.isArray(blocks)) return '';
  return blocks
    .filter((b) => b && typeof b === 'object' && b.type === 'text')
    .map((b) => String(b.text || ''))
    .join('')
    .trim();
}

export function runEventsToChatMessages(events: RunEvent[]): ChatMessage[] {
  const out: ChatMessage[] = [];
  let currentThinking: ChatMessage | null = null;
  const toolIndexById = new Map<string, number>();

  const flushThinking = () => {
    currentThinking = null;
  };

  const pushThinking = (text: string, timestamp: RunEvent['timestamp']) => {
    if (currentThinking) {
      currentThinking.content = (currentThinking.content || '') + text;
      return;
    }
    currentThinking = { type: 'assistant', isThinking: true, content: text, timestamp };
    out.push(currentThinking);
  };

  for (const ev of events) {
    if (!ev) continue;
    const timestamp = ev.timestamp || Date.now();

    // 旧形态：thinking_tokens 流式片段
    if (ev.type === 'system' && ev.subtype === 'thinking_tokens') {
      pushThinking(ev.content || '', timestamp);
      continue;
    }

    // 新形态：原始 claude message（assistant / user 含块数组）
    const rawMessage = (ev as Record<string, unknown>).message as
      | { content?: unknown; role?: string }
      | undefined;

    if (ev.type === 'user') {
      flushThinking();
      const results = toolResultFromUserMessage(ev);
      if (results.length > 0) {
        for (const { toolUseId, result } of results) {
          const idx = toolIndexById.get(toolUseId);
          if (idx != null && out[idx]) {
            out[idx].toolResult = result;
          }
        }
        // tool_result 消息不再渲染文本行（除非另有文本内容）
        const text = userMessageText(ev);
        if (text && text !== '[Request interrupted by user]') {
          out.push({ type: 'user', content: text, timestamp });
        }
        continue;
      }
      // 普通用户消息：优先字符串 content，回显事件（isReplay，块数组无顶层
      // content）经 userMessageText 提取 text 块
      const text = userMessageText(ev);
      if (text) {
        out.push({ type: 'user', content: text, timestamp });
      }
      continue;
    }

    if (ev.type === 'assistant' && rawMessage && Array.isArray(rawMessage.content)) {
      for (const block of rawMessage.content as Array<Record<string, unknown>>) {
        if (!block || typeof block !== 'object') continue;
        if (block.type === 'thinking') {
          pushThinking(String(block.thinking || ''), timestamp);
        } else if (block.type === 'text') {
          flushThinking();
          const text = String(block.text || '');
          if (text.trim()) {
            out.push({ type: 'assistant', content: text, timestamp });
          }
        } else if (block.type === 'tool_use') {
          flushThinking();
          const toolId = String(block.id || `tool-${out.length}`);
          const msg: ChatMessage = {
            type: 'tool',
            isToolUse: true,
            toolName: String(block.name || 'UnknownTool'),
            toolInput: block.input ?? '',
            toolId,
            timestamp,
          };
          toolIndexById.set(toolId, out.length);
          out.push(msg);
        }
      }
      continue;
    }

    // 终态事件：error 渲染为错误行（MessageItem 红色「错误」头），原因在
    // error 字段；interrupted/cancelled 渲染为系统行，原因在 reason 字段。
    // 原先落 fallback 只剩 [error]/[interrupted] 心跳行，原因文本丢失
    // （Max turns (600) reached 之类死因在运行记录里不可见）。
    if (ev.type === 'error' || ev.type === 'interrupted' || ev.type === 'cancelled') {
      const text = String(ev.error || ev.reason || '').trim();
      if (text) {
        flushThinking();
        out.push(
          ev.type === 'error'
            ? { type: 'error', content: text, timestamp }
            : { type: 'system', content: text, timestamp },
        );
      } else {
        out.push({ type: 'system', content: `[${ev.type}]`, timestamp });
      }
      continue;
    }

    // session 终态事件（dashboard-live-session 4.4）：
    // reason 映射为中文系统行，MUST NOT 落 fallback 的 [session_ended]。
    if (ev.type === 'session_ended') {
      flushThinking();
      const reason = (ev.reason as string) || '';
      let label: string;
      switch (reason) {
        case 'idle':
          label = '会话因空闲已自动终止';
          break;
        case 'process_exit':
          label = '会话进程已退出';
          break;
        case 'user':
          label = '会话已停止';
          break;
        case 'shutdown':
          label = 'Dashboard 正在关闭，会话已终止';
          break;
        default:
          label = reason ? `会话已终止（${reason}）` : '会话已终止';
      }
      out.push({ type: 'system', content: label, timestamp });
      continue;
    }

    // fallback：顶层字符串 content（纯文本事件形态）
    const text = typeof ev.content === 'string' ? ev.content : '';
    if (ev.type === 'assistant') {
      flushThinking();
      if (text.trim()) out.push({ type: 'assistant', content: text, timestamp });
    } else if (ev.type === 'system') {
      if (text.trim()) out.push({ type: 'system', content: text, timestamp });
    } else if (ev.type === 'stderr' || ev.type === 'result') {
      // 运行结束标记（如 "[success]"）对对话无信息量，省略
      const label = (text || '').trim();
      if (label && label !== '[success]' && label !== '[error]') {
        out.push({ type: 'system', content: label, timestamp });
      }
    } else {
      // init / hook 等无 content 的结构化事件 → 系统心跳行
      const label = ev.subtype || ev.type;
      if (label && label !== 'system') {
        out.push({ type: 'system', content: `[${label}]`, timestamp });
      }
    }
  }

  return out;
}
