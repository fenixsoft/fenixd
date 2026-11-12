/**
 * utf8.ts — UTF-8 字节上限截断共享工具（单源）。
 *
 * 二分求 UTF-8 字节数 ≤ maxBytes 的最长字符前缀：按 UTF-16 码元二分，若恰落
 * 在代理对中间则回退一个码元，不劈开字符。原为 agentsMd.ts 与 session-title.ts
 * 各持一份逐字节相同的私有实现（正确性敏感：二分边界 + 代理对回退），单源化
 * 防两份拷贝日后独立演化时单侧漂移。
 */

import { Buffer } from "node:buffer";

/**
 * 二分求 UTF-8 字节数 ≤ maxBytes 的最长字符前缀（按 UTF-16 码元二分，若恰落在
 * 代理对中间则回退一个码元，不劈开字符）。
 */
export function truncateUtf8ByBytes(text: string, maxBytes: number): string {
  let lo = 0;
  let hi = text.length;
  while (lo < hi) {
    const mid = (lo + hi + 1) >>> 1;
    if (Buffer.byteLength(text.slice(0, mid), "utf-8") <= maxBytes) lo = mid;
    else hi = mid - 1;
  }
  if (lo > 0 && lo < text.length && text.charCodeAt(lo - 1) >= 0xd800 && text.charCodeAt(lo - 1) < 0xdc00) lo -= 1;
  return text.slice(0, lo);
}
