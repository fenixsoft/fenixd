// PromptInput — 无样式原语（add-session-composer 2.1）。
// 迁移自 claudecodeui shared/view/ui/PromptInput.tsx，裁剪：
//  - shadcn Button/Tooltip 换 antd Tooltip + 原生 button（tailwind 类保留）；
//  - lucide 图标换 @ant-design/icons（SendOutlined / StopOutlined）；
//  - PromptInputHeader（附件区）随附件链裁剪不迁。
//
// 预留说明：PromptInputButton / PromptInputSubmit / usePromptInput（连同
// status Context 与 Send/Stop 图标切换）当前全仓无消费方（桶文件亦未导出），
// 属对齐上游原语集的预留 API，非死代码遗留。启用前注意：PromptInputButton
// 的 tooltip 用 antd Tooltip 直接包 disabled 按钮时，disabled:pointer-events-none
// 会让 tooltip 永不弹出，届时需外包 span 或改走其他提示形态。

import * as React from 'react';
import { Tooltip } from 'antd';
import { SendOutlined, StopOutlined } from '@ant-design/icons';

import { cn } from './cn';

/* ─── Context ────────────────────────────────────────────────────── */

type PromptInputStatus = 'ready' | 'submitted' | 'streaming' | 'error';

interface PromptInputContextValue {
  status: PromptInputStatus;
}

const PromptInputContext = React.createContext<PromptInputContextValue | null>(null);

const usePromptInput = () => {
  const context = React.useContext(PromptInputContext);
  if (!context) {
    throw new Error('PromptInput components must be used within PromptInput');
  }
  return context;
};

/* ─── PromptInput (root form) ────────────────────────────────────── */

export interface PromptInputProps extends React.FormHTMLAttributes<HTMLFormElement> {
  status?: PromptInputStatus;
}

export const PromptInput = React.forwardRef<HTMLFormElement, PromptInputProps>(
  ({ className, status = 'ready', children, ...props }, ref) => {
    const contextValue = React.useMemo(() => ({ status }), [status]);

    return (
      <PromptInputContext.Provider value={contextValue}>
        <form
          ref={ref}
          data-slot="prompt-input"
          className={cn(
            // 无圆角（2026-09-25 用户定调：输入区直角）
            'relative overflow-hidden border border-border/50 bg-card/80 shadow-sm backdrop-blur-sm transition-all duration-200 focus-within:border-primary/30 focus-within:shadow-md focus-within:ring-1 focus-within:ring-primary/15',
            className,
          )}
          {...props}
        >
          {children}
        </form>
      </PromptInputContext.Provider>
    );
  },
);
PromptInput.displayName = 'PromptInput';

/* ─── PromptInputBody ────────────────────────────────────────────── */

export const PromptInputBody = React.forwardRef<
  HTMLDivElement,
  React.HTMLAttributes<HTMLDivElement>
>(({ className, ...props }, ref) => (
  <div
    ref={ref}
    data-slot="prompt-input-body"
    className={cn('relative', className)}
    {...props}
  />
));
PromptInputBody.displayName = 'PromptInputBody';

/* ─── PromptInputTextarea ────────────────────────────────────────── */

// 高度上限：移动端 40vh、桌面 300px（spec：超出后内部滚动且面板整体高度不变）。
export const PromptInputTextarea = React.forwardRef<
  HTMLTextAreaElement,
  React.TextareaHTMLAttributes<HTMLTextAreaElement>
>(({ className, ...props }, ref) => (
  <textarea
    ref={ref}
    data-slot="prompt-input-textarea"
    className={cn(
      // 占位符样式单一来源在 composer.css 的 .chat-input-placeholder::placeholder
      // （!important 对垒 tailwind utility），此处勿并排 tailwind placeholder-* 类。
      'chat-input-placeholder block max-h-[40vh] w-full resize-none overflow-y-auto bg-transparent px-4 py-2 text-sm leading-6 text-foreground focus:outline-none sm:max-h-[300px]',
      className,
    )}
    {...props}
  />
));
PromptInputTextarea.displayName = 'PromptInputTextarea';

/* ─── PromptInputFooter ──────────────────────────────────────────── */

export const PromptInputFooter = React.forwardRef<
  HTMLDivElement,
  React.HTMLAttributes<HTMLDivElement>
>(({ className, ...props }, ref) => (
  <div
    ref={ref}
    data-slot="prompt-input-footer"
    className={cn(
      'flex items-center justify-between border-t border-border/30 px-3 py-2',
      className,
    )}
    {...props}
  />
));
PromptInputFooter.displayName = 'PromptInputFooter';

/* ─── PromptInputTools ───────────────────────────────────────────── */

export const PromptInputTools = React.forwardRef<
  HTMLDivElement,
  React.HTMLAttributes<HTMLDivElement>
>(({ className, ...props }, ref) => (
  <div
    ref={ref}
    data-slot="prompt-input-tools"
    className={cn('flex items-center gap-1', className)}
    {...props}
  />
));
PromptInputTools.displayName = 'PromptInputTools';

/* ─── PromptInputButton ──────────────────────────────────────────── */

export interface PromptInputButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  tooltip?: React.ReactNode;
}

export const PromptInputButton = React.forwardRef<HTMLButtonElement, PromptInputButtonProps>(
  ({ className, tooltip, children, ...props }, ref) => {
    const button = (
      <button
        ref={ref}
        type="button"
        className={cn(
          'inline-flex h-8 w-8 items-center justify-center rounded-lg text-foreground/80 transition-colors hover:bg-accent hover:text-foreground focus-visible:outline-none disabled:pointer-events-none disabled:opacity-50 [&_svg]:size-4',
          className,
        )}
        {...props}
      >
        {children}
      </button>
    );

    if (tooltip) {
      return (
        <Tooltip title={tooltip}>
          {button}
        </Tooltip>
      );
    }

    return button;
  },
);
PromptInputButton.displayName = 'PromptInputButton';

/* ─── PromptInputSubmit ──────────────────────────────────────────── */

export interface PromptInputSubmitProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  status?: PromptInputStatus;
}

export const PromptInputSubmit = React.forwardRef<HTMLButtonElement, PromptInputSubmitProps>(
  ({ className, status: statusProp, children, ...props }, ref) => {
    const context = React.useContext(PromptInputContext);
    const status = statusProp ?? context?.status ?? 'ready';
    const isActive = status === 'submitted' || status === 'streaming';

    return (
      <button
        ref={ref}
        type={isActive ? 'button' : 'submit'}
        className={cn(
          'inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-primary text-primary-foreground shadow-sm transition-colors hover:bg-primary/90 focus-visible:outline-none disabled:pointer-events-none disabled:opacity-50',
          className,
        )}
        {...props}
      >
        {children ??
          (isActive ? (
            <StopOutlined className="h-3.5 w-3.5" />
          ) : (
            <SendOutlined className="h-4 w-4" />
          ))}
      </button>
    );
  },
);
PromptInputSubmit.displayName = 'PromptInputSubmit';

export { usePromptInput };
