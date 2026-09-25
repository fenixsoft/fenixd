// useVisualViewportHeight — 虚拟键盘高度（add-session-composer 2.4 / D4）。
// 参照 claudecodeui AppContent 的 --keyboard-height 方案：keyboardHeight =
// max(0, innerHeight - visualViewport.height)。只监听 resize、不监听 scroll、
// 不读 offsetTop——iOS Safari 滚动内容会改变 offsetTop，读它会令高度在正常
// 滚动期间抖动（参考实现 AppContent.tsx 注释同源）。
import { useEffect, useState } from 'react';

export function useVisualViewportHeight(): number {
  const [keyboardHeight, setKeyboardHeight] = useState(0);

  useEffect(() => {
    const vv = window.visualViewport;
    if (!vv) {
      return undefined;
    }
    const update = () => {
      // Only resize matters — keyboard open/close changes vv.height.
      const kb = Math.max(0, window.innerHeight - vv.height);
      setKeyboardHeight(kb);
    };
    update();
    vv.addEventListener('resize', update);
    return () => {
      vv.removeEventListener('resize', update);
    };
  }, []);

  return keyboardHeight;
}
