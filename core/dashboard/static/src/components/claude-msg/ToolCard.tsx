// 单条工具调用卡片 —— 迁移自 claudecodeui 的工具展示视觉（ToolGroupContainer/ToolErrorDisplay），
// 以通用折叠形式呈现工具名 + 输入摘要 + 结果（原项目的 40+ 工具专属渲染器不在迁移范围）。
import { useMemo, useState } from 'react';

import type { ChatMessage } from './types';

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

function prettyJson(value: unknown): string {
  if (typeof value === 'string') return value;
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
}

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

export default function ToolCard({ message }: { message: ChatMessage }) {
  const [expanded, setExpanded] = useState(false);
  const toolName = message.toolName || 'UnknownTool';
  const parsedInput = useMemo(() => parseToolInput(message.toolInput), [message.toolInput]);
  const preview = useMemo(() => summarize(parsedInput), [parsedInput]);
  const isError = Boolean(message.toolResult?.isError);
  const hasDetail = message.toolInput != null || message.toolResult != null;

  return (
    <div className="px-3 py-0.5">
      <button
        type="button"
        className={`group flex w-full items-center gap-2 border-l-2 rounded-r-md px-3 py-2 text-left transition-colors ${
          isError
            ? 'border-destructive/60 bg-destructive/5 hover:bg-destructive/10'
            : 'border-border bg-muted/25 hover:bg-muted/40'
        }`}
        onClick={() => hasDetail && setExpanded((current) => !current)}
        aria-expanded={expanded}
      >
        <span className="flex h-5 w-5 flex-shrink-0 items-center justify-center rounded bg-background/80 text-xs font-medium">
          {TOOL_ICONS[toolName] || toolName.slice(0, 1).toUpperCase()}
        </span>
        <span className="min-w-0 flex-shrink-0 text-xs font-medium text-foreground">{toolName}</span>
        {preview && (
          <span className="min-w-0 truncate font-mono text-xs text-muted-foreground">{preview}</span>
        )}
      </button>

      {expanded && (
        <div className="mt-1 space-y-2 pl-5">
          {message.toolInput != null && (
            <div className="overflow-hidden rounded-lg border border-border bg-muted/50">
              <div className="px-3 pt-2 text-[10px] font-medium text-muted-foreground">输入</div>
              <pre className="overflow-x-auto p-3 text-xs leading-relaxed">
                <code className="whitespace-pre font-mono text-foreground">{prettyJson(parsedInput)}</code>
              </pre>
            </div>
          )}
          {message.toolResult != null && (
            <div
              className={`overflow-hidden rounded-lg border ${
                isError ? 'border-destructive/40 bg-destructive/5' : 'border-border bg-muted/50'
              }`}
            >
              <div className="px-3 pt-2 text-[10px] font-medium text-muted-foreground">
                {isError ? '结果（错误）' : '结果'}
              </div>
              <pre className="overflow-x-auto p-3 text-xs leading-relaxed">
                <code className="whitespace-pre-wrap font-mono text-foreground">
                  {typeof message.toolResult.content === 'string'
                    ? message.toolResult.content
                    : prettyJson(message.toolResult.content ?? message.toolResult)}
                </code>
              </pre>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
