// 人工告警「标记已处理」乐观遮蔽共享 hook（code-review items d9c50f5bcc38、
// e673281b0b03）：overview AlertBanner 与 activities 页的同源逻辑（optimistic
// 数组、inOptimistic 过滤、「后端确认已消失才移除」的收敛 effect、markHandled
// 包装的失败回滚）此前近乎逐行双写，两副本会各自漂移，收敛单源两页复用；
// message 提示与刷新回调（load）仍留在各 surface。
// 收敛口径（item e673281b0b03）：标记成功不立即解除遮蔽——后端告警列表存在收敛
// 窗口（横幅文档注释所记 3s），立即解除会让已处理告警在「未处理」列表闪回且无
// 兜底；仍由收敛 effect 在 alertsData 确认该 id 已消失后清除。另设超时兜底：
// load 持续失败（SSE 断连、网络故障）导致 alertsData 停留旧值时，超时强制解除
// 遮蔽，不让已标记告警在「未处理」与「已解决」两个列表同时消失。失败立即回滚，
// 绝不永久遮蔽。
import { useCallback, useEffect, useRef, useState } from 'react';
import type { AlertItem, AlertsData } from '@/services/dashboard';
import { markAlertHandled } from '@/services/dashboard';

// 「成功标记后超时仍未获后端确认」的兜底阈值：正常路径下首次成功的 load 即由
// 收敛 effect 清除（远快于此），仅 load 持续失败期间才走到超时强制收敛
const OPTIMISTIC_FALLBACK_MS = 10_000;

export function useOptimisticAlerts(alertsData: AlertsData | null) {
  const [optimistic, setOptimistic] = useState<string[]>([]);
  // 标记成功的时刻（id → ts）：超时兜底的计时依据（ref 记账不触发渲染）
  const confirmedAtRef = useRef(new Map<string, number>());
  // 兜底时钟：仅在存在乐观遮蔽时每秒 tick，驱动下方超时检查（alertsData 陈旧
  // 不再更新时收敛 effect 仍能按时推进）；遮蔽清空即停表，卸载自动清理
  const [tick, setTick] = useState(0);
  useEffect(() => {
    if (!optimistic.length) return;
    const timer = setInterval(() => setTick((v) => v + 1), 1000);
    return () => clearInterval(timer);
  }, [optimistic.length]);

  const inOptimistic = (id: string) => optimistic.includes(id);

  // 收敛 effect：后端确认已消失的乐观 id 才移除遮蔽（绝不永久遮蔽）；
  // alertsData 陈旧（load 持续失败）期间由 tick 驱动的超时兜底强制收敛
  useEffect(() => {
    if (!optimistic.length) return;
    const stillThere = alertsData ? new Set((alertsData.alerts || []).map((a) => a.id)) : null;
    const now = Date.now();
    const next = optimistic.filter((id) => {
      if (stillThere && !stillThere.has(id)) {
        confirmedAtRef.current.delete(id);
        return false;
      }
      const confirmedAt = confirmedAtRef.current.get(id);
      if (confirmedAt != null && now - confirmedAt >= OPTIMISTIC_FALLBACK_MS) {
        confirmedAtRef.current.delete(id);
        return false;
      }
      return true;
    });
    if (next.length !== optimistic.length) setOptimistic(next);
  }, [alertsData, optimistic, tick]);

  // 标记已处理包装：成功记录收敛时刻并返回 null（遮蔽待确认或超时兜底清除），
  // 失败立即回滚遮蔽并返回错误文案（提示与刷新由各 surface 接续）
  const markHandled = useCallback(async (a: AlertItem): Promise<string | null> => {
    // 去重守卫：同 id 并发重复调用（快速双击等）不重复写入遮蔽数组
    setOptimistic((prev) => (prev.includes(a.id) ? prev : [...prev, a.id]));
    try {
      await markAlertHandled(a.project, a.id);
      confirmedAtRef.current.set(a.id, Date.now());
      return null;
    } catch (err) {
      // 失败即回滚乐观遮蔽：后端列表仍含该 id，不回滚会让未处理告警被永久隐藏
      setOptimistic((prev) => prev.filter((id) => id !== a.id));
      return err instanceof Error ? err.message : String(err);
    }
  }, []);

  return { optimistic, inOptimistic, markHandled };
}
