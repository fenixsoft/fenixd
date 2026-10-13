// useComposerMenuAnchor — composer 弹层锚定 hook（add-session-composer 2.2）。
// 迁移自 claudecodeui useComposerMenuAnchor.ts：以 right/bottom 锚定让菜单向上、
// 向左生长而无需先自测尺寸，避免首帧错位；maxWidth 收缩保证手机上不越出左缘。
// 当前版本菜单链（模型/权限）裁剪后暂无消费方——P2 回归时与
// ComposerMenuPrimitives 配套启用。
//
// 与 SessionComposer.tsx 命令菜单锚点的对账（code-review 71613fdefb9d）：
// SessionComposer 已对同款跟随策略落地三项增强并回灌进本 hook——
// ① visualViewport resize 监听（移动端键盘开合使输入区位移，仅 window resize
//    不够）；② 锚点值未变不 setState 去重（滚动期间的连续重采样不引发无谓
//    重渲染）；③ useLayoutEffect 保证打开首帧即重采样坐标、不闪旧位置。
//    两处跟随策略后续增改须双向对齐，勿再以「迁移自、原样」掩盖分叉。
//
// 极端布局行为（code-review baff0617daff）：触发器上方可用高度 / 右侧可用
// 宽度容不下 200 下限时，尺寸收敛到可用值（可能比理想矮/窄，但不再确定性
// 越出视口上缘/左缘）；可用空间非正（触发器贴住或越过视口边缘）时按视口
// 比例兜底保证菜单至少可见，此时越界不可避免。
import { useCallback, useLayoutEffect, useRef, useState } from 'react';

export type ComposerMenuAnchor = {
  right: number;
  bottom: number;
  maxHeight: number;
  maxWidth: number;
};

const VIEWPORT_MARGIN = 8;
const MENU_GAP = 8;
const MIN_MENU_WIDTH = 200;

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
    const availableHeight = rect.top - MENU_GAP - VIEWPORT_MARGIN;
    const availableWidth = window.innerWidth - right - VIEWPORT_MARGIN;
    const next: ComposerMenuAnchor = {
      right,
      bottom: window.innerHeight - rect.top + MENU_GAP,
      // 尺寸下限仅在可用空间容得下时生效；空间不足收敛到可用值，空间非正时
      // 按视口比例兜底（见头注「极端布局行为」），避免下限反把菜单推出视口。
      maxHeight:
        availableHeight > 0
          ? availableHeight
          : Math.round(window.innerHeight * 0.4),
      maxWidth:
        availableWidth > 0
          ? Math.min(Math.max(MIN_MENU_WIDTH, preferredWidth), availableWidth)
          : Math.round(window.innerWidth * 0.9),
    };
    // 锚点未变不 setState：滚动 / 键盘开合期间的连续重采样不引发无谓重渲染
    // （对齐 SessionComposer 的去重口径）。
    setAnchor((previous) =>
      previous &&
      previous.right === next.right &&
      previous.bottom === next.bottom &&
      previous.maxHeight === next.maxHeight &&
      previous.maxWidth === next.maxWidth
        ? previous
        : next,
    );
  }, [preferredWidth]);

  // useLayoutEffect（对齐 SessionComposer）：打开首帧就是重采样后的坐标，
  // 不闪一帧旧位置。
  useLayoutEffect(() => {
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
      // 只拦截源自本菜单链路（trigger/menu 内）的 Escape（code-review
      // 2c60e17d2bb7）：capture 阶段对任意目标一律 preventDefault +
      // stopPropagation 会抢食其他 Escape 消费方（如 useSlashCommands 的
      // textarea 处理），多个本 hook 实例并存时也会一次关掉全部而非只关
      // 焦点所在菜单；链路外的 Escape 原样放行，由其归属消费方处理。
      const target = event.target as Node;
      if (
        !triggerRef.current?.contains(target) &&
        !menuRef.current?.contains(target)
      ) {
        return;
      }
      event.preventDefault();
      event.stopImmediatePropagation();
      onClose();
      triggerRef.current?.focus();
    };

    document.addEventListener('pointerdown', handlePointerDown);
    const visualViewport = window.visualViewport;
    window.addEventListener('resize', updateAnchor);
    window.addEventListener('scroll', updateAnchor, true);
    visualViewport?.addEventListener('resize', updateAnchor);
    window.addEventListener('keydown', handleKeyDown, { capture: true });
    updateAnchor();

    return () => {
      document.removeEventListener('pointerdown', handlePointerDown);
      window.removeEventListener('resize', updateAnchor);
      window.removeEventListener('scroll', updateAnchor, true);
      visualViewport?.removeEventListener('resize', updateAnchor);
      window.removeEventListener('keydown', handleKeyDown, { capture: true });
    };
  }, [isOpen, onClose, updateAnchor]);

  return { triggerRef, menuRef, anchor, updateAnchor };
}
