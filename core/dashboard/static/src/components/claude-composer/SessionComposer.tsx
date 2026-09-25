// SessionComposer — 会话输入控件业务壳（add-session-composer 2.4）。
// 迁移自 claudecodeui ChatComposer.tsx，按 fenixd 场景深度裁剪：排队消息卡、
// 权限请求横幅、模型/权限菜单、token 徽章、语音、附件拖拽区全部移除；停止
// 语义映射到既有 stopSession（由 SessionPanel 注入 onStop）。输入区贴底全宽、
// VisualViewport 键盘高度经 --keyboard-height 变量消费（D4）。
import { useEffect, useMemo, useRef } from 'react';
import type { CSSProperties, FormEvent, ReactNode } from 'react';
import { Button } from 'antd';
import {
  ClearOutlined,
  LoadingOutlined,
  MessageOutlined,
  StopOutlined,
} from '@ant-design/icons';

import './composer.css';
import { cn } from './cn';
import { useVisualViewportHeight } from './useVisualViewportHeight';
import { useComposerState } from './useComposerState';
import CommandMenu from './CommandMenu';
import {
  PromptInput,
  PromptInputBody,
  PromptInputTextarea,
  PromptInputFooter,
  PromptInputTools,
  PromptInputButton,
  PromptInputSubmit,
} from './PromptInput';

// D8：中文常量替换 react-i18next 文案
const DEFAULT_PLACEHOLDER = '输入消息…（Enter 发送，Shift+Enter 换行，/ 唤起命令，@ 引用文件）';
const SEND_HINT = 'Enter 发送，Shift+Enter 换行';
const END_HINT_DEFAULT = '会话已结束。切离本分面再切回可开始新会话。';

export interface SessionComposerProps {
  /** 项目名：草稿/命令频次 localStorage 键的一部分。 */
  project: string;
  /** 发送请求在途（禁用发送，防并发重复请求）。 */
  sending: boolean;
  /** 会话终态：禁用输入区并显示会话已结束提示。 */
  disabled: boolean;
  /** 终态提示文案；缺省用 END_HINT_DEFAULT。 */
  endHint?: string;
  /** 发送单点：resolve=成功（清空草稿），reject=失败（还原草稿）。 */
  onSend: (text: string) => Promise<void>;
  /** 停止会话（既有 stopSession 语义：终止整个会话进程）。 */
  onStop?: () => void;
  /** 停止请求在途。 */
  stopping?: boolean;
  /** 是否可停止（会话在飞时 true）。 */
  canStop?: boolean;
  /** 斜杠命令名（GET /api/session/commands → slash_commands）。 */
  slashCommands: string[];
  /** skill 名（GET /api/session/commands → skills）。 */
  skills: string[];
  /** 项目文件相对路径（GET /api/session/files）。 */
  files: string[];
}

export default function SessionComposer({
  project,
  sending,
  disabled,
  endHint,
  onSend,
  onStop,
  stopping = false,
  canStop = false,
  slashCommands,
  skills,
  files,
}: SessionComposerProps) {
  // files/slashCommands/skills 端点失败静默降级（SessionPanel 已吞错给空数组）。
  const composer = useComposerState({
    project,
    sending,
    disabled,
    onSend,
    slashCommands,
    skills,
    files,
  });
  const keyboardHeight = useVisualViewportHeight();

  const fileDropdownRef = useRef<HTMLDivElement | null>(null);
  const selectedFileRef = useRef<HTMLDivElement | null>(null);

  const commandMenuPosition = useMemo(() => {
    if (!composer.showCommandMenu) {
      return { top: 0, left: 16, bottom: 90 };
    }
    const textareaRect = composer.textareaRef.current?.getBoundingClientRect();
    return {
      top: textareaRect ? Math.max(16, textareaRect.top - 316) : 0,
      left: textareaRect ? textareaRect.left : 16,
      bottom: textareaRect ? window.innerHeight - textareaRect.top + 8 : 90,
    };
  }, [composer.showCommandMenu, composer.textareaRef]);

  // 键盘高亮选中项滚入可视区
  useEffect(() => {
    const dropdown = fileDropdownRef.current;
    const selectedFile = selectedFileRef.current;
    if (!composer.showFileDropdown || !dropdown || !selectedFile) {
      return;
    }

    const itemTop = selectedFile.offsetTop;
    const itemBottom = itemTop + selectedFile.offsetHeight;
    const visibleTop = dropdown.scrollTop;
    const visibleBottom = visibleTop + dropdown.clientHeight;

    if (itemTop < visibleTop) {
      dropdown.scrollTop = itemTop;
    } else if (itemBottom > visibleBottom) {
      dropdown.scrollTop = itemBottom - dropdown.clientHeight;
    }
  }, [composer.selectedFileIndex, composer.showFileDropdown]);

  const hasInput = Boolean(composer.input.trim());
  const sendDisabled = disabled || sending || !hasInput;

  const handleFormSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    void composer.handleSubmit().catch(() => {
      // 失败已还原草稿；错误提示由 SessionPanel 呈现
    });
  };

  const renderTool = (node: ReactNode) => node;

  return (
    <div
      className="fenix-composer chat-composer-shell relative flex-shrink-0 px-2 pt-0 sm:px-4 fenix-composer-shell-pb"
      style={{ '--keyboard-height': `${keyboardHeight}px` } as CSSProperties}
    >
      <div className="fenix-composer-input-shell relative mx-auto max-w-[54.25rem]">
        {composer.showFileDropdown && composer.filteredFiles.length > 0 && (
          <div
            ref={fileDropdownRef}
            className="fenix-composer-dropdown absolute bottom-full left-0 right-0 z-50 mb-2 max-h-48 overflow-y-auto rounded-xl border border-border/50 bg-card/95 shadow-lg backdrop-blur-md"
          >
            {composer.filteredFiles.map((file, index) => (
              <div
                key={file.path}
                ref={index === composer.selectedFileIndex ? selectedFileRef : undefined}
                className={`cursor-pointer touch-manipulation border-b border-border/30 px-4 py-3 last:border-b-0 ${
                  index === composer.selectedFileIndex
                    ? 'bg-primary/8 text-primary'
                    : 'text-foreground hover:bg-accent/50'
                }`}
                onMouseDown={(event) => {
                  event.preventDefault();
                  event.stopPropagation();
                }}
                onClick={(event) => {
                  event.preventDefault();
                  event.stopPropagation();
                  composer.selectFile(file);
                }}
              >
                <div className="text-sm font-medium">{file.name}</div>
                <div className="font-mono text-xs text-muted-foreground">{file.path}</div>
              </div>
            ))}
          </div>
        )}

        <CommandMenu
          commands={composer.filteredCommands}
          selectedIndex={composer.selectedCommandIndex}
          onSelect={composer.handleCommandSelect}
          onClose={composer.resetCommandMenuState}
          position={commandMenuPosition}
          isOpen={composer.showCommandMenu}
          frequentCommands={composer.frequentCommands}
        />

        <PromptInput
          onSubmit={handleFormSubmit}
          status="ready"
          className={composer.isTextareaExpanded ? 'chat-input-expanded' : ''}
        >
          <PromptInputBody>
            <div
              ref={composer.inputHighlightRef}
              aria-hidden="true"
              className="pointer-events-none absolute inset-0 overflow-hidden rounded-xl"
            >
              <div className="chat-input-placeholder chat-input-overlay block w-full whitespace-pre-wrap break-words px-4 py-2 text-sm leading-6 text-transparent">
                {composer.renderInputWithMentions(composer.input)}
              </div>
            </div>

            <PromptInputTextarea
              ref={composer.textareaRef}
              dir="auto"
              value={composer.input}
              disabled={disabled}
              onChange={composer.handleInputChange}
              onClick={composer.handleTextareaClick}
              onKeyDown={composer.handleKeyDown}
              onScroll={(event) =>
                composer.syncInputOverlayScroll(event.target as HTMLTextAreaElement)
              }
              onFocus={() => composer.setIsInputFocused(true)}
              onBlur={() => composer.setIsInputFocused(false)}
              onInput={composer.handleTextareaInput}
              placeholder={disabled ? '会话已结束' : DEFAULT_PLACEHOLDER}
            />
          </PromptInputBody>

          <PromptInputFooter>
            <PromptInputTools className="min-w-0">
              {renderTool(
                <PromptInputButton
                  tooltip="斜杠命令与 Skills"
                  onClick={composer.handleToggleCommandMenu}
                  disabled={disabled}
                  className="relative"
                  aria-label="显示全部命令"
                >
                  <MessageOutlined />
                  {composer.slashCommandsCount > 0 && (
                    <span className="absolute -right-1 -top-1 flex h-4 w-4 items-center justify-center rounded-full bg-primary text-[10px] font-bold text-primary-foreground">
                      {composer.slashCommandsCount}
                    </span>
                  )}
                </PromptInputButton>,
              )}

              {hasInput &&
                renderTool(
                  <PromptInputButton
                    tooltip="清空输入"
                    onClick={composer.handleClearInput}
                    disabled={disabled}
                    className="hidden sm:flex"
                    aria-label="清空输入"
                  >
                    <ClearOutlined />
                  </PromptInputButton>,
                )}
            </PromptInputTools>

            <div className="flex shrink-0 items-center gap-1.5 sm:gap-2">
              <div
                className={cn(
                  'hidden text-xs text-muted-foreground/50 transition-opacity duration-200 lg:block',
                  hasInput ? 'opacity-0' : 'opacity-100',
                )}
              >
                {SEND_HINT}
              </div>

              {canStop && onStop && (
                <Button
                  danger
                  size="small"
                  icon={<StopOutlined />}
                  loading={stopping}
                  disabled={disabled || stopping}
                  onClick={onStop}
                >
                  停止
                </Button>
              )}

              <PromptInputSubmit
                disabled={sendDisabled}
                onClick={(event) => {
                  event.preventDefault();
                  void composer.handleSubmit().catch(() => {
                    // 失败已还原草稿；错误提示由 SessionPanel 呈现
                  });
                }}
                aria-label={disabled ? '会话已结束' : '发送'}
                title={disabled ? '会话已结束' : '发送'}
                className="h-9 w-9"
              >
                {sending ? <LoadingOutlined spin className="h-4 w-4" /> : undefined}
              </PromptInputSubmit>
            </div>
          </PromptInputFooter>
        </PromptInput>

        {disabled && (
          <p className="mt-1.5 px-1 text-xs text-gray-500">{endHint || END_HINT_DEFAULT}</p>
        )}
      </div>
    </div>
  );
}
