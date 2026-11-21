import { useEffect, useState } from 'react';

// 通用 matchMedia 订阅钩子（断点型特化如 useIsMobile 同款模式收敛于此）：
// useState initializer 同步取值，首帧即得到正确结果，避免 Grid.useBreakpoint()
// 首帧空对象导致的闪 tables / 误判；挂载后再重同步一次对齐（订阅挂上前发生的
// 媒体变更收不到 change 事件）。
export function useMediaQuery(query: string): boolean {
  const [matches, setMatches] = useState(() =>
    typeof window !== 'undefined' ? window.matchMedia(query).matches : false,
  );

  useEffect(() => {
    const mql = window.matchMedia(query);
    const onChange = (e: MediaQueryListEvent) => setMatches(e.matches);
    mql.addEventListener('change', onChange);
    setMatches(mql.matches);
    return () => mql.removeEventListener('change', onChange);
  }, [query]);

  return matches;
}
