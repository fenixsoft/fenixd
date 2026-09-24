// 迁移自 claudecodeui src/components/chat/utils/messageKeys.ts（原样）

import type { ChatMessage } from './types';

const toMessageKeyPart = (value: unknown): string | null => {
  if (typeof value !== 'string' && typeof value !== 'number') {
    return null;
  }

  const normalized = String(value).trim();
  return normalized.length > 0 ? normalized : null;
};

export const getIntrinsicMessageKey = (message: ChatMessage): string | null => {
  const candidates = [
    message.id,
    message.messageId,
    message.toolId,
    message.toolCallId,
    message.blobId,
    message.rowid,
    message.sequence,
  ];

  for (const candidate of candidates) {
    const keyPart = toMessageKeyPart(candidate);
    if (keyPart) {
      return `message-${message.type}-${keyPart}`;
    }
  }

  const timestamp = new Date(message.timestamp).getTime();
  if (!Number.isFinite(timestamp)) {
    return null;
  }

  const contentPreview = typeof message.content === 'string' ? message.content.slice(0, 48) : '';
  const toolName = typeof message.toolName === 'string' ? message.toolName : '';
  // [fenix-ignore:0209ad3f1986] 撞键边界一句话：仅当七个身份字段全缺失且同毫秒同型同前 48 字符前缀才可能撞键，上游 claudecodeui 原样迁移；本仓库唯一调用方 ClaudeMessageList 的 messageKeyMap 已按出现序号 __n 消歧，裸用本函数仍可能撞键
  return `message-${message.type}-${timestamp}-${toolName}-${contentPreview}`;
};
