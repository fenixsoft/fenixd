// 连续同类工具调用合并折叠 —— 迁移自 claudecodeui ToolGroupContainer.tsx（精简版）：
// 去 getToolConfig 依赖，图标/标签取自 ToolCard 的映射逻辑。
// add-run-record-readability 2.1：同类连续组渲染语义化组标题；编辑组收起态按
// 首现顺序去重展示文件路径。
import { useMemo, useState } from 'react';

import type { ChatMessage } from './types';
import type { ToolClass, ToolGroupItem } from './toolGrouping';
import { describeToolInput, editFilePaths } from './toolGrouping';
import MessageItem from './MessageItem';
import ToolCard from './ToolCard';

const CLASS_ICONS: Record<ToolClass, string> = {
  read: '📄',
  bash: '$',
  edit: '✏️',
};

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
  // 同类组用语义化标题（组名已含计数，省去 xN 徽标）；同名连续组沿用工具名
  const label = group.groupTitle || group.toolName;
  const icon = group.groupKind
    ? CLASS_ICONS[group.groupKind]
    : TOOL_ICONS[group.toolName] || group.toolName.slice(0, 1).toUpperCase();

  const preview = useMemo(() => {
    // 编辑组收起态：按首现顺序去重展示文件路径（design D2）
    if (group.groupKind === 'edit') {
      const paths = editFilePaths(group.messages);
      const visible = paths.slice(0, 3);
      const text = visible.join(', ');
      if (!text) return '';
      const extra = paths.length - visible.length;
      return extra > 0 ? `${text}, +${extra} 个文件` : text;
    }
    const visiblePreviews = group.messages
      .slice(0, 2)
      .map((m) => describeToolInput(m.toolInput))
      .filter(Boolean);

    const extraCount = group.messages.length - visiblePreviews.length;
    const previewText = visiblePreviews.join(', ');

    if (!previewText) {
      return extraCount > 0 ? `+${extraCount} more` : '';
    }

    return extraCount > 0 ? `${previewText}, +${extraCount} more` : previewText;
  }, [group.messages, group.groupKind]);

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
        {!group.groupTitle && (
          <span className="flex-shrink-0 rounded-full bg-muted px-1.5 py-0.5 text-[10px] font-medium text-muted-foreground">
            x{group.messages.length}
          </span>
        )}
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
