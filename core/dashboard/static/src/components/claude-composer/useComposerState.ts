// useComposerState — composer 逻辑核心（add-session-composer 2.3）。
// 迁移自 claudecodeui useChatComposerState.ts（1317 行），按 fenixd 场景深度
// 裁剪（D3）：删除排队消息状态机、权限模式菜单、模型菜单、token 徽章、语音
// 三件套、react-dropzone 附件链、builtin/custom 命令执行链；发送调用单点替换
// 为 onSend 回调（SessionPanel 落到既有 REST sendSessionMessage(project, text)
// 纯文本协议）。保留：草稿按 project 键持久化、isComposing 守卫、发送在途
// 禁用、失败还原草稿、textarea 高度自适应与 overlay 滚动同步、发送成功清空。
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type {
  ChangeEvent,
  FormEvent,
  KeyboardEvent,
  MouseEvent,
  SetStateAction,
} from 'react';

import { clearDraft, readDraft, writeDraft } from './chatStorage';
import {
  toSlashCommands,
  type SlashCommand,
  useSlashCommands,
} from './useSlashCommands';
import { useFileMentions } from './useFileMentions';

interface UseComposerStateArgs {
  /** 项目名：草稿/频次 localStorage 键的一部分。 */
  project: string;
  /** 发送请求在途（SessionPanel 的 sending 状态镜像）——在途禁用发送。 */
  sending: boolean;
  /** 会话终态（进程退出/已停止）——禁用输入区。 */
  disabled: boolean;
  /**
   * 发送单点（D3）：resolve = 成功（清空输入+草稿）；reject = 失败（还原
   * 草稿为发送前文本，错误提示由调用方呈现）。
   */
  onSend: (text: string) => Promise<void>;
  /** 斜杠命令名（commands 端点 slash_commands）。 */
  slashCommands: string[];
  /** skill 名（commands 端点 skills）。 */
  skills: string[];
  /** 项目文件相对路径（files 端点）。 */
  files: string[];
}

export function useComposerState({
  project,
  sending,
  disabled,
  onSend,
  slashCommands,
  skills,
  files,
}: UseComposerStateArgs) {
  const [input, setInput] = useState(() => readDraft(project));
  const [isTextareaExpanded, setIsTextareaExpanded] = useState(false);

  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const inputHighlightRef = useRef<HTMLDivElement>(null);
  const textareaLineHeightRef = useRef<number | null>(null);
  const lastAutosizedInputRef = useRef<string | null>(null);
  const inputValueRef = useRef(input);
  // sending/disabled 镜像进 ref：handleSubmit 经键盘事件触发，闭包里的
  // state 可能是上一渲染的旧值——并发防重/终态禁用必须读实时值。
  const sendingRef = useRef(sending);
  const disabledRef = useRef(disabled);
  sendingRef.current = sending;
  disabledRef.current = disabled;

  // ── 草稿持久化（spec：切页签/路由/刷新保留；发送成功清除） ──
  useEffect(() => {
    setInput(readDraft(project));
    inputValueRef.current = readDraft(project);
  }, [project]);

  useEffect(() => {
    inputValueRef.current = input;
    if (input !== '') {
      writeDraft(project, input);
    } else {
      clearDraft(project);
    }
  }, [input, project]);

  // ── 补全 hooks（数据源 props 注入） ──
  const commands = useMemo(
    () => toSlashCommands(slashCommands, skills),
    [slashCommands, skills],
  );
  const slash = useSlashCommands({
    commands,
    historyProjectKey: project,
    input,
    setInput,
    textareaRef,
  });

  const mentions = useFileMentions({
    files,
    input,
    setInput,
    textareaRef,
  });

  // ── textarea 高度自适应 + overlay 滚动同步 ──
  const syncInputOverlayScroll = useCallback((target: HTMLTextAreaElement) => {
    if (!inputHighlightRef.current || !target) {
      return;
    }
    inputHighlightRef.current.scrollTop = target.scrollTop;
    inputHighlightRef.current.scrollLeft = target.scrollLeft;
  }, []);

  const resizeTextarea = useCallback((target: HTMLTextAreaElement) => {
    target.style.height = 'auto';
    const nextHeight = Math.max(22, target.scrollHeight);
    target.style.height = `${nextHeight}px`;

    let lineHeight = textareaLineHeightRef.current;
    if (!lineHeight) {
      lineHeight = parseInt(window.getComputedStyle(target).lineHeight, 10);
      textareaLineHeightRef.current = Number.isFinite(lineHeight) ? lineHeight : 24;
    }

    const expanded = nextHeight > (textareaLineHeightRef.current || 24) * 2;
    setIsTextareaExpanded((previous) =>
      previous === expanded ? previous : expanded,
    );
    lastAutosizedInputRef.current = target.value;
  }, []);

  // ── 发送（D3 单点） ──
  const handleSubmit = useCallback(async () => {
    const currentInput = inputValueRef.current;
    if (!currentInput.trim() || sendingRef.current || disabledRef.current) {
      return; // 空文本 / 并发防重（spec：在途 MUST NOT 二次请求）/ 终态禁用
    }
    const previousInput = currentInput;
    try {
      await onSend(currentInput);
    } catch (error) {
      // 失败还原草稿（spec：发送失败时输入内容还原为发送前状态）。
      // 空文本判定前置 guard 后，previousInput 非空——直接还原。
      setInput(previousInput);
      inputValueRef.current = previousInput;
      throw error instanceof Error ? error : new Error(String(error));
    }

    // 成功：清空输入 + 草稿 + 菜单态 + 高度
    setInput('');
    inputValueRef.current = '';
    slash.resetCommandMenuState();
    setIsTextareaExpanded(false);
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto';
    }
  }, [onSend, slash]);

  // ── 输入事件 ──
  const handleInputChange = useCallback(
    (event: ChangeEvent<HTMLTextAreaElement>) => {
      const newValue = event.target.value;
      const cursorPos = event.target.selectionStart;

      setInput(newValue);
      inputValueRef.current = newValue;
      mentions.setCursorPosition(cursorPos);

      if (!newValue.trim()) {
        event.target.style.height = 'auto';
        setIsTextareaExpanded(false);
        slash.resetCommandMenuState();
        return;
      }

      slash.handleCommandInputChange(newValue, cursorPos);
    },
    [mentions, slash],
  );

  const handleKeyDown = useCallback(
    (event: KeyboardEvent<HTMLTextAreaElement>) => {
      // 补全菜单优先消费键盘（↑↓/Tab/Enter/Esc 选中候选且不误发送）
      if (slash.handleCommandMenuKeyDown(event)) {
        return;
      }
      if (mentions.handleFileMentionsKeyDown(event)) {
        return;
      }

      if (event.key === 'Enter') {
        // IME composing 态 Enter 是候选确认，MUST NOT 发送（spec）
        if (event.nativeEvent.isComposing) {
          return;
        }
        if (!event.shiftKey && !event.ctrlKey && !event.metaKey) {
          event.preventDefault();
          void handleSubmit().catch(() => {
            // 失败已还原草稿；错误提示由 SessionPanel 呈现
          });
        }
      }
    },
    [handleSubmit, mentions, slash],
  );

  const handleTextareaClick = useCallback(
    (event: MouseEvent<HTMLTextAreaElement>) => {
      mentions.setCursorPosition(event.currentTarget.selectionStart);
    },
    [mentions],
  );

  const handleTextareaInput = useCallback(
    (event: FormEvent<HTMLTextAreaElement>) => {
      const target = event.currentTarget;
      resizeTextarea(target);
      mentions.setCursorPosition(target.selectionStart);
      syncInputOverlayScroll(target);
    },
    [mentions, resizeTextarea, syncInputOverlayScroll],
  );

  const handleClearInput = useCallback(() => {
    setInput('');
    inputValueRef.current = '';
    slash.resetCommandMenuState();
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto';
      textareaRef.current.focus();
    }
    setIsTextareaExpanded(false);
  }, [slash]);

  const [isInputFocused, setIsInputFocused] = useState(false);

  // 草稿恢复/程序性 input 变更后重跑自适应（用户打字已在 onInput 里做）
  useEffect(() => {
    if (!textareaRef.current) {
      return;
    }
    if (lastAutosizedInputRef.current === input) {
      return;
    }
    resizeTextarea(textareaRef.current);
  }, [input, resizeTextarea]);

  useEffect(() => {
    if (!textareaRef.current || input.trim()) {
      return;
    }
    textareaRef.current.style.height = 'auto';
    setIsTextareaExpanded(false);
  }, [input]);

  return {
    input,
    setInput,
    textareaRef,
    inputHighlightRef,
    isTextareaExpanded,
    isInputFocused,
    setIsInputFocused,
    handleSubmit,
    handleInputChange,
    handleKeyDown,
    handleTextareaClick,
    handleTextareaInput,
    syncInputOverlayScroll,
    handleClearInput,
    ...slash,
    ...mentions,
  };
}

