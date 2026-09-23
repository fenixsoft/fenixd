// 消息分组与工具卡片纯工具函数 —— 迁移自 claudecodeui toolGrouping.ts，
// add-run-record-readability 起同时承载卡片摘要/耗时/同类聚合的纯逻辑
//（node:test 直载 .ts 单测覆盖，见 tests/toolGrouping.test.mjs）。

import type { ChatMessage } from './types';

export const TOOL_GROUP_THRESHOLD = 2;

// ── 工具输入解析与摘要（自 ToolCard/ToolGroupContainer 收敛至此，单测可达） ──

export function parseToolInput(toolInput: unknown): unknown {
  if (typeof toolInput !== 'string') {
    return toolInput;
  }
  try {
    return JSON.parse(toolInput);
  } catch {
    return toolInput;
  }
}

function summarize(value: unknown, depth = 0): string {
  if (value == null) return '';
  if (typeof value === 'string') return value;
  if (typeof value === 'number' || typeof value === 'boolean') return String(value);
  if (Array.isArray(value)) return value.slice(0, 3).map((v) => summarize(v, depth + 1)).join(', ');
  if (typeof value === 'object') {
    const entries = Object.entries(value as Record<string, unknown>);
    const primaryKeys = ['command', 'file_path', 'path', 'pattern', 'url', 'query', 'description', 'prompt'];
    const preferred = primaryKeys
      .map((k) => entries.find(([key]) => key === k))
      .filter((entry) => entry != null)
      .slice(0, 2)
      .map(([, v]) => summarize(v, depth + 1));
    if (preferred.length > 0) return preferred.join(' | ');
    return entries.slice(0, 2).map(([k, v]) => `${k}=${summarize(v, depth + 1)}`).join(' ');
  }
  return String(value);
}

// 卡片语义摘要（design D3）：优先取工具输入的 description 字段（agent 写的意图
// 描述）；缺失时按工具类型回落既有 summarize 兜底（Bash 用 command 原文、文件类
// 工具用 file_path/path，其余沿用 primaryKeys）。
export function describeToolInput(toolInput: unknown): string {
  const parsed = parseToolInput(toolInput);
  if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) {
    const description = (parsed as Record<string, unknown>).description;
    if (typeof description === 'string' && description.trim()) {
      return description.trim();
    }
  }
  return summarize(parsed);
}

// 卡片预览（verification BUG-01 修复）：task_started 凭 tool_use_id 回填的
// taskDescription 是任务意图的权威描述，优先于工具输入摘要（Task 工具输入只
// 有 prompt 长文）；无回填时回落 describeToolInput 既有兜底。
export function toolCardPreview(message: ChatMessage): string {
  const backfilled =
    typeof message.taskDescription === 'string' ? message.taskDescription.trim() : '';
  return backfilled || describeToolInput(message.toolInput);
}

// 工具耗时标注格式（design D3）：秒 → 「XmYs」；非法/负值返回空串（调用方
// 无值不渲染）。
export function formatElapsedSeconds(seconds: number): string {
  if (!Number.isFinite(seconds) || seconds < 0) return '';
  const total = Math.round(seconds);
  const m = Math.floor(total / 60);
  const s = total % 60;
  if (m === 0) return `${s}s`;
  return `${m}m${s}s`;
}

// ── 同类连续聚合（design D2） ────────────────────────────────────────

// 工具→类映射：查阅=Read/Grep/Glob、命令=Bash、编辑=Edit/Write；
// 不在映射内的工具沿用既有同名连续分组逻辑。
export type ToolClass = 'read' | 'bash' | 'edit';

const TOOL_CLASS_BY_NAME: Record<string, ToolClass> = {
  Read: 'read',
  Grep: 'read',
  Glob: 'read',
  Bash: 'bash',
  Edit: 'edit',
  Write: 'edit',
};

export function toolClassOf(toolName: string): ToolClass | null {
  return TOOL_CLASS_BY_NAME[toolName] ?? null;
}

// 组标题：同类连续组按类命名并带计数
export function toolGroupTitle(kind: ToolClass, count: number): string {
  if (kind === 'read') return `查阅 ${count} 个文件/模式`;
  if (kind === 'bash') return `执行 ${count} 条命令`;
  return `编辑 ${count} 个文件`;
}

// 编辑组收起态：组内文件路径按首现顺序去重
export function editFilePaths(messages: ChatMessage[]): string[] {
  const seen = new Set<string>();
  const paths: string[] = [];
  for (const message of messages) {
    const input = parseToolInput(message.toolInput);
    if (!input || typeof input !== 'object' || Array.isArray(input)) continue;
    const rec = input as Record<string, unknown>;
    // file_path/path 回退链展开（项目清单禁嵌套三元，code-review item 4ac183111d64）
    let p = '';
    if (typeof rec.file_path === 'string') {
      p = rec.file_path;
    } else if (typeof rec.path === 'string') {
      p = rec.path;
    }
    if (p && !seen.has(p)) {
      seen.add(p);
      paths.push(p);
    }
  }
  return paths;
}

export interface ToolGroupItem {
  _isGroup: true;
  toolName: string;
  /** 同类聚合组的类（read/bash/edit）；同名连续组不设 */
  groupKind?: ToolClass;
  /** 语义化组标题（如「执行 5 条命令」）；未设时展示沿用 toolName */
  groupTitle?: string;
  messages: ChatMessage[];
  timestamp: ChatMessage['timestamp'];
}

export type MessageListItem = ChatMessage | ToolGroupItem;

export function isToolGroupItem(item: MessageListItem): item is ToolGroupItem {
  return '_isGroup' in item && (item as ToolGroupItem)._isGroup === true;
}

function isGroupableToolMessage(message: ChatMessage): message is ChatMessage & { toolName: string } {
  return Boolean(message.isToolUse && message.toolName && !message.isSubagentContainer);
}

// thinking 隐藏判定（唯一权威口径，code-review item 2faec963d2ea）：开关关闭
// 且非兜底强制渲染的 thinking 消息不可见。渲染层（MessageItem 隐藏分支）与
// 分组层（隐藏消息不打断同类连续分组）共用本谓词——此前两处各自内联同一
// 不变式（`!thinkingForced` vs `thinkingForced !== true`），单侧改动就会产出
// 「隐藏但破坏分组」或「可见却被分组」的不一致。
export function isThinkingHidden(message: ChatMessage, showThinking: boolean): boolean {
  // 兜底强制渲染的 thinking（thinkingForced）真实可见，须照常打断同类连续分组。
  // （静默事件在 runEventsToChatMessages 即不产出条目，此处不再保留
  // rendersNothing 防御标记分支——全仓无赋值点的死标记只会误导读者，
  // code-review item fcd96aabd6d9）
  return Boolean(message.isThinking && !showThinking && message.thinkingForced !== true);
}

// 任务通知状态点配色（唯一权威口径，code-review item 1dd4d551b484）：
// MessageItem 任务通知行与 ToolCard 终态摘要行共用，completed 绿 / 其余琥珀，
// 色彩映射单源持有防两处视觉漂移（如未来 failed 独立配色只改这里）。
export function taskStatusDotClass(status?: string): string {
  return status === 'completed' ? 'bg-green-400' : 'bg-amber-400';
}

// 工具图标映射（唯一权威口径，code-review item 00df5be42e62）：ToolCard 卡片
// 与 ToolGroupContainer 组头共用，防两处复制粘贴双写漂移（同一工具在卡片与
// 组头显示不同图标）。未命中回落工具名首字母大写。
const TOOL_ICONS: Record<string, string> = {
  Bash: '$',
  Read: '📄',
  Write: '✏️',
  Edit: '✏️',
  Grep: '🔍',
  Glob: '🔍',
  WebFetch: '🌐',
  WebSearch: '🌐',
  TodoWrite: '☑️',
  Task: '🤖',
};

export function toolIcon(toolName: string): string {
  return TOOL_ICONS[toolName] || toolName.slice(0, 1).toUpperCase();
}

// 同组判定：同类（read/bash/edit）连续即可成组；类外工具沿用同名连续
function sameGrouping(firstToolName: string, firstClass: ToolClass | null, candidate: ChatMessage & { toolName: string }): boolean {
  if (firstClass != null) {
    return toolClassOf(candidate.toolName) === firstClass;
  }
  return candidate.toolName === firstToolName;
}

export function groupConsecutiveTools(
  messages: ChatMessage[],
  showThinking: boolean = true,
): MessageListItem[] {
  const items: MessageListItem[] = [];
  let index = 0;

  while (index < messages.length) {
    const message = messages[index];

    if (!isGroupableToolMessage(message)) {
      items.push(message);
      index += 1;
      continue;
    }

    const firstClass = toolClassOf(message.toolName);
    const run: ChatMessage[] = [message];
    let nextIndex = index + 1;

    while (nextIndex < messages.length) {
      const candidate = messages[nextIndex];

      if (isThinkingHidden(candidate, showThinking)) {
        nextIndex += 1;
        continue;
      }

      if (isGroupableToolMessage(candidate) && sameGrouping(message.toolName, firstClass, candidate)) {
        run.push(candidate);
        nextIndex += 1;
        continue;
      }

      break;
    }

    if (run.length >= TOOL_GROUP_THRESHOLD) {
      items.push({
        _isGroup: true,
        toolName: message.toolName,
        groupKind: firstClass ?? undefined,
        groupTitle: firstClass ? toolGroupTitle(firstClass, run.length) : undefined,
        messages: run,
        timestamp: message.timestamp,
      });
    } else {
      items.push(...run);
    }

    index = nextIndex;
  }

  return items;
}
