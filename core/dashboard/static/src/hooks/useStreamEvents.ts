import { useCallback, useEffect, useRef } from 'react';
import { STREAM_URL } from '@/services/dashboard';

export interface UseStreamEventsOptions {
  /** 是否建立 SSE 连接（默认 true）：翻转为 false 时不建连并关闭既有连接（对齐消费点 early-return 不订阅语义） */
  enabled?: boolean;
  /** 连接重置键：值变化时关闭旧连接并按新语境重建（对齐 QualityTab project 切换、详情页 SPEC 切换的既有重建语义） */
  resetKey?: string;
  /** 连接（重新）建立回调：消费点在此复位各自的失败计数 / 降级状态 */
  onOpen?: () => void;
  /** 连接错误回调：入参为当前 EventSource 实例（消费点可读 readyState 区分重连中 / 永久停连）；不传即维持 EventSource 原生自动重连、无降级动作 */
  onError?: (es: EventSource) => void;
}

/**
 * SSE 单源连接共享 hook（code-review item 97a49df83a67）。
 *
 * 收敛仓库内四处同构的 EventSource 装配样板（activities 页 / useOpsAlertBadge /
 * QualityTab / 项目详情页）——连接管理（STREAM_URL 单源、enabled/resetKey 门控
 * 建立与重建、卸载 close）与报文解析守卫（JSON.parse try/catch + 字面量
 * "null"/标量报文丢弃）统一单源；重连降级（onerror）与连接恢复（onopen）语义
 * 经可选回调交给消费点，保持各处既有差异（计数阈值提示 / 降级轮询 / 原生重连）。
 *
 * 返回事件注册器：消费点经它登记报文分发回调（入参已通过解析与非对象守卫），
 * 回调经 ref 转发、身份更新不触发连接重建。回调在 effect 内注册时可捕获
 * effect 局部闭包（节流器 / effect 局部 loader 等，与各消费点原 onmessage
 * 的闭包形态一致）。
 *
 * 行为保持注记：
 * - onmessage 首行内置 live 哨：cleanup（卸载 / enabled 翻转 / resetKey 变化）
 *   后该连接上已入队的迟到 message 不再解析分发（QualityTab 原 disposed 守卫
 *   的通用化；对其余消费点属卸载后纯防御，正常路径零差异）；
 * - 非对象报文守卫统一为本 hook 单源口径：EV.data 为字面量 "null" 时
 *   JSON.parse 返回 null，直接读字段会抛 TypeError 中断本次事件处理
 *   （item 43c08fc037cf 口径，收敛前仅 useOpsAlertBadge 有此守卫）；
 * - onopen / onerror 同受 live 哨保护：cleanup 后迟到的开/错事件不再回调，
 *   防卸载后写 state / 复活降级轮询。
 */
export function useStreamEvents<T extends object>(
  options: UseStreamEventsOptions,
): (onEvent: (msg: T) => void) => void {
  const optsRef = useRef(options);
  // 每 commit 同步最新 onOpen/onError，连接生命周期只随 enabled/resetKey 变化
  useEffect(() => {
    optsRef.current = options;
  });

  const handlerRef = useRef<((msg: T) => void) | null>(null);
  const register = useCallback((onEvent: (msg: T) => void) => {
    handlerRef.current = onEvent;
  }, []);

  const { enabled = true, resetKey } = options;

  useEffect(() => {
    if (!enabled) return;
    let live = true;
    const es = new EventSource(STREAM_URL);
    // onopen/onerror 与 onmessage 同款 live 转发：闭包内经 optsRef.current 读
    // 最新回调，回调身份更新不重建连接（连接生命周期只随 enabled/resetKey 变化）
    es.onopen = () => {
      if (!live) return;
      optsRef.current.onOpen?.();
    };
    es.onmessage = (ev: MessageEvent) => {
      // cleanup 后该连接上已入队的迟到 message 不再解析分发
      if (!live) return;
      let msg: T | null = null;
      try {
        msg = JSON.parse(ev.data) as T | null;
      } catch {
        return;
      }
      // EV.data 为字面量 "null"（或其他 JSON 标量）时 parse 产物不是对象，
      // 直接读字段会抛 TypeError 中断本次事件处理——丢弃非对象报文
      if (!msg || typeof msg !== 'object') return;
      handlerRef.current?.(msg);
    };
    es.onerror = () => {
      if (!live) return;
      optsRef.current.onError?.(es);
    };
    // 卸载 / enabled 翻转 / resetKey 变化：关闭连接防泄漏，并停发后续回调
    return () => {
      live = false;
      es.close();
    };
  }, [enabled, resetKey]);

  return register;
}
