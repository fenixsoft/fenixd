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
  // load 闭包经 ref 每渲染同步——闭包新鲜不等于重拉：筛选变化要即时生效
  // 须把筛选值作为 refreshKey 传入（进激活 effect 依赖触发 run）
  const loadRef = useRef(load);
  loadRef.current = load;
  const loadedRef = useRef(false);
  // fix e14d8d1dbe05: run 自增请求序号——60s 轮询、refreshKey 变化重拉（如
  // PipelineBoard 切换项目筛选）与 retry 可能并发在飞，响应到达顺序不保证，
  // 先发出后返回的旧响应会把旧数据写回（如筛选后被「全部项目」旧响应刷回
  // 未过滤列表）。仿 activities 页（fix 01635701025b）loadSeqRef 口径：仅
  // 最新一次请求允许落状态，过期响应（含其失败与收尾置位）直接丢弃
  const runSeqRef = useRef(0);
  // 卸载守卫：轮询 interval 卸载时会清理，但已在飞的 Promise 不取消——
  // 卸载后响应返回时序号守卫仍可能通过，故收尾落状态前再核本标志，
  // 不对已卸载组件 setData/setError/setLoading（组件卸载重挂时复位）
  const mountedRef = useRef(true);
  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);
  const [tick, setTick] = useState(0);
  const retry = useCallback(() => setTick((t) => t + 1), []);

  const run = useCallback(async (initial: boolean) => {
    const seq = ++runSeqRef.current;
    try {
      if (initial) setLoading(true);
      const d = await loadRef.current();
      // 写回前复核序号与存活：过期请求或已卸载不改写任何状态（data 与
      // loaded 标记均不覆盖）
      if (seq !== runSeqRef.current || !mountedRef.current) return;
      loadedRef.current = true;
      setData(d);
      setError('');
    } catch (err) {
      // 过期请求的失败同样不落状态，避免旧错误提示覆盖新请求结果
      if (seq !== runSeqRef.current || !mountedRef.current) return;
      // 后台刷新失败：保留旧数据仅置 error（首载失败 data 保持 null → 占位）
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      // 收尾置 false 同样纳入序号守卫（对齐 activities 页 fix 9fc948945fc7）：
      // 旧请求先完成时不抢在并发中的新请求之前撤掉加载指示
      if (seq === runSeqRef.current && mountedRef.current) setLoading(false);
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
