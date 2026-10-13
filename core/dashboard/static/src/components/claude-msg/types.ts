// ChatMessage 数据形态 —— 迁移自 claudecodeui（src/components/chat/types/types.ts），
// 仅保留本控件渲染所需字段。type: 'user' | 'assistant' | 'system' | 'error' | 'tool'

export interface ToolResult {
  content?: unknown;
  isError?: boolean;
  timestamp?: string | number | Date;
  // 宽松索引签名系有意保留（code-review item 04b23cd6fe52，取舍说明同 ChatMessage）：
  // 容纳后端附加字段；代价是拼错的字段名不会编译报错，读取端需对索引字段做存在性防御
  [key: string]: unknown;
}

export type ChatMessageType = 'user' | 'assistant' | 'system' | 'error' | 'tool';

export interface ChatMessage {
  type: ChatMessageType;
  content?: string;
  displayText?: string;
  timestamp: string | number | Date;
  isThinking?: boolean;
  isStreaming?: boolean;
  isToolUse?: boolean;
  toolName?: string;
  toolInput?: unknown;
  toolResult?: ToolResult | null;
  toolId?: string;
  /** tool_progress 心跳观测到的最大耗时（秒），add-run-record-readability 1.4；
   * 无心跳覆盖时不写字段、卡片不渲染耗时 */
  toolElapsedSeconds?: number;
  /** task_started 凭 tool_use_id 回填的任务意图描述（1.3） */
  taskDescription?: string;
  /** task_notification 凭 tool_use_id 回填的任务终态与摘要（1.3） */
  taskStatus?: string;
  taskSummary?: string;
  /** thinking 折叠头：相邻 assistant 事件 timestamp 差估算时长（秒）与首行预览（3.1）；
   * 估算不可用时缺省，折叠头回退「已思考数秒」 */
  thinkingSeconds?: number;
  thinkingPreview?: string;
  /** 无正文兜底强制渲染标记（3.2）：showThinking=false 但全流无非空正文时，
   * 兜底产出的 thinking 消息带此标记；渲染层（MessageItem 隐藏判定与
   * toolGrouping 分组判定）据此豁免隐藏——缺了它兜底会在渲染层被击穿
   *（verification BUG-02） */
  thinkingForced?: boolean;
  // 宽松索引签名系有意保留（code-review item 04b23cd6fe52）：数据形态迁移自
  // claudecodeui，需容纳上游/后端附加字段，故不收窄为 Record 交叉类型；代价是
  // 写入拼错的字段名（如 toolElapseSeconds ≠ toolElapsedSeconds）编译期不报错、
  // 读取端拿到 undefined 只表现为功能静默缺失——新增字段必须落上方具名声明，
  // 读取端对仅经索引访问的字段做存在性防御
  [key: string]: unknown;
}
