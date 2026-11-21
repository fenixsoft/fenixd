import { useMediaQuery } from './useMediaQuery';

// 与 antd md 断点（≥768）对齐；同步 matchMedia 首帧即得到正确值，
// 避免 Grid.useBreakpoint() 首帧空对象导致的移动端闪 tables / PC 误判
const QUERY = '(max-width: 767.98px)';

export function useIsMobile(): boolean {
  return useMediaQuery(QUERY);
}
