// 迁移自 claudecodeui src/shared/view/ui/Reasoning.tsx（精简版）：
// 原 UI 依赖 radix Collapsible / Shimmer / lucide，此处以受控展开的极简实现等价替代，
// 保留 streaming 时自动展开、结束后自动收起 + "思考了 N 秒" 文案。
import * as React from 'react';

const AUTO_CLOSE_DELAY = 1000;

export interface ReasoningProps extends React.HTMLAttributes<HTMLDivElement> {
  isStreaming?: boolean;
  defaultOpen?: boolean;
  duration?: number;
}

export const Reasoning: React.FC<ReasoningProps> = ({
  className,
  isStreaming = false,
  defaultOpen,
  children,
  style,
  ...props
}) => {
  const resolvedDefaultOpen = defaultOpen ?? isStreaming;
  const isExplicitlyClosed = defaultOpen === false;

  const [isOpen, setIsOpen] = React.useState(resolvedDefaultOpen);
  const hasEverStreamedRef = React.useRef(isStreaming);
  const [hasAutoClosed, setHasAutoClosed] = React.useState(false);
  const [duration, setDuration] = React.useState<number | undefined>(undefined);
  const startTimeRef = React.useRef<number | null>(null);

  React.useEffect(() => {
    if (isStreaming) {
      hasEverStreamedRef.current = true;
      if (startTimeRef.current === null) {
        startTimeRef.current = Date.now();
      }
    } else if (startTimeRef.current !== null) {
      setDuration(Math.ceil((Date.now() - startTimeRef.current) / 1000));
      startTimeRef.current = null;
    }
  }, [isStreaming]);

  // Auto-open when streaming starts
  React.useEffect(() => {
    if (isStreaming && !isOpen && !isExplicitlyClosed) {
      setIsOpen(true);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isStreaming]);

  // Auto-close after streaming ends
  React.useEffect(() => {
    if (hasEverStreamedRef.current && !isStreaming && isOpen && !hasAutoClosed) {
      const timer = setTimeout(() => {
        setIsOpen(false);
        setHasAutoClosed(true);
      }, AUTO_CLOSE_DELAY);
      return () => clearTimeout(timer);
    }
  }, [isStreaming, isOpen, hasAutoClosed]);

  const thinkingMessage =
    isStreaming ? '思考中…' : duration === undefined ? '已思考数秒' : `已思考 ${duration} 秒`;

  return (
    <div
      className={`not-prose rounded-lg border border-border/60 bg-muted/30 ${className || ''}`}
      style={style}
      {...props}
    >
      <button
        type="button"
        className="flex w-full items-center gap-2 px-3 py-2 text-left text-sm text-muted-foreground transition-colors hover:text-foreground"
        onClick={() => setIsOpen((current) => !current)}
        aria-expanded={isOpen}
      >
        <svg
          className={`h-3.5 w-3.5 flex-shrink-0 transition-transform ${isOpen ? 'rotate-90' : ''}`}
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
          aria-hidden
        >
          <path d="M9 18l6-6-6-6" />
        </svg>
        {thinkingMessage}
      </button>
      {isOpen && <div className="px-3 pb-3 text-sm text-muted-foreground">{children}</div>}
    </div>
  );
};

export const ReasoningContent: React.FC<{ children: React.ReactNode }> = ({ children }) => <>{children}</>;
