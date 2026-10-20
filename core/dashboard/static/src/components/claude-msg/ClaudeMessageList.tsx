// 消息列表面板 —— 迁移自 claudecodeui ChatMessagesPane.tsx（精简版）：
// 去 provider 管理/分页加载/导出/权限/空态组件，保留分组渲染 + 聊天区布局，
// 新增滚动跟随（接近底部时新消息自动滚到底）。
import { memo, useCallback, useLayoutEffect, useMemo, useRef } from 'react';

import type { ChatMessage } from './types';
import { getIntrinsicMessageKey } from './messageKeys';
import { groupConsecutiveTools, isToolGroupItem } from './toolGrouping';

import MessageItem from './MessageItem';
import ToolGroupContainer from './ToolGroupContainer';

interface ClaudeMessageListProps {
  messages: ChatMessage[];
  showThinking?: boolean;
}

const BOTTOM_STICKY_THRESHOLD_PX = 80;

function ClaudeMessageList({ messages, showThinking = false }: ClaudeMessageListProps) {
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const stickToBottomRef = useRef(true);

  const groupedMessages = useMemo(
    () => groupConsecutiveTools(messages, showThinking),
    [messages, showThinking],
  );

  // Stable, deterministic keys for the messages rendered this pass.
  // Deriving keys purely from this render's ordered messages (intrinsic key,
  // disambiguated by occurrence index on collision) yields the same key for the
  // same message order, so React preserves existing DOM nodes on prepend/append.
  const messageKeyMap = useMemo(() => {
    const keys = new WeakMap<ChatMessage, string>();
    const occurrences = new Map<string, number>();
    const assign = (message: ChatMessage) => {
      const intrinsicKey = getIntrinsicMessageKey(message) ?? 'message-generated';
      const seen = occurrences.get(intrinsicKey) ?? 0;
      occurrences.set(intrinsicKey, seen + 1);
      keys.set(message, seen === 0 ? intrinsicKey : `${intrinsicKey}__${seen}`);
    };
    for (const item of groupedMessages) {
      if (isToolGroupItem(item)) {
        item.messages.forEach(assign);
      } else {
        assign(item);
      }
    }
    return keys;
  }, [groupedMessages]);

  const getMessageKey = useCallback(
    (message: ChatMessage) =>
      messageKeyMap.get(message) ?? getIntrinsicMessageKey(message) ?? 'message-generated',
    [messageKeyMap],
  );

  // 滚动跟随：接近底部时新内容自动滚到底，用户上滚阅读历史时不打扰
  // useLayoutEffect 在绘制前同步滚动，避免流式追加时先露底再跳底的抖动；
  // showThinking 入依赖：切换 thinking 显示会改变分组与高度，也须重新贴底。
  useLayoutEffect(() => {
    const el = scrollRef.current;
    if (!el || !stickToBottomRef.current) return;
    el.scrollTop = el.scrollHeight;
  }, [messages, showThinking]);

  const handleScroll = useCallback(() => {
    const el = scrollRef.current;
    if (!el) return;
    const distance = el.scrollHeight - el.scrollTop - el.clientHeight;
    stickToBottomRef.current = distance < BOTTOM_STICKY_THRESHOLD_PX;
  }, []);

  return (
    <div
      ref={scrollRef}
      onScroll={handleScroll}
      className="claude-msg-pane relative min-h-0 flex-1 overflow-y-auto overflow-x-hidden pt-3 pb-3"
    >
      <div className="w-full space-y-3 px-2 sm:px-4 sm:space-y-4">
        {messages.length === 0 ? (
          <div className="mt-8 text-center text-muted-foreground">
            <p className="text-sm">暂无消息</p>
          </div>
        ) : (
          groupedMessages.map((item) => {
            if (isToolGroupItem(item)) {
              const first = item.messages[0];
              return (
                <ToolGroupContainer
                  key={`tool-group-${getMessageKey(first)}`}
                  group={item}
                  getMessageKey={getMessageKey}
                  showThinking={showThinking}
                />
              );
            }
            // 顶层有意不做相邻同角色合并：prevMessage 恒为 null，MessageItem 的
            // isGrouped（grouped class / 头像与头部抑制）在此永不生效，
            // 仅由 ToolGroupContainer 展开组内时传入真实 prevMessage 驱动。
            return (
              <MessageItem key={getMessageKey(item)} message={item} prevMessage={null} showThinking={showThinking} />
            );
          })
        )}
      </div>
    </div>
  );
}

export default memo(ClaudeMessageList);
