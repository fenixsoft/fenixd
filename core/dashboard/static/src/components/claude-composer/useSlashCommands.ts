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
  applyCommandInsertion,
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
  // 频次写盘版本号：trackCommandUsage 只落 localStorage、不改 commands 引用，
  // frequent 的 useMemo 需要靠它感知历史变化并即时重算（否则频次面板长期陈旧）。
  const [historyVersion, setHistoryVersion] = useState(0);
  const [commandQuery, setCommandQuery] = useState('');
  const [selectedCommandIndex, setSelectedCommandIndex] = useState(-1);
  const [slashPosition, setSlashPosition] = useState(-1);

  // commands 引用变化（父组件重拉）时同步重排频次——排一次即可，过滤在查询侧做。
  const historyRef = useRef<Record<string, number>>({});
  const sortedCommands = useMemo(
    () => {
      // 渲染期读盘（localStorage）+ 写 historyRef 是受控幂等副作用：同 key 重复
      // 渲染读到同一份历史，排序结果稳定；移入 useEffect 会改变首帧 sortedCommands
      // 排序并多一次重排渲染，故有意保留在 memo 内，勿误改为 effect。
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
    [sortedCommands, historyVersion],
  );

  const trackCommandUsage = useCallback(
    (command: SlashCommand) => {
      const history = readCommandHistory(historyProjectKey);
      history[command.name] = (history[command.name] || 0) + 1;
      saveCommandHistory(historyProjectKey, history);
      // 同步内存副本并 bump 版本号，frequent 面板与 localStorage 即时同步
      historyRef.current = history;
      setHistoryVersion((version) => version + 1);
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
      // 新输入与光标位计算抽到 composerLogic.applyCommandInsertion（纯逻辑
      // node --test 直测）；code-review item 660693cb4a10：斜杠与空格之间
      // 夹换行时尾段按首个 \s 切分，换行后的既有文本不再被静默丢弃。
      const { text: newInput, cursor: nextCursorPosition } = applyCommandInsertion(
        input,
        command.name,
        insertionStart,
        currentTextarea?.selectionEnd ?? insertionStart,
        slashPosition >= 0,
      );

      setInput(newInput);
      resetCommandMenuState();

      window.requestAnimationFrame(() => {
        currentTextarea?.focus();
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
    // 按钮开关路径同样取消在途查询 debounce（code-review item 00b49c1b3385，
    // 与 resetCommandMenuState 同口径）：输入 /x 后 150ms 内快速关开菜单，
    // pending 回调到期会以旧查询词覆盖打开时设置的全量候选集。
    commandQueryDebounce.cancel();
    setShowCommandMenu(isOpening);
    setCommandQuery('');
    setSelectedCommandIndex(-1);

    if (isOpening) {
      setFilteredCommands(sortedCommands);
    }

    textareaRef.current?.focus();
  }, [showCommandMenu, sortedCommands, textareaRef, commandQueryDebounce]);

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
      // IME 组合态按键属于组词操作（Enter 确认候选词 / Esc 取消组合 / ↑↓ 组内
      // 选词），不被候选选中拦截——组合期整体让行 IME（code-review item
      // ec1c3ab24569），与 useFileMentions.handleFileMentionsKeyDown 的守卫
      // 口径一致；否则命令菜单打开时组合期 Enter 会被拦成「插入首个候选命令」。
      if (event.nativeEvent.isComposing) {
        return false;
      }
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
        // filteredCommands 经 effect 重算（debounce 到期 / sortedCommands 引用
        // 变化收缩候选集）时 selectedCommandIndex 不随之收敛，可能越界命中
        // undefined——确认前统一取 picked 守卫：越界不动作，未选中回退首个候选。
        const picked =
          selectedCommandIndex >= 0 ? filteredCommands[selectedCommandIndex] : filteredCommands[0];
        if (picked) {
          // 复用 selectCommand（= handleCommandSelect，isHover=false）走
          // trackCommandUsage + 插入，与鼠标点击路径的频次记录口径一致
          // （code-review item 2464aa93c426：键盘确认此前绕过频次历史，
          // 常用命令面板低估键盘用户的真实使用频次）。
          selectCommand(picked, selectedCommandIndex, false);
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
      selectCommand,
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
