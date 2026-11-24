import { useCallback, useEffect, useRef, useState } from 'react';
import { getAlerts } from '@/services/dashboard';
import { useStreamEvents } from '@/hooks/useStreamEvents';

/**
 * 运维菜单红点徽标计数 hook（consolidate-alerts-to-ops-page 4.1）。
 *
 * 概览告警横幅退役（4.3）后，全局告警感知面收敛为运维菜单项上的红点数字
 * 徽标（未处理且 choices 非空——可裁决告警才配人工注意力）。本 hook 把原
 * overview 页的告警管线整套迁来：/api/alerts 拉取 + SSE alerts/admin_activities
 * 事件驱动刷新，保留既有可靠性路数——
 *
 * - 事件合帧 500ms（item 332c514d9d76）：AdminMonitor/watcher 批量升级告警时
 *   短窗连发事件，逐事件 GET /api/alerts 会形成重拉风暴，窗口内合并为一次；
 * - SSE 永久停连降级 30s 轮询（item 690bc68a1883）：非 200 响应（连接数满等）
 *   会让 EventSource 永久停止重连、事件永不再到，onerror 降级为低频轮询，
 *   onopen（连接恢复）停轮询回到事件驱动（item 2303508d27ff 同类兜底先例）；
 * - visibilitychange 门控（item cad10ca9d3a8）：隐藏时暂停降级轮询（保留降级
 *   标记），恢复可见时补启并立即补拉，避免断连 + 后台标签组合持续消耗 daemon；
 * - load 序号守卫（item 370293e2857d 同源惯例）：合帧 tick / 降级轮询 / 可见性
 *   补拉可并发在飞，仅最新一次响应允许落计数，过期响应直接丢弃。
 *
 * SSE 连接装配样板已收敛 useStreamEvents 共享单源（code-review item
 * 97a49df83a67）：连接管理 / 解析守卫 / 卸载 close 由 hook 承担，永久停连
 * 降级轮询与连接恢复停轮询语义经 onOpen/onError 保持本 hook 既有差异。
 *
 * 挂载面（4.2）：仅由 app.tsx 的运维菜单名组件挂载；embed=1（dsh 面板桥）
 * menuRender:false 无菜单 → 组件不挂载 → 本 hook 不运行（零请求零连接）。
 */
// SSE 告警事件合帧窗口：窗口内多个 alerts/admin_activities 事件合并为一次拉取
const TICK_COALESCE_MS = 500;
// SSE 永久停连时的兜底轮询间隔（对齐原 overview 告警管线的 HEARTBEAT_MS 量级）
const FALLBACK_POLL_MS = 30000;

export function useOpsAlertBadge(): number {
  const [count, setCount] = useState(0);
  // 合帧定时器句柄（ref 供 onmessage 与卸载清理共用）
  const coalesceTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  // 降级轮询定时器句柄 + 降级状态标记（可见性暂停只清句柄、保留标记）
  const pollTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const fallbackActiveRef = useRef(false);
  // 拉取序号：过期响应不落计数（防旧快照闪回，同 overview/activities 页 loadSeqRef 惯例）
  const loadSeqRef = useRef(0);

  // 原 effect 内局部函数提升为组件级（回调身份恒定，供 onOpen/onError 与
  // visibilitychange / 合帧 tick 多处闭包共用；仅操作 refs，行为不变）
  const refresh = useCallback(async () => {
    const seq = ++loadSeqRef.current;
    try {
      const d = await getAlerts();
      // 计数口径（4.1）：未处理且 choices 非空（可裁决告警）——与后端
      // total_unhandled 口径解耦：后者含无 choices 的知情类告警，不配红点
      const n = (d.alerts || []).filter(
        (a) => Array.isArray(a.choices) && a.choices.length > 0,
      ).length;
      if (seq === loadSeqRef.current) setCount(n);
    } catch {
      // 拉取失败保留上次计数（徽标是弱提示面，不弹错误横幅）；下次
      // 事件/轮询/补拉自愈
    }
  }, []);

  const stopFallback = useCallback(() => {
    if (pollTimerRef.current) {
      clearInterval(pollTimerRef.current);
      pollTimerRef.current = null;
    }
  }, []);

  const startFallback = useCallback(() => {
    fallbackActiveRef.current = true;
    // 幂等：断线重连风暴中 onerror 可连发，只起一个轮询
    if (pollTimerRef.current) return;
    // 可见性门控：隐藏期间只记降级状态不起轮询，恢复可见后由 onVisible 补启
    if (document.visibilityState !== 'visible') return;
    void refresh();
    pollTimerRef.current = setInterval(() => void refresh(), FALLBACK_POLL_MS);
  }, [refresh]);

  // SSE 订阅移交 useStreamEvents 共享单源（code-review item 97a49df83a67）：
  // 连接管理 / 解析守卫（含字面量 "null" 报文丢弃，原为本文件独有守卫）/ 卸载
  // close 由 hook 承担
  const registerStreamEvent = useStreamEvents<{ type?: string }>({
    onOpen: () => {
      // 连接（重新）建立：停兜底轮询，回到 SSE 事件驱动（恢复路径）
      fallbackActiveRef.current = false;
      stopFallback();
    },
    onError: () => {
      // 非瞬态断连（503 连接数上限等）EventSource 会永久停止重连——降级低频
      // 轮询，连接恢复由 onOpen 停轮询
      startFallback();
    },
  });

  useEffect(() => {
    void refresh();
    const onVisible = () => {
      if (document.visibilityState === 'visible') {
        // 恢复可见时补启降级轮询——仅当 SSE 仍处降级状态（onOpen 未接管）
        // 才重启，避免 SSE 已重连却重复起轮询。降级态下补拉统一交由
        // startFallback 的立即 refresh 承担（隐藏期间轮询必已停，此处必走
        // 补启分支），就地再 refresh 会与之同事件循环在飞双拉 /api/alerts；
        // 非降级路径（SSE 事件驱动）仍就地补拉一次
        if (fallbackActiveRef.current) {
          startFallback();
        } else {
          void refresh();
        }
      } else {
        stopFallback();
      }
    };
    document.addEventListener('visibilitychange', onVisible);

    return () => {
      stopFallback();
      document.removeEventListener('visibilitychange', onVisible);
      if (coalesceTimerRef.current !== null) {
        clearTimeout(coalesceTimerRef.current);
        coalesceTimerRef.current = null;
      }
    };
  }, [refresh, startFallback, stopFallback]);

  useEffect(() => {
    // 报文经 hook 的解析与非对象守卫后到达此处（alerts/admin_activities 过滤
    // 与合帧逻辑保持本 hook 既有差异）
    registerStreamEvent((msg) => {
      // alerts/admin_activities 事件均驱动徽标刷新：AdminMonitor 新写入的升级
      // 告警走 admin_alerts.json 变更，watcher 只广播 type=admin_activities（无
      // alerts 事件），不同驱则停留页面期间新告警不上红点
      if (msg.type === 'alerts' || msg.type === 'admin_activities') {
        // 时间窗合帧：首个事件排程 TICK_COALESCE_MS 后的一次拉取，窗口内后续
        // 事件并入不再排程，逐事件重拉风暴收敛为每窗至多一次 GET /api/alerts
        if (coalesceTimerRef.current === null) {
          coalesceTimerRef.current = setTimeout(() => {
            coalesceTimerRef.current = null;
            void refresh();
          }, TICK_COALESCE_MS);
        }
      }
    });
  }, [registerStreamEvent, refresh]);

  return count;
}
