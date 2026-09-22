// ChatMessage 数据形态 —— 迁移自 claudecodeui（src/components/chat/types/types.ts），
// 仅保留本控件渲染所需字段。type: 'user' | 'assistant' | 'system' | 'error' | 'tool'

export interface ToolResult {
  content?: unknown;
  isError?: boolean;
  timestamp?: string | number | Date;
  [key: string]: unknown;
}

export interface ChatMessage {
  type: string;
  content?: string;
  displayText?: string;
  timestamp: string | number | Date;
  reasoning?: string;
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
  /** 防御标记：被静默的消息不渲染且不打断同类连续分组（2.2） */
  rendersNothing?: boolean;
  [key: string]: unknown;
}
