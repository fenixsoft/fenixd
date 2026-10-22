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
  // subtype 缺失/空串时回退字面量 'system'：归一化空串既不命中静默名单与分类
  // 分支，也过不了末尾 fail-open 的 if (kind) 判真，事件会被整体静默丢弃，违背
  // design D1「system 形态未分类事件 MUST 显示归一化 kind」不变式
  //（code-review item 6bce55dfed37）
  if (ev.type === 'system') return String(ev.subtype || 'system');
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

// stderr 错误词表（固化于常量，统一小写存储）：匹配时对行取小写后按词边界
// 正则判定（item 34cca47c42ac：旧 includes 子串匹配过宽，'errorhandler' 之类
// 含关键词字母的无关词与 'no error'/'0 errors' 这类否定/零计数表述都会误判为
// 错误行）。大小写不敏感——归档流实测存在 "ECONNREFUSED ..." 这类全大写错误行
//（spec 场景锚定其必须渲染为系统行），'refused' 因此保持子串匹配，词边界会把
// ECONNREFUSED 整词挡在门外。（code-review item 288bc70996d0：旧表混入大小写
// 敏感条目 'Error'/'FATAL' 是死重，大小写不敏感兜底本就覆盖。）
const STDERR_ERROR_KEYWORDS = ['error', 'traceback', 'failed', 'fatal', 'refused'];

// 否定/零计数限定：命中关键词前方紧邻这些限定（允许夹 ≤2 个修饰词）时不判错
//（'no error'、'0 errors'、'tests: 0 failed' 属「无错误」表述，判错是假噪音；
// 同行其他位置的真实命中照常判错，如 'fatal: no error handling'）
const STDERR_NON_ERROR_QUALIFIER = /(?:\b(?:no|zero|without)|\b0)\s+(?:\w+\s+){0,2}$/;

function stderrLooksError(line: string): boolean {
  const lower = line.toLowerCase();
  return STDERR_ERROR_KEYWORDS.some((kw) => stderrKeywordHit(lower, kw));
}

// 单关键词命中判定（item 34cca47c42ac）：默认词边界 + 复数后缀（'errors' 仍
// 命中 'error'，'errorhandler' 不再误中）；逐个命中位置检查前方是否为否定/
// 零计数限定，是则该次命中不计。'refused' 例外保持子串匹配，保住
// 'ECONNREFUSED' 这类整词内的真实错误信号。
function stderrKeywordHit(lower: string, kw: string): boolean {
  const re = new RegExp(kw === 'refused' ? kw : `\\b${kw}(?:s|es)?\\b`, 'g');
  let m: RegExpExecArray | null;
  while ((m = re.exec(lower)) !== null) {
    if (!STDERR_NON_ERROR_QUALIFIER.test(lower.slice(0, m.index))) return true;
  }
  return false;
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
    // 无 text 字段的普通对象 JSON 序列化展示（item 0f6b780b771c）：String() 兜底
    // 会产出字面 '[object Object]'，错误详情在卡片里不可读
    try {
      return JSON.stringify(c, null, 2);
    } catch {
      // 循环引用等序列化失败场景回落 String()
    }
  }
  return String(content);
}

// 终态事件 error/reason 字段文本化（item bec056a5ff10）：字段类型标注为 string，
// 但载荷实际来自外部事件流，非字符串（对象）经 String() 兜底会产出字面
// '[object Object]'；typeof 守卫后非字符串对象回落 JSON 序列化（先例：
// resultContentToText 的 item 0f6b780b771c）
function payloadText(v: unknown): string {
  if (typeof v === 'string') return v;
  if (v !== null && typeof v === 'object') {
    try {
      return JSON.stringify(v);
    } catch {
      // 循环引用等序列化失败场景不产出可读文本
      return '';
    }
  }
  return v ? String(v) : '';
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

// 用户侧中断哨兵（claude CLI 中断时插入的固定文本，可能随带 tool_result 的 user
// 消息或纯 user 消息出现）：渲染层两个 user 分支共用同一过滤判定
//（item 01781f3e4357）
const USER_INTERRUPT_SENTINEL = '[Request interrupted by user]';

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

// ── 稳定引用复用（code-review item 69a0024ae919）────────────────────
// 转换层每轮对全部已加载事件重建全新 ChatMessage 对象，SSE 每批增量到达时
// ClaudeOutputPane 的 useMemo 重算 → MessageItem 的 memo 浅比较因 message 引用
// 恒不等而失效，已加载窗口累积到数千条时流式期间每次增量都整列表重渲染（含
// Markdown 解析与代码高亮 diff）。此处按消息内在键缓存上一轮对象：本轮产出与
// 上轮同键消息逐字段浅等值时复用上轮引用，未变化消息的 memo 重新生效；只有
// 真正新增/被回填突变的消息（toolResult、耗时、任务状态、thinking 增量等）
// 保留新引用触发重渲染。等值判定保证语义等价才复用，键碰撞只会让判定失败
// 回落新对象，不影响正确性。缓存每轮按本轮产出整体重建（只含当前列表），
// 不跨轮累积；多个调用方（ClaudeOutputPane / SessionPanel）交替转换时会互踩
// 缓存键，代价仅是复用未命中，仍正确。
type MessageReferenceCache = Map<string, ChatMessage>;
// [fenix-ignore:e7b39aa4951c] 已知取舍非缺陷：复用前经 chatMessageShallowEqual 等值判定保证语义正确，且实测仅 ClaudeOutputPane/SessionPanel 两调用方，交替互踩缓存键的代价只是复用未命中（注释已载明）
let previousMessageCache: MessageReferenceCache = new Map();

// 字段值比较：引用相等直通过；toolResult 是转换层每轮新建的嵌套对象，按其
// 字段（content 恒为字符串、isError 布尔）浅比较一层。更深的嵌套（如不同
// 事件对象携带的 toolInput）引用不等即判不等，保守回落新引用。
function chatMessageFieldEqual(a: unknown, b: unknown): boolean {
  if (a === b) return true;
  if (a && b && typeof a === 'object' && typeof b === 'object') {
    const ra = a as Record<string, unknown>;
    const rb = b as Record<string, unknown>;
    const keys = Object.keys(ra);
    if (keys.length !== Object.keys(rb).length) return false;
    return keys.every((k) => ra[k] === rb[k]);
  }
  return false;
}

function chatMessageShallowEqual(a: ChatMessage, b: ChatMessage): boolean {
  const keys = Object.keys(a);
  if (keys.length !== Object.keys(b).length) return false;
  return keys.every((k) => chatMessageFieldEqual(a[k], b[k]));
}

// ── 消息内在键（定义本体自 messageKeys.ts 收敛至此，与其再导出保持单一来源）──
// node:test 直载 .ts 单测（tests/sessionEvents.test.mjs 等）按 ESM 解析本文件，
// 无扩展名运行时相对导入无法解析（ERR_MODULE_NOT_FOUND），故本模块不得新增
// 运行时相对导入；messageKeys.ts 改为再导出本实现，ClaudeMessageList 不受影响。

const toMessageKeyPart = (value: unknown): string | null => {
  if (typeof value !== 'string' && typeof value !== 'number') {
    return null;
  }

  const normalized = String(value).trim();
  return normalized.length > 0 ? normalized : null;
};

export const getIntrinsicMessageKey = (message: ChatMessage): string | null => {
  const candidates = [
    message.id,
    message.messageId,
    message.toolId,
    message.toolCallId,
    message.blobId,
    message.rowid,
    message.sequence,
  ];

  for (const candidate of candidates) {
    const keyPart = toMessageKeyPart(candidate);
    if (keyPart) {
      return `message-${message.type}-${keyPart}`;
    }
  }

  const timestamp = new Date(message.timestamp).getTime();
  if (!Number.isFinite(timestamp)) {
    return null;
  }

  // [fenix-ignore:13bb53979ae9] content 在本仓库类型即 string|undefined（types.ts），唯一生产方 runEventsToChatMessages 已把块数组规范化为逐条字符串消息，数组形态到不了本函数，空串仅对应无正文的 tool 等消息
  const contentPreview = typeof message.content === 'string' ? message.content.slice(0, 48) : '';
  const toolName = typeof message.toolName === 'string' ? message.toolName : '';
  // [fenix-ignore:0209ad3f1986] 撞键边界一句话：仅当七个身份字段全缺失且同毫秒同型同前 48 字符前缀才可能撞键，上游 claudecodeui 原样迁移；本仓库唯一调用方 ClaudeMessageList 的 messageKeyMap 已按出现序号 __n 消歧，裸用本函数仍可能撞键
  return `message-${message.type}-${timestamp}-${toolName}-${contentPreview}`;
};

function withStableMessageReferences(messages: ChatMessage[]): ChatMessage[] {
  const cache: MessageReferenceCache = new Map();
  const out = messages.map((msg) => {
    const key = getIntrinsicMessageKey(msg);
    if (key) {
      const prev = previousMessageCache.get(key);
      if (prev && chatMessageShallowEqual(prev, msg)) {
        cache.set(key, prev);
        return prev;
      }
      cache.set(key, msg);
    }
    return msg;
  });
  previousMessageCache = cache;
  return out;
}

export function runEventsToChatMessages(events: RunEvent[], showThinking: boolean = true): ChatMessage[] {
  return withStableMessageReferences(convertRunEvents(events, showThinking));
}

function convertRunEvents(events: RunEvent[], showThinking: boolean = true): ChatMessage[] {
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
    // 空文本短路（code-review item 657bb0c8610d）：无 currentThinking 时空片段
    // 直接跳过，不创建只有折叠头没有内容的空 thinking 条目，也不打断相邻工具
    // 调用的连续分组（与 text 分支仅在 trim 非空才入队的口径对齐）。只针对当前
    // 空片段，不改任何状态，后续非空片段到达仍会正常建条。
    if (!text.trim()) return;
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

  // user 事件文本提取 + 中断哨兵过滤单源化（code-review item 600bb3c13d77）：
  // tool_result 分支与普通用户消息分支共用同一判定，哨兵口径变化只改此处
  const pushUserTextIfVisible = (ev: RunEvent, timestamp: string | number) => {
    const text = userMessageText(ev);
    if (text && text !== USER_INTERRUPT_SENTINEL) {
      out.push({ type: 'user', content: text, timestamp });
    }
  };

  for (const ev of events) {
    if (!ev) continue;
    // 缺时间戳事件（框架 stderr/error 行、透传缺失 timestamp 的 CLI 事件）用
    // 固定哨兵 0：Date.now() 使每次重转换产出不同值 → getIntrinsicMessageKey
    // 回退键漂移，SSE 轮询下 React 反复卸载重挂对应消息；0 保证键稳定
    const timestamp = ev.timestamp || 0;

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
          } else {
            // 无匹配工具卡片（卡片被分页窗口截断、上游 tool_use_id 形态漂移）时
            // 兜底为独立条，不静默丢失（item ea030ea275c2）：与下方 task_started/
            // task_notification 分支同一「不静默丢失」口径；content 类型标注为
            // unknown，经 resultContentToText 文本化再截断。
            // isError 结果改推 error 行（消费端 MessageItem 渲染红色「错误」头，
            // 与上方终态 error 分支同形态），不以中性系统行掩盖失败状态（item
            // 4aef6dc57a79）；digest 为空时省略冒号尾巴（与 :624 task_started
            // 兜底同口径）
            const digest = truncateText(resultContentToText(result.content), 80);
            const text = digest ? `工具结果：${digest}` : '工具结果';
            if (result.isError) {
              flushThinking();
              out.push({ type: 'error', content: text, timestamp });
            } else {
              pushSystem(text, timestamp);
            }
          }
        }
        // tool_result 消息不再渲染文本行（除非另有文本内容）
        pushUserTextIfVisible(ev, timestamp);
        continue;
      }
      // 普通用户消息：优先字符串 content，回显事件（isReplay，块数组无顶层
      // content）经 userMessageText 提取 text 块
      pushUserTextIfVisible(ev, timestamp);
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
      const text = (payloadText(ev.error) || payloadText(ev.reason)).trim();
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
      const reason = payloadText(ev.reason);
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
    // 例外一（code-review item 3c0281837ea5）：旧形态 system 事件（type:"system" +
    // subtype 命中名单）携带非空字符串 content 时不在此吞掉——静默只针对零载荷
    // 心跳，带内容的旧形态事件落到下方 content 回退照旧渲染（该回退分支本就
    // 载明「旧形态 system 事件带字符串内容：直接渲染」，此早检此前与其矛盾）。
    // 例外二（code-review item 3dda29b6297c）：名单内事件带非空 error 载荷时
    // 渲染原因条，不整段吞掉——实测 backend superseded 事件携带门失败 error
    // 字段（runner.py 注释明确要求原因读侧可恢复），整吞会让死因不可见，
    // 违背 design 的 fail-open 原则（旧实现至少还渲染 [superseded] 占位行）。
    if (SILENT_KINDS.has(kind)) {
      const hasLegacyText =
        ev.type === 'system' && typeof ev.content === 'string' && ev.content.trim() !== '';
      if (!hasLegacyText) {
        // error 载荷可能为对象形态（见 payloadText 注释），与 :390 终态分支
        // 同一文本化口径，strField 会把非字符串 error 判空导致整段静默
        const errorPayload = payloadText(rec.error).trim();
        if (!errorPayload) continue;
        pushSystem(`系统事件（${kind}）：${truncateText(errorPayload, 80)}`, timestamp);
        continue;
      }
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
  // 估算前排序（item 253eea758896）：assistantTimes 按事件流序收集，流内时间戳
  // 非单调（回放拼接、生产者时钟抖动）时 find 取到数组序首个更大值而非最小更
  // 大值，(next - t) 偏大导致「已思考 N 秒」高估；排序消除对流序单调的隐式假设
  assistantTimes.sort((a, b) => a - b);
  // 同事件工具观测耗时汇总（item 5828e59782f2）：thinking 与同消息的 tool_use
  // 块共享同一事件 timestamp，下方差值会把工具执行耗时计入（工具耗时长时
  // 「已思考 N 秒」显著夸大）。按 timestamp 汇总心跳观测到的工具耗时，从差值
  // 中扣除；无心跳覆盖的工具不扣（保留 design D4 原口径）。
  const toolElapsedAtTime = new Map<number, number>();
  for (const msg of out) {
    if (typeof msg.toolElapsedSeconds !== 'number') continue;
    const t = parseTimestampMs(msg.timestamp);
    if (t === null || t <= 0) continue;
    toolElapsedAtTime.set(t, (toolElapsedAtTime.get(t) ?? 0) + msg.toolElapsedSeconds);
  }
  const estimatedAtTime = new Set<number>();
  for (const msg of out) {
    if (!msg.isThinking) continue;
    msg.thinkingPreview = thinkingPreviewText(String(msg.content || ''));
    if (assistantTimes.length < 2) continue;
    const t = parseTimestampMs(msg.timestamp);
    // 哨兵 0（缺时间戳）会与下一个 assistant 事件产生 epoch 起的荒谬差值 → 跳过估算
    if (t === null || t <= 0) continue;
    // 同一 timestamp 只估算一次（item c2d1f65c1076）：同事件内多条 thinking（块序
    // 列 thinking→text→thinking 经 flushThinking 产出两条同 timestamp 消息）或相
    // 邻 assistant 事件 timestamp 相同（秒级粒度）时，逐条独立估算会把整段差值
    // 重复计入；同刻后续条目不写时长，折叠头回退「已思考数秒」
    if (estimatedAtTime.has(t)) continue;
    estimatedAtTime.add(t);
    const next = assistantTimes.find((x) => x > t);
    if (next === undefined) continue;
    // 扣除同事件工具的观测耗时后再估算（item 5828e59782f2）；扣除后非正 → 不写
    // 字段，折叠头回退「已思考数秒」
    const seconds = Math.round((next - t) / 1000 - (toolElapsedAtTime.get(t) ?? 0));
    if (seconds > 0) msg.thinkingSeconds = seconds;
  }

  return out;
}
