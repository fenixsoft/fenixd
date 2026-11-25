// 文案经 useIntl/intlText（i18n 修复轮 batch-G：本文件静态中文文案迁 i18n 目录）
// 单条工具调用卡片 —— 迁移自 claudecodeui 的工具展示视觉（ToolGroupContainer/ToolErrorDisplay），
// 以通用折叠形式呈现工具名 + 输入摘要 + 结果（原项目的 40+ 工具专属渲染器不在迁移范围）。
// add-run-record-readability 2.3：摘要优先输入 description、右侧标注心跳观测耗时。
import { useMemo, useState } from 'react';
import { useIntl } from '@umijs/max';

import type { ChatMessage } from './types';
import { formatElapsedSeconds, parseToolInput, prettyJson, taskStatusDotClass, toolCardPreview, toolIcon } from './toolGrouping';

// 展开态结果渲染上限（code-review item cf3ab312e314）：resultContentToText 对
// tool_result 文本化不做截断，Bash/Read 类工具可产出数十万字符结果，整段注入
// <pre> 会触发同步布局，消息列表累积多条此类卡片时滚动与重渲染明显卡顿。
// 无同类先例（既有截断口径均为摘要 80 字上限，不适用正文展示），取 suggestion
// 的 64 KiB。仅展示层截断：数据流与组件外消费不受影响（本卡片无复制按钮）。
const RESULT_RENDER_LIMIT = 64 * 1024;

export default function ToolCard({ message }: { message: ChatMessage }) {
  const [expanded, setExpanded] = useState(false);
  const intl = useIntl();
  const toolName = message.toolName || 'UnknownTool';
  const parsedInput = useMemo(() => parseToolInput(message.toolInput), [message.toolInput]);
  // BUG-01 修复：task_started 回填的 taskDescription 优先作卡片预览
  const preview = useMemo(() => toolCardPreview(message), [message]);
  const elapsedSeconds =
    typeof message.toolElapsedSeconds === 'number' ? message.toolElapsedSeconds : null;
  const taskSummary = typeof message.taskSummary === 'string' ? message.taskSummary.trim() : '';
  const isError = Boolean(message.toolResult?.isError);
  const hasDetail = message.toolInput != null || message.toolResult != null;
  // 结果正文收敛一次（字符串原样、其余 prettyJson 兜底），供截断判定与渲染共用；
  // memo 避免重渲染时对超大内容反复 JSON 序列化
  const resultText = useMemo(() => {
    const result = message.toolResult;
    if (result == null) return '';
    return typeof result.content === 'string'
      ? result.content
      : prettyJson(result.content ?? result);
  }, [message.toolResult]);
  const resultTruncated = resultText.length > RESULT_RENDER_LIMIT;
  const resultShown = resultTruncated ? resultText.slice(0, RESULT_RENDER_LIMIT) : resultText;

  return (
    <div className="px-3 py-0.5">
      {/* 无输入与结果时按钮不可交互（item 06edb928e359）：disabled 阻止聚焦与
          点击，hover 变色与 aria-expanded 一并去除，避免「可点但展开区永不出现」
          的假交互样式误导鼠标与键盘用户 */}
      <button
        type="button"
        disabled={!hasDetail}
        className={`group flex w-full items-center gap-2 border-l-2 rounded-r-md px-3 py-2 text-left transition-colors ${
          isError
            ? `border-destructive/60 bg-destructive/5 ${hasDetail ? 'hover:bg-destructive/10' : ''}`
            : `border-border bg-muted/25 ${hasDetail ? 'hover:bg-muted/40' : ''}`
        }`}
        onClick={() => hasDetail && setExpanded((current) => !current)}
        aria-expanded={hasDetail ? expanded : undefined}
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
            title={intl.formatMessage({ id: 'claudeMsg.toolCard.elapsedHint' })}
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
              <div className="px-3 pt-2 text-[10px] font-medium text-muted-foreground">
                {intl.formatMessage({ id: 'claudeMsg.toolCard.inputLabel' })}
              </div>
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
                {isError
                  ? intl.formatMessage({ id: 'claudeMsg.toolCard.resultError' })
                  : intl.formatMessage({ id: 'claudeMsg.toolCard.result' })}
                {resultTruncated && (
                  <span className="font-normal">
                    {' '}
                    {intl.formatMessage(
                      { id: 'claudeMsg.toolCard.resultTruncated' },
                      { count: resultText.length },
                    )}
                  </span>
                )}
              </div>
              <pre className="overflow-x-auto p-3 text-xs leading-relaxed">
                <code className="whitespace-pre-wrap font-mono text-foreground">{resultShown}</code>
              </pre>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
