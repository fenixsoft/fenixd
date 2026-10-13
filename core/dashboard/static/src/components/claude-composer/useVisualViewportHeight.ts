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
      // 但 vv.height 变小并非键盘独有：双指缩放同样缩小 vv.height（且
      // scale > 1）。缩放态忽略本次更新、保持上一次有效键盘高度——消费方
      // （SessionComposer）拿它写 --keyboard-height 推起输入区，缩放期间
      // 维持原值可避免虚假键盘高度把输入区无谓推起；键盘开着时缩放也不致
      // 归零令输入区掉回键盘后面。缩放结束的 resize 会以 scale=1 重算。
      if (vv.scale > 1) {
        return;
      }
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
