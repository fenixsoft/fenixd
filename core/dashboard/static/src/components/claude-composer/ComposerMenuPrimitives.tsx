// ComposerMenuPrimitives — composer 弹层共享原语（add-session-composer 2.1）。
// 迁移自 claudecodeui ComposerMenuPrimitives.tsx：MenuSurface / Heading /
// Separator / MenuItem 四件套，lucide Check 换 @ant-design/icons CheckOutlined，
// cn 内联本目录实现。当前版本菜单链裁剪后暂无消费方——P2（模型菜单/权限菜单）
// 回归时与 useComposerMenuAnchor 配套启用；文件随组件目录整体落位。
import type { ReactNode, Ref } from 'react';
import { CheckOutlined } from '@ant-design/icons';

import { cn } from './cn';
import type { ComposerMenuAnchor } from './useComposerMenuAnchor';

/**
 * Shared shell for the composer popovers (model/effort and permissions) so both
 * menus share one surface, one heading style and one row style.
 */
export function ComposerMenuSurface({
  anchor,
  menuRef,
  ariaLabel,
  children,
}: {
  anchor: ComposerMenuAnchor;
  menuRef: Ref<HTMLDivElement>;
  ariaLabel: string;
  children: ReactNode;
}) {
  return (
    <div
      ref={menuRef}
      role="menu"
      aria-label={ariaLabel}
      className="fixed z-[100] min-w-48 overflow-y-auto overscroll-contain rounded-xl border border-border bg-popover p-1 text-popover-foreground shadow-xl"
      style={{
        right: anchor.right,
        bottom: anchor.bottom,
        maxHeight: anchor.maxHeight,
        maxWidth: anchor.maxWidth,
      }}
    >
      {children}
    </div>
  );
}

export function ComposerMenuHeading({ children }: { children: ReactNode }) {
  return (
    <p className="px-2.5 pb-1 pt-1.5 text-[11px] font-medium text-muted-foreground">
      {children}
    </p>
  );
}

export function ComposerMenuSeparator() {
  return <div className="my-1 h-px bg-border" aria-hidden />;
}

export function ComposerMenuItem({
  label,
  description,
  icon,
  isSelected,
  onSelect,
  trailing,
  className,
}: {
  label: ReactNode;
  description?: ReactNode;
  icon?: ReactNode;
  isSelected: boolean;
  onSelect: () => void;
  trailing?: ReactNode;
  className?: string;
}) {
  return (
    <button
      type="button"
      role="menuitemradio"
      aria-checked={isSelected}
      onClick={onSelect}
      className={cn(
        'flex w-full items-start gap-2.5 rounded-lg px-2.5 py-1.5 text-left text-sm transition-colors',
        'hover:bg-accent focus-visible:bg-accent focus-visible:outline-none',
        isSelected ? 'text-foreground' : 'text-foreground/90',
        className,
      )}
    >
      {icon && (
        <span className="mt-0.5 flex h-4 w-4 shrink-0 items-center justify-center">
          {icon}
        </span>
      )}
      <span className="min-w-0 flex-1">
        <span className="block truncate leading-5">{label}</span>
        {description && (
          <span className="mt-0.5 block text-xs leading-4 text-muted-foreground">
            {description}
          </span>
        )}
      </span>
      <span className="mt-0.5 flex h-4 w-4 shrink-0 items-center justify-center">
        {trailing ?? (isSelected ? <CheckOutlined className="text-[12px] text-foreground" /> : null)}
      </span>
    </button>
  );
}
