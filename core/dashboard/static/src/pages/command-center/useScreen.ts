// useScreen.ts — 指挥中心四屏独立数据装配 hook（add-command-center 3.3）。
//
// 各屏独立加载/独立错误降级（错误占位 + 重试互不拖垮）+ 60s 常量静默轮询
// （design D5：轮询周期为页面常量，禁配置化）。后台刷新失败保留旧数据
// （error 置位但 data 不清），由调用方决定占位或内联提示。

import { useCallback, useEffect, useRef, useState } from 'react';

// 60s 常量静默轮询（specs「刷新与降级」Requirement：≥30s 固定刷新；
// design D5 定值 60s）
export const SCREEN_POLL_MS = 60_000;

export function useScreenResource<T>(
  load: () => Promise<T>,
  active: boolean,
  refreshKey: unknown = null,
): { data: T | null; error: string; loading: boolean; retry: () => void } {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  // load 闭包经 ref 每渲染同步（project 等筛选变化即时生效，无需进依赖数组）
  const loadRef = useRef(load);
  loadRef.current = load;
  const loadedRef = useRef(false);
  const [tick, setTick] = useState(0);
  const retry = useCallback(() => setTick((t) => t + 1), []);

  const run = useCallback(async (initial: boolean) => {
    try {
      if (initial) setLoading(true);
      const d = await loadRef.current();
      loadedRef.current = true;
      setData(d);
      setError('');
    } catch (err) {
      // 后台刷新失败：保留旧数据仅置 error（首载失败 data 保持 null → 占位）
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, []);

  // 激活即拉取：首载转圈、重激活（含 refreshKey 变化=收件箱裁决后的 KPI
  // 刷新）静默原位
  useEffect(() => {
    if (!active) return;
    void run(!loadedRef.current);
  }, [active, tick, refreshKey, run]);

  // 60s 静默轮询仅在激活屏运行（非激活屏不产生请求）
  useEffect(() => {
    if (!active) return;
    const hb = setInterval(() => void run(false), SCREEN_POLL_MS);
    return () => clearInterval(hb);
  }, [active, run]);

  return { data, error, loading, retry };
}
