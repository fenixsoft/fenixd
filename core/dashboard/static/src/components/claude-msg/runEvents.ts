// RunEvent 流 → ChatMessage 数组转换（fenixd run 产物 → claudecodeui 消息形态）
//
// run 事件携带原始 claude message（message.content 为块数组：thinking / text /
// tool_use；user 侧 tool_result 回填前序工具调用结果）。顶层 content 为字符串时
// 是旧的纯文本事件形态，作为 fallback 处理。
//
// add-run-record-readability D1：结构化事件按分类表处理（唯一权威口径见
// spec/changes/add-run-record-readability/design.md）——心跳类静默、信息类语义化、
// 任务生命周期回填工具卡片，替代原「无字符串 content 一律落 [label] 裸行」的兜底。
// 静默是纯渲染侧行为，原始事件仍完整落盘可查（Non-Goals：不做后端过滤）。
import type { RunEvent } from '@/services/dashboard';
import type { ChatMessage, ToolResult } from './types';

// ── 事件分类表常量（design D1，实现与单测对齐此表） ──────────────────

// kind 归一化：fenixd 自有事件为顶层 type 形态（tool_progress/provider_marker/
// transient_retry/stderr/error 等），SDK 侧结构化事件实测全部为 type:"system" +
// subtype 形态（system/init、system/status、system/task_started…）。分类判定先
// 归一再查表——按顶层 type 直配会使整张名单失效。
function normalizedKind(ev: RunEvent): string {
  if (ev.type === 'system') return String(ev.subtype || '');
  return String(ev.type || '');
}

// 静默名单：零信息心跳/框架内部事件，不产出任何可见行，也不打断连续工具分组
//（runEventsToChatMessages 对静默项不产出条目，等效于不可见分隔符）。
const SILENT_KINDS = new Set([
  'background_tasks_changed',
  'commands_changed',
  'run_metrics',
  'init',
  'status',
  'task_updated',
  'hook_started',
  'hook_response',
  'superseded',
  'turn_extension',
  'timeout_extension',
]);

// stderr 错误词表（固化于常量，统一小写存储）：匹配时对行取小写后 includes，
// 天然大小写不敏感——归档流实测存在 "ECONNREFUSED ..." 这类全大写错误行
//（spec 场景锚定其必须渲染为系统行）。（code-review item 288bc70996d0：
// 旧表混入大小写敏感条目 'Error'/'FATAL' 是死重，大小写不敏感兜底本就覆盖。）
const STDERR_ERROR_KEYWORDS = ['error', 'traceback', 'failed', 'fatal', 'refused'];

function stderrLooksError(line: string): boolean {
  const lower = line.toLowerCase();
  return STDERR_ERROR_KEYWORDS.some((kw) => lower.includes(kw));
}

function strField(rec: Record<string, unknown>, key: string): string {
  const v = rec[key];
  return typeof v === 'string' ? v : '';
}

function truncateText(text: string, max: number): string {
  const t = text.trim();
  return t.length > max ? `${t.slice(0, max)}…` : t;
}

// provider_marker → 「模型路由 <model> @ <provider>（第 i/n 棒）」；字段缺失
// 降级为「模型路由」，MUST NOT 渲染 [label] 裸行或空行。
function providerMarkerText(rec: Record<string, unknown>): string {
  const model = strField(rec, 'model');
  const provider = strField(rec, 'provider');
  const chainIndex = typeof rec.chain_index === 'number' ? rec.chain_index : null;
  const chainLen = typeof rec.chain_len === 'number' ? rec.chain_len : null;
  if (model && provider) {
    if (chainIndex !== null && chainLen !== null) {
      return `模型路由 ${model} @ ${provider}（第 ${chainIndex + 1}/${chainLen} 棒）`;
    }
    return `模型路由 ${model} @ ${provider}`;
  }
  return '模型路由';
}

// transient_retry → 错误样式系统条：瞬断原因 + 退避 + 重试序号 + error 摘要。
// 部分发射点缺 reason/error 字段，按总则降级（有啥渲染啥，全缺 → 「网关瞬断」）。
function transientRetryText(rec: Record<string, unknown>): string {
  const reason = strField(rec, 'reason');
  const backoff = typeof rec.backoff_seconds === 'number' ? rec.backoff_seconds : null;
  const retry = typeof rec.retry_number === 'number' ? rec.retry_number : null;
  const error = strField(rec, 'error');
  let text = reason ? `网关瞬断（${reason}）` : '网关瞬断';
  if (backoff !== null && retry !== null) {
    text += `，${backoff}s 后第 ${retry} 次重试`;
  } else if (backoff !== null) {
    text += `，${backoff}s 后重试`;
  } else if (retry !== null) {
    text += `，第 ${retry} 次重试`;
  }
  if (error) {
    text += `：${truncateText(error, 80)}`;
  }
  return text;
}

// compact_boundary → 「上下文压缩（trigger）：pre → post tokens」。实测载荷整体
// 嵌套于 compact_metadata 内。
function compactBoundaryText(rec: Record<string, unknown>): string {
  const meta = rec.compact_metadata;
  if (meta && typeof meta === 'object' && !Array.isArray(meta)) {
    const m = meta as Record<string, unknown>;
    const trigger = strField(m, 'trigger');
    const pre = typeof m.pre_tokens === 'number' ? m.pre_tokens : null;
    const post = typeof m.post_tokens === 'number' ? m.post_tokens : null;
    if (pre !== null && post !== null) {
      const head = trigger ? `上下文压缩（${trigger}）` : '上下文压缩';
      return `${head}：${pre} → ${post} tokens`;
    }
    if (trigger) return `上下文压缩（${trigger}）`;
  }
  return '上下文压缩';
}

// vcs_state_changed → kind=commit 渲染「提交 @ 分支」（实测载荷仅 kind/branch/cwd，
// 无哈希字段不渲染短哈希，写侧未来补哈希字段时可附显示）；其他 kind 静默。
function vcsCommitText(rec: Record<string, unknown>): string {
  const branch = strField(rec, 'branch');
  const hash = strField(rec, 'hash') || strField(rec, 'commit');
  const shortHash = hash ? hash.slice(0, 7) : '';
  if (shortHash && branch) return `提交 ${shortHash} @ ${branch}`;
  if (shortHash) return `提交 ${shortHash}`;
  if (branch) return `提交 @ ${branch}`;
  return '提交';
}

function resultContentToText(content: unknown): string {
  if (content === null || content === undefined) return '';
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
  const message = (ev as unknown as Record<string, unknown>).message as
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
  const message = (ev as unknown as Record<string, unknown>).message as
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

// 兜底判定（design D4）：全流是否存在含非空 text 块的 assistant 事件。
// deepseek 系全程只有 thinking 块 → false，此时忽略 showThinking=false 强制
// 渲染 thinking，避免界面看似「无 LLM 输出」。
function streamHasAnyAssistantText(events: RunEvent[]): boolean {
  for (const ev of events) {
    if (!ev || ev.type !== 'assistant') continue;
    if (typeof ev.content === 'string' && ev.content.trim()) return true;
    const message = (ev as unknown as Record<string, unknown>).message as
      | { content?: unknown }
      | undefined;
    const blocks = message?.content;
    if (!Array.isArray(blocks)) continue;
    for (const block of blocks) {
      if (block && typeof block === 'object' && block.type === 'text' && String(block.text || '').trim()) {
        return true;
      }
    }
  }
  return false;
}

function parseTimestampMs(timestamp: unknown): number | null {
  if (timestamp === null || timestamp === undefined) return null;
  const t = new Date(timestamp as string | number | Date).getTime();
  return Number.isFinite(t) ? t : null;
}

// thinking 首个非空行截断预览（design D4，约 40 字符）
export function thinkingPreviewText(text: string, max = 40): string {
  const line = (text || '')
    .split('\n')
    .map((l) => l.trim())
    .find(Boolean) || '';
  if (!line) return '';
  return line.length > max ? `${line.slice(0, max)}…` : line;
}

export function runEventsToChatMessages(events: RunEvent[], showThinking: boolean = true): ChatMessage[] {
  const out: ChatMessage[] = [];
  let currentThinking: ChatMessage | null = null;
  const toolIndexById = new Map<string, number>();
  // tool_progress 心跳观测耗时映射（design D1/D3）：tool_use_id → max(elapsed)
  const elapsedByToolId = new Map<string, number>();
  // 兜底：全流无非空 text 块时忽略 showThinking=false 强制渲染 thinking
  const effectiveShowThinking = showThinking || !streamHasAnyAssistantText(events);

  const flushThinking = () => {
    currentThinking = null;
  };

  const pushThinking = (text: string, timestamp: string | number) => {
    if (!effectiveShowThinking) return;
    if (currentThinking) {
      currentThinking.content = (currentThinking.content || '') + text;
      return;
    }
    const msg: ChatMessage = { type: 'assistant', isThinking: true, content: text, timestamp };
    // 兜底强制渲染（design D4）：用户开关关闭但全流无非空正文时打标记，渲染层
    //（MessageItem / rendersNothing）据此豁免隐藏——只改转换层不传导标记会被
    // MessageItem 的 showThinking 隐藏逻辑击穿（verification BUG-02）
    if (!showThinking) msg.thinkingForced = true;
    currentThinking = msg;
    out.push(msg);
  };

  const pushSystem = (content: string, timestamp: string | number) => {
    flushThinking();
    out.push({ type: 'system', content, timestamp });
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
    const rawMessage = (ev as unknown as Record<string, unknown>).message as
      | { content?: unknown; role?: string }
      | undefined;

    if (ev.type === 'user') {
      flushThinking();
      const results = toolResultFromUserMessage(ev);
      if (results.length > 0) {
        for (const { toolUseId, result } of results) {
          const idx = toolIndexById.get(toolUseId);
          if (idx !== undefined && out[idx]) {
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

    // ── 分类表通道（design D1）：kind 归一化后查表 ──
    const kind = normalizedKind(ev);
    const rec = ev as unknown as Record<string, unknown>;

    // tool_progress：无条件静默；但按 parent_tool_use_id（顶层工具无 parent 时
    // 即 tool_use_id 本身）记录 max(elapsed_time_seconds) 供耗时标注
    if (kind === 'tool_progress') {
      const elapsed = rec.elapsed_time_seconds;
      if (typeof elapsed === 'number' && Number.isFinite(elapsed) && elapsed >= 0) {
        for (const key of [rec.parent_tool_use_id, rec.tool_use_id]) {
          if (typeof key === 'string' && key) {
            elapsedByToolId.set(key, Math.max(elapsedByToolId.get(key) ?? 0, elapsed));
          }
        }
      }
      continue;
    }

    // 静默名单：零信息心跳/框架内部事件，不产出任何可见行。
    // 例外（code-review item 3c0281837ea5）：旧形态 system 事件（type:"system" +
    // subtype 命中名单）携带非空字符串 content 时不在此吞掉——静默只针对零载荷
    // 心跳，带内容的旧形态事件落到下方 content 回退照旧渲染（该回退分支本就
    // 载明「旧形态 system 事件带字符串内容：直接渲染」，此早检此前与其矛盾）。
    if (SILENT_KINDS.has(kind)) {
      const hasLegacyText =
        ev.type === 'system' && typeof ev.content === 'string' && ev.content.trim() !== '';
      if (!hasLegacyText) continue;
    }

    // 信息类事件 → 携带关键载荷的语义化系统条（中文），替代 [label] 裸行
    if (kind === 'provider_marker') {
      pushSystem(providerMarkerText(rec), timestamp);
      continue;
    }
    if (kind === 'transient_retry') {
      pushSystem(transientRetryText(rec), timestamp);
      continue;
    }
    if (kind === 'compact_boundary') {
      pushSystem(compactBoundaryText(rec), timestamp);
      continue;
    }
    if (kind === 'vcs_state_changed') {
      // 仅 commit 渲染提交条，其他 kind（如 stage/checkout）静默
      if (strField(rec, 'kind') === 'commit') {
        pushSystem(vcsCommitText(rec), timestamp);
      }
      continue;
    }

    // 任务生命周期：凭 tool_use_id 回填对应工具条目，不渲染独立行；
    // 无匹配卡片（如被分页窗口截断）时兜底为系统条，不静默丢失
    if (kind === 'task_started' || kind === 'task_notification') {
      const toolUseId = strField(rec, 'tool_use_id');
      const idx = toolUseId ? toolIndexById.get(toolUseId) : undefined;
      if (idx !== undefined && out[idx]) {
        const msg = out[idx];
        if (kind === 'task_started') {
          const description = strField(rec, 'description');
          if (description) msg.taskDescription = description;
        } else {
          const status = strField(rec, 'status');
          const summary = strField(rec, 'summary');
          if (status) msg.taskStatus = status;
          if (summary) msg.taskSummary = summary;
        }
        continue;
      }
      const digest = strField(rec, 'description') || strField(rec, 'summary');
      const head = kind === 'task_started' ? '任务已启动' : '任务通知';
      pushSystem(digest ? `${head}：${truncateText(digest, 80)}` : head, timestamp);
      continue;
    }

    // stderr：命中错误词表 → 系统行；未命中 → 静默（30s 存活 stderr 噪声）
    if (kind === 'stderr') {
      // 嵌套三元展开为 if/else（项目清单禁嵌套三元，code-review item 4ac183111d64）
      let line = '';
      if (typeof rec.line === 'string') {
        line = rec.line;
      } else if (typeof ev.content === 'string') {
        line = ev.content;
      }
      const label = line.trim();
      if (label && label !== '[success]' && label !== '[error]' && stderrLooksError(label)) {
        pushSystem(label, timestamp);
      }
      continue;
    }

    // run 终态标记（result 事件，如 "[success]"）对对话无信息量，省略；
    // 其余字符串内容照旧渲染（既有行为不变）
    if (kind === 'result') {
      const label = (typeof ev.content === 'string' ? ev.content : '').trim();
      if (label && label !== '[success]' && label !== '[error]') {
        pushSystem(label, timestamp);
      }
      continue;
    }

    // fallback：顶层字符串 content（纯文本事件形态）
    const text = typeof ev.content === 'string' ? ev.content : '';
    if (ev.type === 'assistant') {
      flushThinking();
      if (text.trim()) out.push({ type: 'assistant', content: text, timestamp });
      continue;
    }
    if (ev.type === 'system' && text.trim()) {
      // 旧形态 system 事件带字符串内容：直接渲染；无内容的 system 形态事件
      // 不在此吞掉，继续落到 fail-open 占位条（design D1：system 形态未分类
      // 事件 MUST 显示归一化 kind，否则整张分类名单失效）
      pushSystem(text, timestamp);
      continue;
    }

    // fail-open：未命中名单的结构化事件渲染「系统事件（<kind>）」占位条
    //（显示归一化 kind 而非吞掉，防止未来新增事件类型被当成心跳静默）
    if (kind) {
      pushSystem(`系统事件（${kind}）`, timestamp);
    }
  }

  // tool_progress 耗时映射回填工具条目（design D3）：无心跳覆盖的工具不写值，
  // 卡片不渲染耗时标注
  if (elapsedByToolId.size > 0) {
    for (const [toolId, idx] of toolIndexById) {
      const elapsed = elapsedByToolId.get(toolId);
      if (elapsed !== undefined) {
        out[idx].toolElapsedSeconds = elapsed;
      }
    }
  }

  // thinking 时长估算 + 首行预览（design D4）：时长 = 所在 assistant 事件与流中
  // 下一个 assistant 事件的 timestamp 差（秒，四舍五入）；下一事件/时间戳缺失或
  // 差值为负 → 不写字段，折叠头回退「已思考数秒」。预览对全部 thinking 生效。
  const assistantTimes: number[] = [];
  for (const ev of events) {
    if (!ev || ev.type !== 'assistant') continue;
    const t = parseTimestampMs(ev.timestamp);
    if (t !== null) assistantTimes.push(t);
  }
  for (const msg of out) {
    if (!msg.isThinking) continue;
    msg.thinkingPreview = thinkingPreviewText(String(msg.content || ''));
    if (assistantTimes.length < 2) continue;
    const t = parseTimestampMs(msg.timestamp);
    if (t === null) continue;
    const next = assistantTimes.find((x) => x > t);
    if (next === undefined) continue;
    const seconds = Math.round((next - t) / 1000);
    if (seconds > 0) msg.thinkingSeconds = seconds;
  }

  return out;
}
