// SessionComposer — 会话输入控件业务壳（add-session-composer 2.4）。
// 迁移自 claudecodeui ChatComposer.tsx，按 fenixd 场景深度裁剪：排队消息卡、
// 权限请求横幅、模型/权限菜单、token 徽章、语音、附件拖拽区全部移除；停止
// 语义映射到既有 stopSession（由 SessionPanel 注入 onStop）。输入区贴底全宽、
// VisualViewport 键盘高度经 --keyboard-height 变量消费（D4）。
import { useEffect, useLayoutEffect, useRef, useState } from 'react';
import type { CSSProperties, SyntheticEvent } from 'react';
import { App, Button, Tooltip } from 'antd';
import {
  ClearOutlined,
  MessageOutlined,
  SendOutlined,
  StopOutlined,
} from '@ant-design/icons';

import './composer.css';
import { cn } from './cn';
import { formatCommandCount } from './composerLogic';
import { useVisualViewportHeight } from './useVisualViewportHeight';
import { useComposerState } from './useComposerState';
import CommandMenu, { DEFAULT_ANCHOR_BOTTOM } from './CommandMenu';
import {
  PromptInput,
  PromptInputBody,
  PromptInputTextarea,
  PromptInputFooter,
  PromptInputTools,
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
  const { message } = App.useApp();
  const fileDropdownRef = useRef<HTMLDivElement | null>(null);
  const selectedFileRef = useRef<HTMLDivElement | null>(null);
  // 命令菜单唤起按钮（code-review item 6aa027f2f9c1）：CommandMenu 的外点
  // 关闭须排除本按钮，否则菜单打开时点按钮会被外点关闭后又被 click 重新
  // 打开，按钮失去「再点收起」能力。
  const commandMenuTriggerRef = useRef<HTMLButtonElement | null>(null);

  // files/slashCommands/skills 端点失败静默降级（SessionPanel 已吞错给空数组）。
  const composer = useComposerState({
    project,
    sending,
    disabled,
    onSend,
    slashCommands,
    skills,
    files,
    // 下拉容器 ref 透传 useFileMentions（code-review item 432c294ae05f）：
    // 拖动下拉滚动条/点候选行间空白不算外点，下拉不被误收起。
    fileDropdownRef,
  });
  const keyboardHeight = useVisualViewportHeight();

  // 命令菜单锚点（code-review c69c4ee705ca）：弹层是 position:fixed，坐标只在
  // 打开那一帧采样会过期——页面滚动、窗口 resize、移动端键盘开合（visualViewport
  // 变化改 --keyboard-height 使输入区位移）后菜单会漂离输入区；CommandMenu 内部
  // resize 重渲染消费的仍是这份过期 position。菜单打开期间挂 resize +
  // scroll(capture) + visualViewport resize 监听持续重采样 textarea rect（对齐
  // useComposerMenuAnchor 的跟随策略），rect 未变不 setState；关闭即卸载监听
  // （isOpen=false 时 CommandMenu 不渲染，position 值不被消费）。用
  // useLayoutEffect 保证打开首帧就是重采样后的坐标，不闪旧位置。
  const [commandMenuPosition, setCommandMenuPosition] = useState({
    left: 16,
    bottom: DEFAULT_ANCHOR_BOTTOM,
  });

  useLayoutEffect(() => {
    if (!composer.showCommandMenu) {
      return;
    }
    const sampleCommandMenuAnchor = () => {
      const textareaRect = composer.textareaRef.current?.getBoundingClientRect();
      const next = textareaRect
        ? {
            left: textareaRect.left,
            bottom: window.innerHeight - textareaRect.top + 8,
          }
        : { left: 16, bottom: DEFAULT_ANCHOR_BOTTOM };
      setCommandMenuPosition((previous) =>
        previous.left === next.left && previous.bottom === next.bottom ? previous : next,
      );
    };

    sampleCommandMenuAnchor();
    const visualViewport = window.visualViewport;
    window.addEventListener('resize', sampleCommandMenuAnchor);
    window.addEventListener('scroll', sampleCommandMenuAnchor, true);
    visualViewport?.addEventListener('resize', sampleCommandMenuAnchor);
    return () => {
      window.removeEventListener('resize', sampleCommandMenuAnchor);
      window.removeEventListener('scroll', sampleCommandMenuAnchor, true);
      visualViewport?.removeEventListener('resize', sampleCommandMenuAnchor);
    };
    // keyboardHeight 入 deps：visualViewport resize 事件可能早于
    // --keyboard-height 变量提交触发，依赖键盘高度变化后重跑兜底重采样。
  }, [composer.showCommandMenu, composer.textareaRef, keyboardHeight]);

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
    // filteredFiles 入 deps（code-review item 442c2d1bc995）：继续输入使候选
    // 过滤收窄时 selectedFileIndex 不变，但 key={file.path} 列表重排会使选中项
    // DOM 节点重挂（selectedFileRef 指向新节点），不重跑则新选中项可能停在
    // 可视区外。filteredFiles 是 useState 持有的数组，引用仅在过滤结果真正
    // 变化时更新，入 deps 不会引发多余重跑。
  }, [composer.selectedFileIndex, composer.showFileDropdown, composer.filteredFiles]);

  const hasInput = Boolean(composer.input.trim());
  const sendDisabled = disabled || sending || !hasInput;

  // 表单提交与发送按钮共用的单一提交入口；参数放宽为 SyntheticEvent
  // 以同时兼容 form onSubmit 与 antd Button onClick（两者事件类型不同）。
  const handleFormSubmit = (event: SyntheticEvent) => {
    event.preventDefault();
    void composer.handleSubmit().catch(() => {
      // 失败已还原草稿；错误提示由 SessionPanel 呈现
    });
  };

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
                    ? 'bg-primary/10 text-primary'
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
          triggerRef={commandMenuTriggerRef}
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
              className="pointer-events-none absolute inset-0 overflow-hidden"
            >
              <div className="chat-input-placeholder chat-input-overlay block w-full whitespace-pre-wrap break-words px-4 py-2 text-sm leading-6 text-transparent">
                {composer.renderInputWithMentions(composer.input)}
              </div>
            </div>

            <PromptInputTextarea
              ref={composer.textareaRef}
              dir="auto"
              /* 命令菜单 ARIA 关联（code-review cbffca1f7ee4）：菜单键盘导航
                 时焦点始终留在本 textarea，高亮项须靠 aria-activedescendant
                 播报、容器靠 aria-controls 关联；undefined 时 React 移除属性
                 （菜单关闭或空候选），避免悬空引用。 */
              aria-controls={
                composer.showCommandMenu && composer.filteredCommands.length > 0
                  ? 'command-menu-listbox'
                  : undefined
              }
              aria-activedescendant={
                composer.showCommandMenu &&
                composer.filteredCommands.length > 0 &&
                composer.selectedCommandIndex >= 0
                  ? `command-menu-opt-${composer.selectedCommandIndex}`
                  : undefined
              }
              value={composer.input}
              disabled={disabled}
              onChange={composer.handleInputChange}
              onClick={composer.handleTextareaClick}
              onKeyDown={composer.handleKeyDown}
              onScroll={(event) =>
                composer.syncInputOverlayScroll(event.target as HTMLTextAreaElement)
              }
              onInput={composer.handleTextareaInput}
              placeholder={disabled ? '会话已结束' : DEFAULT_PLACEHOLDER}
            />
          </PromptInputBody>

          <PromptInputFooter>
            <PromptInputTools className="min-w-0">
              <Tooltip title="斜杠命令与 Skills">
                {/* 三个按钮统一 antd 默认风格（2026-09-25 用户定调） */}
                {/* disabled 按钮不派发鼠标事件、禁用态 Tooltip 永不弹出
                    （PromptInput.tsx 头注同款坑），外包 span 承载悬停
                    （同 RegressionTab span 承载范式）；inline-flex 使包装
                    不改变按钮在 flex 行内的尺寸与对齐。 */}
                <span className="inline-flex">
                  <Button
                    ref={commandMenuTriggerRef}
                    icon={<MessageOutlined />}
                    onClick={() => {
                      // 空候选点击给显式反馈（2026-09-25 缺陷修复）：init 事件
                      // 要等会话首次交互后才产生（stream-json 实证），新会话
                      // 首条消息前候选恒为空，静默不弹菜单会被当成按钮坏了。
                      if (composer.slashCommandsCount === 0) {
                        message.info('命令候选尚未就绪：会话完成首次交互后即可唤起');
                        return;
                      }
                      composer.handleToggleCommandMenu();
                    }}
                    disabled={disabled}
                    className="relative"
                    /* 开关态语义（code-review item 60db89ee581c）：按钮是开关，
                       aria-label 随菜单开合切换、aria-expanded 播报当前态；
                       Tooltip 保持静态文案不随动。 */
                    aria-expanded={composer.showCommandMenu}
                    aria-label={composer.showCommandMenu ? '收起命令菜单' : '显示全部命令'}
                  >
                    {composer.slashCommandsCount > 0 && (
                      <span className="absolute -right-1.5 -top-1.5 flex h-4 min-w-[1rem] items-center justify-center rounded-full bg-primary px-1 text-[10px] font-bold leading-none text-primary-foreground">
                        {formatCommandCount(composer.slashCommandsCount)}
                      </span>
                    )}
                  </Button>
                </span>
              </Tooltip>

              {hasInput && (
                <Tooltip title="清空输入">
                  {/* disabled 按钮不派发鼠标事件、禁用态 Tooltip 永不弹出
                      （PromptInput.tsx 头注同款坑），外包 span 承载悬停
                      （同 RegressionTab span 承载范式）；inline-flex 使包装
                      不改变按钮在 flex 行内的尺寸与对齐。响应式隐藏迁到
                      span，避免小屏留下空占位参与 flex gap。
                      小屏整体隐藏是有意取舍（code-review item 854dd6060f99）：
                      移动端不提供清空按钮入口，长按/滑动手势等价方案暂无
                      诉求依据，小屏清空走逐字删除，按钮仅 sm 及以上展示，
                      避免挤占小屏工具行宽度。 */}
                  <span className="hidden sm:inline-flex">
                    <Button
                      icon={<ClearOutlined />}
                      onClick={composer.handleClearInput}
                      disabled={disabled}
                      aria-label="清空输入"
                    />
                  </span>
                </Tooltip>
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
                <Tooltip title="停止会话">
                  {/* 三个按钮统一 antd 默认风格（2026-09-25 用户定调） */}
                  {/* disabled 按钮不派发鼠标事件、禁用态 Tooltip 永不弹出
                      （PromptInput.tsx 头注同款坑），外包 span 承载悬停
                      （同 RegressionTab span 承载范式）。 */}
                  <span className="inline-flex">
                    <Button
                      danger
                      icon={<StopOutlined />}
                      loading={stopping}
                      disabled={disabled || stopping}
                      onClick={onStop}
                      aria-label="停止会话"
                    />
                  </span>
                </Tooltip>
              )}

              {/* disabled 按钮不派发鼠标事件、禁用态 Tooltip 永不弹出
                  （PromptInput.tsx 头注同款坑；sendDisabled 在空输入恒真，
                  禁用态悬停提示恰是最需要提示的场景），外包 span 承载悬停
                  （同 RegressionTab span 承载范式）；原 title 原生提示是
                  禁用态无提示的补偿 hack，Tooltip 恢复后会同文案双弹，移除
                  （可访问名仍由 aria-label 提供）。 */}
              <Tooltip title={disabled ? '会话已结束' : '发送'}>
                <span className="inline-flex">
                  <Button
                    icon={<SendOutlined />}
                    loading={sending}
                    disabled={sendDisabled}
                    onClick={handleFormSubmit}
                    aria-label={disabled ? '会话已结束' : '发送'}
                  />
                </span>
              </Tooltip>
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
