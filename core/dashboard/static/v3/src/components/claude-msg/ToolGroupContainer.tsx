// 连续同类工具调用合并折叠 —— 迁移自 claudecodeui ToolGroupContainer.tsx（精简版）：
// 去 getToolConfig 依赖，图标/标签取自 ToolCard 的映射逻辑。
import { useMemo, useState } from 'react';

import type { ChatMessage } from './types';
import type { ToolGroupItem } from './toolGrouping';
import MessageItem from './MessageItem';
import ToolCard from './ToolCard';

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

function parseToolInput(toolInput: unknown): unknown {
  if (typeof toolInput !== 'string') {
    return toolInput;
  }
  try {
    return JSON.parse(toolInput);
  } catch {
    return toolInput;
  }
}

function summarize(value: unknown): string {
  if (value == null) return '';
  if (typeof value === 'string') return value;
  if (typeof value === 'number' || typeof value === 'boolean') return String(value);
  if (Array.isArray(value)) return value.slice(0, 3).map((v) => summarize(v)).join(', ');
  if (typeof value === 'object') {
    const entries = Object.entries(value as Record<string, unknown>);
    const primaryKeys = ['command', 'file_path', 'path', 'pattern', 'url', 'query', 'description', 'prompt'];
    const preferred = primaryKeys
      .map((k) => entries.find(([key]) => key === k))
      .filter((entry) => entry != null)
      .slice(0, 2)
      .map(([, v]) => summarize(v));
    if (preferred.length > 0) return preferred.join(' | ');
    return entries.slice(0, 2).map(([k, v]) => `${k}=${summarize(v)}`).join(' ');
  }
  return String(value);
}

interface ToolGroupContainerProps {
  group: ToolGroupItem;
  prevMessage: ChatMessage | null;
  getMessageKey: (message: ChatMessage) => string;
  showThinking?: boolean;
}

export default function ToolGroupContainer({
  group,
  prevMessage,
  getMessageKey,
  showThinking = false,
}: ToolGroupContainerProps) {
  const [isExpanded, setIsExpanded] = useState(false);
  const label = group.toolName;
  const icon = TOOL_ICONS[group.toolName] || group.toolName.slice(0, 1).toUpperCase();

  const preview = useMemo(() => {
    const visiblePreviews = group.messages
      .slice(0, 2)
      .map((m) => summarize(parseToolInput(m.toolInput)))
      .filter(Boolean);

    const extraCount = group.messages.length - visiblePreviews.length;
    const previewText = visiblePreviews.join(', ');

    if (!previewText) {
      return extraCount > 0 ? `+${extraCount} more` : '';
    }

    return extraCount > 0 ? `${previewText}, +${extraCount} more` : previewText;
  }, [group.messages]);

  return (
    <div className="chat-message tool px-3 sm:px-0">
      <button
        type="button"
        className="group flex w-full items-center gap-2 border-l-2 border-border rounded-r-md bg-muted/25 px-3 py-2 text-left transition-colors hover:bg-muted/40"
        onClick={() => setIsExpanded((current) => !current)}
        aria-expanded={isExpanded}
      >
        <svg
          className={`h-3.5 w-3.5 flex-shrink-0 text-muted-foreground transition-transform ${isExpanded ? 'rotate-90' : ''}`}
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
          aria-hidden
        >
          <path d="M9 18l6-6-6-6" />
        </svg>
        <span className="flex h-5 w-5 flex-shrink-0 items-center justify-center rounded bg-background/80 text-xs font-medium">
          {icon}
        </span>
        <span className="min-w-0 flex-shrink-0 text-xs font-medium text-foreground">{label}</span>
        <span className="flex-shrink-0 rounded-full bg-muted px-1.5 py-0.5 text-[10px] font-medium text-muted-foreground">
          x{group.messages.length}
        </span>
        {preview && (
          <>
            <span className="text-[10px] text-muted-foreground/40">/</span>
            <span className="min-w-0 truncate font-mono text-xs text-muted-foreground">{preview}</span>
          </>
        )}
      </button>

      {isExpanded && (
        <div className="mt-2 space-y-3 sm:space-y-4">
          {group.messages.map((message, index) => (
            <MessageItem
              key={getMessageKey(message)}
              message={message}
              prevMessage={index > 0 ? group.messages[index - 1] : prevMessage}
              showThinking={showThinking}
            />
          ))}
        </div>
      )}
    </div>
  );
}
