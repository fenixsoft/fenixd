// 单条消息渲染 —— 迁移自 claudecodeui MessageComponent.tsx（精简版）：
// - 去 i18n / provider logo / 语音 / 附件（图片、文件）/ 交互式 prompt
// - 头像用固定字符（Claude / U / 工具 / 错误）
// - thinking 折叠用本目录 Reasoning（无 radix 依赖）
import { memo, useMemo } from 'react';

import type { ChatMessage } from './types';
import { formatUsageLimitText } from './chatFormatting';
import { Markdown } from './Markdown';
import { Reasoning } from './Reasoning';
import ClaudeLogo from './ClaudeLogo';
import ToolCard from './ToolCard';

function MessageCopyControl({ content }: { content: string }) {
  return (
    <button
      type="button"
      className="text-muted-foreground opacity-0 transition-opacity group-hover:opacity-100"
      title="复制"
      onClick={() => navigator.clipboard?.writeText(content).catch(() => {})}
    >
      复制
    </button>
  );
}

type MessageItemProps = {
  message: ChatMessage;
  prevMessage: ChatMessage | null;
  showThinking?: boolean;
};

const MessageItem = memo(({ message, prevMessage, showThinking = false }: MessageItemProps) => {
  const isGrouped =
    prevMessage &&
    prevMessage.type === message.type &&
    ['assistant', 'user', 'tool', 'error', 'system'].includes(message.type);

  const formattedMessageContent = useMemo(
    () => formatUsageLimitText(String(message.content || '')),
    [message.content],
  );

  const formattedTime = useMemo(
    () => new Date(message.timestamp).toLocaleTimeString(),
    [message.timestamp],
  );
  const shouldHideThinkingMessage = Boolean(message.isThinking && !showThinking);

  if (shouldHideThinkingMessage) {
    return null;
  }

  return (
    <div
      className={`chat-message ${message.type} ${isGrouped ? 'grouped' : ''} ${
        message.type === 'user' ? 'flex justify-end px-1 sm:px-0' : 'px-1 sm:px-0'
      }`}
    >
      {message.type === 'user' ? (
        <div className="flex w-full items-end space-x-0 sm:w-auto sm:max-w-[85%]">
          <div className="flex min-w-0 flex-1 flex-col items-end gap-2 sm:flex-initial">
            <div className="group max-w-full rounded-2xl rounded-br-md border border-border/60 bg-muted/60 px-3 py-2 text-foreground shadow-sm">
              <div dir="auto" className="break-words font-serif text-sm">
                <Markdown breaks className="prose prose-sm max-w-none font-serif">
                  {message.content}
                </Markdown>
              </div>
              <div className="mt-1 flex items-center justify-end gap-1 text-xs text-muted-foreground">
                {String(message.content || '').trim().length > 0 && (
                  <MessageCopyControl content={String(message.content || '')} />
                )}
                <span>{formattedTime}</span>
              </div>
            </div>
          </div>
          {!isGrouped && (
            <div className="hidden h-8 w-8 flex-shrink-0 items-center justify-center rounded-full bg-primary text-sm text-primary-foreground sm:flex">
              U
            </div>
          )}
        </div>
      ) : message.isTaskNotification ? (
        <div className="w-full">
          <div className="flex items-center gap-2 py-0.5">
            <span
              className={`inline-block h-1.5 w-1.5 flex-shrink-0 rounded-full ${
                message.taskStatus === 'completed' ? 'bg-green-400' : 'bg-amber-400'
              }`}
            />
            <span className="text-xs text-muted-foreground">{message.content}</span>
          </div>
        </div>
      ) : (
        <div className="w-full">
          {!isGrouped && (
            <div className="mb-2 flex items-center space-x-3">
              {message.type === 'error' ? (
                <div className="flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-full bg-destructive text-sm text-white">
                  !
                </div>
              ) : message.type === 'tool' ? (
                <div className="flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-full bg-gray-600 text-sm text-white">
                  🔧
                </div>
              ) : message.type === 'system' ? (
                <div className="flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-full bg-gray-400 text-sm text-white">
                  ⚙
                </div>
              ) : (
                <div className="flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-full p-0.5">
                  <ClaudeLogo className="h-full w-full" />
                </div>
              )}
              <div className="whitespace-nowrap text-sm font-medium text-foreground">
                {message.type === 'error'
                  ? '错误'
                  : message.type === 'tool'
                    ? '工具'
                    : message.type === 'system'
                      ? '系统'
                      : 'Claude'}
              </div>
              <span className="ml-auto text-[11px] text-gray-400">{formattedTime}</span>
            </div>
          )}

          <div className="w-full">
            {message.isToolUse ? (
              <>
                {message.displayText && (
                  <Markdown className="prose prose-sm max-w-none font-serif">
                    {String(message.displayText)}
                  </Markdown>
                )}
                <ToolCard message={message} />
                {message.toolResult?.isError && (
                  <div className="mx-3 mt-1 rounded-md bg-destructive/10 px-3 py-2 text-xs text-destructive">
                    {String(message.toolResult.content || '')}
                  </div>
                )}
              </>
            ) : message.isThinking ? (
              <Reasoning
                defaultOpen={false}
                staticDuration={typeof message.thinkingSeconds === 'number' ? message.thinkingSeconds : undefined}
                preview={typeof message.thinkingPreview === 'string' ? message.thinkingPreview : undefined}
              >
                <Markdown className="prose prose-sm prose-gray max-w-none">
                  {message.content}
                </Markdown>
                <div className="mt-3 flex items-center text-[11px]">
                  <MessageCopyControl content={String(message.content || '')} />
                </div>
              </Reasoning>
            ) : message.type === 'system' ? (
              <div className="whitespace-pre-wrap text-xs text-muted-foreground">
                {formattedMessageContent}
              </div>
            ) : (
              <div dir="auto" className="text-sm text-gray-700">
                {showThinking && message.reasoning && (
                  <Reasoning className="mb-3" defaultOpen={false}>
                    <div className="whitespace-pre-wrap">{message.reasoning}</div>
                  </Reasoning>
                )}

                {(() => {
                  const content = formattedMessageContent;
                  // Detect if content is pure JSON (starts with { or [)
                  const trimmedContent = content.trim();
                  if (
                    (trimmedContent.startsWith('{') || trimmedContent.startsWith('[')) &&
                    (trimmedContent.endsWith('}') || trimmedContent.endsWith(']'))
                  ) {
                    try {
                      const parsed = JSON.parse(trimmedContent);
                      const formatted = JSON.stringify(parsed, null, 2);
                      return (
                        <div className="my-2">
                          <div className="overflow-hidden rounded-lg border border-border bg-muted">
                            <pre className="overflow-x-auto p-4">
                              <code className="block whitespace-pre font-mono text-sm text-foreground">
                                {formatted}
                              </code>
                            </pre>
                          </div>
                        </div>
                      );
                    } catch {
                      // Not valid JSON, fall through to normal rendering
                    }
                  }

                  return message.type === 'assistant' ? (
                    <Markdown className="prose prose-sm prose-gray max-w-none">
                      {content}
                    </Markdown>
                  ) : (
                    <div className="whitespace-pre-wrap">{content}</div>
                  );
                })()}
              </div>
            )}

            {message.type === 'assistant' &&
              !message.isThinking &&
              !message.isToolUse &&
              String(message.content || '').trim().length > 0 && (
                <div className="group mt-1 flex w-full items-center gap-2 text-[11px] text-gray-400">
                  <MessageCopyControl content={formattedMessageContent} />
                </div>
              )}
          </div>
        </div>
      )}
    </div>
  );
});

MessageItem.displayName = 'MessageItem';

export default MessageItem;
