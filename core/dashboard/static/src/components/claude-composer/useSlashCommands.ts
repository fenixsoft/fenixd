// useSlashCommands — 斜杠命令/skill 补全 hook（add-session-composer 2.2）。
// 迁移自 claudecodeui useSlashCommands.ts，按 fenixd 场景裁剪：
//  - 候选数据源由端点拉取改为 props 注入（SessionComposer 传入 commands 端点
//    封装的数组，组件内不直接 fetch）；
//  - 选中命令的行为统一为「插入输入框」（fenixd 无本地命令执行端点，未知
//    /命令由 CLI 透传模型并友好降级——已验证前提，无需 builtin/custom 执行链）；
//  - 频次历史按 project 键存 localStorage（command_history_<project>）。
// 保留：150ms debounce（COMMAND_QUERY_DEBOUNCE_MS）、↑↓/Tab/Enter/Esc 键盘
// 导航、代码块内不触发、空候选不弹菜单（spec：无会话 MUST NOT 触发）。
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { Dispatch, KeyboardEvent, RefObject, SetStateAction } from 'react';

import {
  COMMAND_QUERY_DEBOUNCE_MS,
  createTrailingDebounce,
  filterSlashCommands,
  frequentCommands,
  matchSlashTrigger,
  sortCommandsByUsage,
  toSlashCommands,
  type SlashCommand,
} from './composerLogic';
import {
  readCommandHistory,
  saveCommandHistory,
} from './chatStorage';

export { toSlashCommands };
export type { SlashCommand };

interface UseSlashCommandsOptions {
  /** 候选列表（props 注入；空数组 = 无在飞会话/init 未到，不弹菜单）。 */
  commands: SlashCommand[];
  /** 频次 localStorage 的 project 键（command_history_<project>）。 */
  historyProjectKey: string;
  input: string;
  setInput: Dispatch<SetStateAction<string>>;
  textareaRef: RefObject<HTMLTextAreaElement | null>;
}

export function useSlashCommands({
  commands,
  historyProjectKey,
  input,
  setInput,
  textareaRef,
}: UseSlashCommandsOptions) {
  const [filteredCommands, setFilteredCommands] = useState<SlashCommand[]>([]);
  const [showCommandMenu, setShowCommandMenu] = useState(false);
  const [commandQuery, setCommandQuery] = useState('');
  const [selectedCommandIndex, setSelectedCommandIndex] = useState(-1);
  const [slashPosition, setSlashPosition] = useState(-1);

  // commands 引用变化（父组件重拉）时同步重排频次——排一次即可，过滤在查询侧做。
  const historyRef = useRef<Record<string, number>>({});
  const sortedCommands = useMemo(
    () => {
      historyRef.current = readCommandHistory(historyProjectKey);
      return sortCommandsByUsage(commands, historyRef.current);
    },
    [commands, historyProjectKey],
  );

  const debounceRef = useRef<ReturnType<typeof createTrailingDebounce> | null>(null);
  if (debounceRef.current === null) {
    debounceRef.current = createTrailingDebounce((query: string) => {
      setCommandQuery(query);
    }, COMMAND_QUERY_DEBOUNCE_MS);
  }
  const commandQueryDebounce = debounceRef.current;

  const resetCommandMenuState = useCallback(() => {
    setShowCommandMenu(false);
    setSlashPosition(-1);
    setCommandQuery('');
    setSelectedCommandIndex(-1);
    commandQueryDebounce.cancel();
  }, [commandQueryDebounce]);

  useEffect(() => {
    if (!showCommandMenu) {
      setSelectedCommandIndex(-1);
    }
  }, [showCommandMenu]);

  useEffect(() => {
    setFilteredCommands(filterSlashCommands(sortedCommands, commandQuery));
  }, [commandQuery, sortedCommands]);

  const frequent = useMemo(
    () => frequentCommands(sortedCommands, historyRef.current),
    [sortedCommands],
  );

  const trackCommandUsage = useCallback(
    (command: SlashCommand) => {
      const history = readCommandHistory(historyProjectKey);
      history[command.name] = (history[command.name] || 0) + 1;
      saveCommandHistory(historyProjectKey, history);
    },
    [historyProjectKey],
  );

  const insertCommandIntoInput = useCallback(
    (command: SlashCommand) => {
      const currentTextarea = textareaRef.current;
      const insertionStart =
        slashPosition >= 0
          ? slashPosition
          : currentTextarea?.selectionStart ?? input.length;
      const textBeforeCommand = input.slice(0, insertionStart);
      const textAfterCommandStart = input.slice(insertionStart);
      const spaceIndex = textAfterCommandStart.indexOf(' ');
      const textAfterCommand =
        slashPosition >= 0 && spaceIndex !== -1
          ? textAfterCommandStart.slice(spaceIndex).trimStart()
          : input.slice(currentTextarea?.selectionEnd ?? insertionStart);
      const separator =
        textBeforeCommand && !/\s$/.test(textBeforeCommand) ? ' ' : '';
      const newInput = `${textBeforeCommand}${separator}${command.name}${textAfterCommand ? ` ${textAfterCommand}` : ' '}`;

      setInput(newInput);
      resetCommandMenuState();

      window.requestAnimationFrame(() => {
        currentTextarea?.focus();
        const nextCursorPosition = `${textBeforeCommand}${separator}${command.name} `.length;
        currentTextarea?.setSelectionRange(nextCursorPosition, nextCursorPosition);
      });
    },
    [input, resetCommandMenuState, setInput, slashPosition, textareaRef],
  );

  const selectCommand = useCallback(
    (command: SlashCommand | null, index: number, isHover: boolean) => {
      if (!command) {
        return;
      }
      if (isHover) {
        setSelectedCommandIndex(index);
        return;
      }
      trackCommandUsage(command);
      insertCommandIntoInput(command);
    },
    [trackCommandUsage, insertCommandIntoInput],
  );

  const handleToggleCommandMenu = useCallback(() => {
    const isOpening = !showCommandMenu;
    if (isOpening && sortedCommands.length === 0) {
      // 空候选（无在飞会话 / init 未到）不弹菜单（spec：MUST NOT 出现补全菜单）
      return;
    }
    setShowCommandMenu(isOpening);
    setCommandQuery('');
    setSelectedCommandIndex(-1);

    if (isOpening) {
      setFilteredCommands(sortedCommands);
    }

    textareaRef.current?.focus();
  }, [showCommandMenu, sortedCommands, textareaRef]);

  const handleCommandInputChange = useCallback(
    (newValue: string, cursorPos: number) => {
      if (!newValue.trim()) {
        resetCommandMenuState();
        return;
      }
      if (sortedCommands.length === 0) {
        resetCommandMenuState();
        return;
      }

      const textBeforeCursor = newValue.slice(0, cursorPos);
      const match = matchSlashTrigger(textBeforeCursor);
      if (!match) {
        resetCommandMenuState();
        return;
      }

      setSlashPosition(match.position);
      setShowCommandMenu(true);
      setSelectedCommandIndex(-1);

      commandQueryDebounce.call(match.query);
    },
    [resetCommandMenuState, commandQueryDebounce, sortedCommands.length],
  );

  const handleCommandMenuKeyDown = useCallback(
    (event: KeyboardEvent<HTMLTextAreaElement>): boolean => {
      if (!showCommandMenu) {
        return false;
      }

      if (!filteredCommands.length) {
        if (event.key === 'Escape') {
          event.preventDefault();
          resetCommandMenuState();
          return true;
        }
        return false;
      }

      if (event.key === 'ArrowDown') {
        event.preventDefault();
        setSelectedCommandIndex((previousIndex) =>
          previousIndex < filteredCommands.length - 1 ? previousIndex + 1 : 0,
        );
        return true;
      }

      if (event.key === 'ArrowUp') {
        event.preventDefault();
        setSelectedCommandIndex((previousIndex) =>
          previousIndex > 0 ? previousIndex - 1 : filteredCommands.length - 1,
        );
        return true;
      }

      if (event.key === 'Tab' || event.key === 'Enter') {
        event.preventDefault();
        if (selectedCommandIndex >= 0) {
          insertCommandIntoInput(filteredCommands[selectedCommandIndex]);
        } else if (filteredCommands.length > 0) {
          insertCommandIntoInput(filteredCommands[0]);
        }
        return true;
      }

      if (event.key === 'Escape') {
        event.preventDefault();
        resetCommandMenuState();
        return true;
      }

      return false;
    },
    [
      showCommandMenu,
      filteredCommands,
      resetCommandMenuState,
      insertCommandIntoInput,
      selectedCommandIndex,
    ],
  );

  useEffect(() => commandQueryDebounce.cancel, [commandQueryDebounce]);

  return {
    slashCommandsCount: sortedCommands.length,
    filteredCommands,
    frequentCommands: frequent,
    commandQuery,
    showCommandMenu,
    selectedCommandIndex,
    resetCommandMenuState,
    handleCommandSelect: selectCommand,
    handleToggleCommandMenu,
    handleCommandInputChange,
    handleCommandMenuKeyDown,
  };
}
