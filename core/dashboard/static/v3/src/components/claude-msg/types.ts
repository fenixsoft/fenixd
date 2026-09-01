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
  [key: string]: unknown;
}
