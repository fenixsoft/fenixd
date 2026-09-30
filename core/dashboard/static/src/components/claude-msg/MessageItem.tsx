// 单条消息渲染 —— 迁移自 claudecodeui MessageComponent.tsx（精简版）：
// - 去 i18n / provider logo / 语音 / 附件（图片、文件）/ 交互式 prompt
// - 头像用固定字符（Claude / U / 工具 / 错误）
// - thinking 折叠用本目录 Reasoning（无 radix 依赖）
import { memo, useMemo } from 'react';

import type { ChatMessage } from './types';
import { formatUsageLimitText } from './chatFormatting';
// 隐藏判定与 toolGrouping 同源单点（code-review item 2faec963d2ea /
// 1dd4d551b484）：渲染与分组共用同一谓词，防双写漂移
import { isThinkingHidden } from './toolGrouping';
import { Markdown, copyToClipboard } from './Markdown';
import { Reasoning } from './Reasoning';
import ClaudeLogo from './ClaudeLogo';
import ToolCard from './ToolCard';

// 复制统一复用 Markdown.tsx 的 copyToClipboard（item 562395f77242）：带
// execCommand 降级路径，非安全上下文（如 http://<局域网IP> 访问 dashboard，
// navigator.clipboard 为 undefined）下复制不再静默失效
function MessageCopyControl({ content }: { content: string }) {
  return (
    <button
      type="button"
      className="text-muted-foreground opacity-0 transition-opacity group-hover:opacity-100"
      title="复制"
      onClick={() => copyToClipboard(content).catch(() => {})}
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

  // JSON 正文探测与格式化纳入 useMemo（item 14eea692ef38）：此前在渲染 IIFE 内
  // 每次组件渲染都重复 JSON.parse + JSON.stringify，长 JSON 正文叠加父列表重
  // 渲染产生重复解析开销——仅在正文变化时重算，非 JSON 返回 null 走普通分支
  const jsonFormattedContent = useMemo<string | null>(() => {
    const trimmed = formattedMessageContent.trim();
    if (
      (trimmed.startsWith('{') || trimmed.startsWith('[')) &&
      (trimmed.endsWith('}') || trimmed.endsWith(']'))
    ) {
      try {
        return JSON.stringify(JSON.parse(trimmed), null, 2);
      } catch {
        // Not valid JSON, fall through to normal rendering
      }
    }
    return null;
  }, [formattedMessageContent]);

  const formattedTime = useMemo(() => {
    // 非法 timestamp（缺失/格式错）解析得 Invalid Date，toLocaleTimeString 会把
    // 字面 'Invalid Date' 渲染到头像行/气泡时间（code-review item 4bc55b8aa8d6）：
    // 校验解析结果，非法时省略时间显示（类型契约只保证字段存在，不保证可解析）。
    const t = new Date(message.timestamp);
    return Number.isNaN(t.getTime()) ? '' : t.toLocaleTimeString();
  }, [message.timestamp]);
  // thinkingForced：无正文兜底强制渲染的 thinking（design D4）不受开关隐藏，
  // 否则 thinking-only 流的兜底产物在渲染层被击穿（verification BUG-02）。
  // 判定经 toolGrouping.isThinkingHidden 与分组层同源（item 2faec963d2ea）
  if (isThinkingHidden(message, showThinking)) {
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
                {/* 复制口径与气泡展示同源（item 1c90277944ce）：用户气泡原样渲染
                    message.content，复制原始 content；assistant 气泡渲染的是经
                    formatUsageLimitText（及 JSON 格式化）后的文本，复制同源格式化
                    文本——两处统一为「剪贴板 == 气泡所见」，不做跨类型拉齐 */}
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
                className="group"
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
                {(() => {
                  // JSON 探测/格式化结果已 memo 化（item 14eea692ef38），此处只做分支渲染
                  if (jsonFormattedContent !== null) {
                    return (
                      <div className="my-2">
                        <div className="overflow-hidden rounded-lg border border-border bg-muted">
                          <pre className="overflow-x-auto p-4">
                            <code className="block whitespace-pre font-mono text-sm text-foreground">
                              {jsonFormattedContent}
                            </code>
                          </pre>
                        </div>
                      </div>
                    );
                  }

                  return message.type === 'assistant' ? (
                    <Markdown className="prose prose-sm prose-gray max-w-none">
                      {formattedMessageContent}
                    </Markdown>
                  ) : (
                    <div className="whitespace-pre-wrap">{formattedMessageContent}</div>
                  );
                })()}
              </div>
            )}

            {message.type === 'assistant' &&
              !message.isThinking &&
              !message.isToolUse &&
              String(message.content || '').trim().length > 0 && (
                /* 复制口径与气泡展示同源（item 1c90277944ce）：气泡渲染的是
                   formatUsageLimitText 后的文本（JSON 正文分支则为美化后的
                   jsonFormattedContent，item d49ecef4bdd2），复制同源格式化
                   文本，保证「剪贴板 == 气泡所见」（用户消息侧同理复制其原样
                   展示的 content） */
                <div className="group mt-1 flex w-full items-center gap-2 text-[11px] text-gray-400">
                  <MessageCopyControl
                    content={
                      jsonFormattedContent !== null ? jsonFormattedContent : formattedMessageContent
                    }
                  />
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
