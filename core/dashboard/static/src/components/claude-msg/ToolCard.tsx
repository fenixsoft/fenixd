// 单条工具调用卡片 —— 迁移自 claudecodeui 的工具展示视觉（ToolGroupContainer/ToolErrorDisplay），
// 以通用折叠形式呈现工具名 + 输入摘要 + 结果（原项目的 40+ 工具专属渲染器不在迁移范围）。
// add-run-record-readability 2.3：摘要优先输入 description、右侧标注心跳观测耗时。
import { useMemo, useState } from 'react';

import type { ChatMessage } from './types';
import { formatElapsedSeconds, parseToolInput, taskStatusDotClass, toolCardPreview, toolIcon } from './toolGrouping';

function prettyJson(value: unknown): string {
  if (typeof value === 'string') return value;
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
}

export default function ToolCard({ message }: { message: ChatMessage }) {
  const [expanded, setExpanded] = useState(false);
  const toolName = message.toolName || 'UnknownTool';
  const parsedInput = useMemo(() => parseToolInput(message.toolInput), [message.toolInput]);
  // BUG-01 修复：task_started 回填的 taskDescription 优先作卡片预览
  const preview = useMemo(() => toolCardPreview(message), [message]);
  const elapsedSeconds =
    typeof message.toolElapsedSeconds === 'number' ? message.toolElapsedSeconds : null;
  const taskSummary = typeof message.taskSummary === 'string' ? message.taskSummary.trim() : '';
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
          {toolIcon(toolName)}
        </span>
        <span className="min-w-0 flex-shrink-0 text-xs font-medium text-foreground">{toolName}</span>
        {preview && (
          <span className="min-w-0 truncate font-mono text-xs text-muted-foreground">{preview}</span>
        )}
        {elapsedSeconds != null && (
          <span
            className="ml-auto flex-shrink-0 text-[10px] tabular-nums text-muted-foreground"
            title="工具耗时（按心跳观测估算）"
          >
            {formatElapsedSeconds(elapsedSeconds)}
          </span>
        )}
      </button>

      {/* task_notification 回填的任务终态摘要（BUG-01 修复）：折叠态常显，
          状态点配色经 taskStatusDotClass 与 MessageItem 任务通知行同源
          （completed 绿 / 其余琥珀，item 1dd4d551b484） */}
      {taskSummary && (
        <div className="mt-0.5 flex items-center gap-1.5 pl-6 text-xs text-muted-foreground">
          <span
            className={`inline-block h-1.5 w-1.5 flex-shrink-0 rounded-full ${taskStatusDotClass(message.taskStatus)}`}
          />
          <span className="min-w-0 truncate">{taskSummary}</span>
        </div>
      )}

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
