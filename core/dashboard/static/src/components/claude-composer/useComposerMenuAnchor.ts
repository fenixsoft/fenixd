// useComposerMenuAnchor — composer 弹层锚定 hook（add-session-composer 2.2）。
// 迁移自 claudecodeui useComposerMenuAnchor.ts（原样，零改动语义）：以
// right/bottom 锚定让菜单向上、向左生长而无需先自测尺寸，避免首帧错位；
// maxWidth 收缩保证手机上不越出左缘。当前版本菜单链（模型/权限）裁剪后暂无
// 消费方——P2 回归时与 ComposerMenuPrimitives 配套启用。
import { useCallback, useEffect, useRef, useState } from 'react';

export type ComposerMenuAnchor = {
  right: number;
  bottom: number;
  maxHeight: number;
  maxWidth: number;
};

const VIEWPORT_MARGIN = 8;
const MENU_GAP = 8;

/**
 * Positions a composer popover above its trigger and right-aligned to it.
 *
 * Anchoring with `right`/`bottom` rather than `left`/`top` lets the menu grow
 * upward and leftward without measuring itself first, so it never paints in the
 * wrong spot for a frame. The same anchor works on phones because `maxWidth`
 * shrinks the menu instead of letting it run off the left edge.
 */
export function useComposerMenuAnchor(
  isOpen: boolean,
  onClose: () => void,
  preferredWidth = 320,
) {
  const triggerRef = useRef<HTMLButtonElement | null>(null);
  const menuRef = useRef<HTMLDivElement | null>(null);
  const [anchor, setAnchor] = useState<ComposerMenuAnchor | null>(null);

  const updateAnchor = useCallback(() => {
    const rect = triggerRef.current?.getBoundingClientRect();
    if (!rect) {
      return;
    }

    const right = Math.max(VIEWPORT_MARGIN, window.innerWidth - rect.right);
    setAnchor({
      right,
      bottom: window.innerHeight - rect.top + MENU_GAP,
      maxHeight: Math.max(160, rect.top - MENU_GAP - VIEWPORT_MARGIN),
      maxWidth: Math.max(
        200,
        Math.min(preferredWidth, window.innerWidth - right - VIEWPORT_MARGIN),
      ),
    });
  }, [preferredWidth]);

  useEffect(() => {
    if (!isOpen) {
      return;
    }

    const handlePointerDown = (event: PointerEvent) => {
      const target = event.target as Node;
      if (
        !triggerRef.current?.contains(target) &&
        !menuRef.current?.contains(target)
      ) {
        onClose();
      }
    };

    const handleKeyDown = (event: globalThis.KeyboardEvent) => {
      if (event.key !== 'Escape') {
        return;
      }
      event.preventDefault();
      event.stopPropagation();
      onClose();
      triggerRef.current?.focus();
    };

    document.addEventListener('pointerdown', handlePointerDown);
    window.addEventListener('resize', updateAnchor);
    window.addEventListener('scroll', updateAnchor, true);
    window.addEventListener('keydown', handleKeyDown, { capture: true });
    updateAnchor();

    return () => {
      document.removeEventListener('pointerdown', handlePointerDown);
      window.removeEventListener('resize', updateAnchor);
      window.removeEventListener('scroll', updateAnchor, true);
      window.removeEventListener('keydown', handleKeyDown, { capture: true });
    };
  }, [isOpen, onClose, updateAnchor]);

  return { triggerRef, menuRef, anchor, updateAnchor };
}
