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
  // 同 id 在飞防重（code-review item cc4a669ce5fd）：同口径跟进姊妹 hook
  // useAlertAdjudication 的 resolvingIdsRef——请求发出前同步置位、finally 清除；
  // 双击间隔小于一帧时 optimistic 数组去重拦不住重复的 markAlertHandled 请求，
  // ref 在 await 前同步置位才拦得住（ref 承担防重真相，不触发渲染）
  const resolvingIdsRef = useRef<Set<string>>(new Set());
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
    // 孤儿记账清理：并发 markHandled 一成一败等场景可能留下不在遮蔽内的
    // confirmedAtRef 条目，而收敛遍历只看 optimistic 内的 id，孤儿条目永不会
    // 被下方逻辑清除；这里顺带移除，防 ref 记账随组件生命周期缓慢累积
    // （ref 删除不触发渲染，仅影响 optimistic 内 id 的超时兜底计时）
    const optimisticSet = new Set(optimistic);
    for (const id of confirmedAtRef.current.keys()) {
      if (!optimisticSet.has(id)) confirmedAtRef.current.delete(id);
    }
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
  // 失败立即回滚遮蔽并返回错误文案（提示与刷新由各 surface 接续）；同 id 在飞
  // 防重命中返回 'duplicate' 哨兵（item edcaa9807336，与成功返回的 null 可区分
  // ——首个请求仍在飞，成败提示由首调用接续，调用方不得对哨兵弹成功提示）
  const markHandled = useCallback(async (a: AlertItem): Promise<string | null> => {
    // 在飞防重守卫（item cc4a669ce5fd）：同 id 在飞期间返回 'duplicate' 哨兵
    // （后端请求由首调用负责），不重复发出 markAlertHandled；下方
    // optimistic 去重只拦遮蔽数组重复写入，拦不住请求本身
    if (resolvingIdsRef.current.has(a.id)) return 'duplicate';
    resolvingIdsRef.current.add(a.id);
    // 遮蔽写入守卫：同 id 已在遮蔽内则 no-op，不重复写入
    setOptimistic((prev) => (prev.includes(a.id) ? prev : [...prev, a.id]));
    try {
      await markAlertHandled(a.project, a.id);
      confirmedAtRef.current.set(a.id, Date.now());
      // 遮蔽补写（item f5126d5754ec）：并发一成一败且失败侧先返回时，该 id 已
      // 被失败回滚移出 optimistic，成功侧后返回只记 confirmedAtRef 会让已处理
      // 告警闪回「未处理」列表；这里按需补写遮蔽（已在遮蔽内则 no-op），使
      // 两种并发完成次序的遮蔽收敛一致，清除仍由收敛 effect（确认消失或超时
      // 兜底）负责
      setOptimistic((prev) => (prev.includes(a.id) ? prev : [...prev, a.id]));
      return null;
    } catch (err) {
      // 失败即回滚乐观遮蔽：后端列表仍含该 id，不回滚会让未处理告警被永久隐藏。
      // 例外：同 id 已有成功记录（并发一成一败、成功侧先返回）则跳过回滚——
      // 此刻移除会撤掉由成功请求支撑的遮蔽，让已处理告警闪回「未处理」列表；
      // 遮蔽仍由收敛 effect（后端确认消失或超时兜底）正常清除，绝不永久遮蔽
      if (!confirmedAtRef.current.has(a.id)) {
        setOptimistic((prev) => prev.filter((id) => id !== a.id));
      }
      return err instanceof Error ? err.message : String(err);
    } finally {
      resolvingIdsRef.current.delete(a.id);
    }
  }, []);

  return { optimistic, inOptimistic, markHandled };
}
