import { useEffect, useState } from 'react';

// 与 antd md 断点（≥768）对齐；同步 matchMedia 首帧即得到正确值，
// 避免 Grid.useBreakpoint() 首帧空对象导致的移动端闪 tables / PC 误判
const QUERY = '(max-width: 767.98px)';

export function useIsMobile(): boolean {
  const [isMobile, setIsMobile] = useState(() =>
    typeof window !== 'undefined' ? window.matchMedia(QUERY).matches : false,
  );

  useEffect(() => {
    const mql = window.matchMedia(QUERY);
    const onChange = (e: MediaQueryListEvent) => setIsMobile(e.matches);
    mql.addEventListener('change', onChange);
    // 订阅挂上前发生的媒体变更收不到 change 事件，挂载后再同步一次对齐
    setIsMobile(mql.matches);
    return () => mql.removeEventListener('change', onChange);
  }, []);

  return isMobile;
}
