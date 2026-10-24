// useFileMentions — @ 文件提及补全 hook（add-session-composer 2.2）。
// 迁移自 claudecodeui useFileMentions.tsx，按 fenixd 场景裁剪：
//  - 候选数据源由树形端点拉取改为 props 注入的扁平相对路径数组（files 端点
//    git ls-files 直出，无需 flattenFileTree）；
//  - 触发判定/片段替换/候选过滤抽到 composerLogic（零依赖，node --test 直测）。
// 保留：光标前最后一个 @ 且其后无空格触发、top10 匹配、选中替换与 overlay
// 着色（renderInputWithMentions）、↑↓/Tab/Enter/Esc 键盘交互。
import { useCallback, useEffect, useMemo, useState } from 'react';
import type { Dispatch, KeyboardEvent, RefObject, SetStateAction } from 'react';

import {
  filterMentionableFiles,
  matchFileMention,
  replaceFileMention,
} from './composerLogic';

export interface MentionableFile {
  name: string;
  path: string;
}

/** 相对路径 → 候选对象（name = 末段，path = 完整相对路径）。 */
export function toMentionableFiles(files: string[]): MentionableFile[] {
  return files.map((path) => {
    const segments = path.split('/');
    return { name: segments[segments.length - 1] || path, path };
  });
}

function escapeRegExp(text: string): string {
  return text.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

interface UseFileMentionsOptions {
  /** 项目文件相对路径数组（props 注入；空数组 = 端点失败/非 git，无候选）。 */
  files: string[];
  input: string;
  setInput: Dispatch<SetStateAction<string>>;
  textareaRef: RefObject<HTMLTextAreaElement | null>;
  /** 下拉容器（SessionComposer 持有的 fileDropdownRef）：容器内点击不算外点。 */
  dropdownRef?: RefObject<HTMLElement | null>;
}

export function useFileMentions({
  files,
  input,
  setInput,
  textareaRef,
  dropdownRef,
}: UseFileMentionsOptions) {
  const fileList = useMemo(() => toMentionableFiles(files), [files]);
  // 会话级累积语义命名（code-review item c9a8ffd19c8f）：只在 selectFile 时
  // 追加、从不清空，「当前仍在输入中的提及」靠下方 includes 过滤取——旧名
  // fileMentions 易误读为当前提及列表
  const [knownFileMentions, setKnownFileMentions] = useState<string[]>([]);
  const [filteredFiles, setFilteredFiles] = useState<MentionableFile[]>([]);
  const [showFileDropdown, setShowFileDropdown] = useState(false);
  const [selectedFileIndex, setSelectedFileIndex] = useState(-1);
  const [cursorPosition, setCursorPosition] = useState(0);
  const [atSymbolPosition, setAtSymbolPosition] = useState(-1);

  useEffect(() => {
    const textBeforeCursor = input.slice(0, cursorPosition);
    const match = matchFileMention(textBeforeCursor);

    if (!match) {
      setShowFileDropdown(false);
      setAtSymbolPosition(-1);
      return;
    }

    setAtSymbolPosition(match.atIndex);
    setShowFileDropdown(true);
    setSelectedFileIndex(-1);
    setFilteredFiles(filterMentionableFiles(fileList, match.query));
  }, [input, cursorPosition, fileList]);

  // code-review item 50f9e8a4159c：外点关闭，与 CommandMenu 的 document
  // mousedown 关闭口径统一——点击 textarea 以外区域即收起（textarea 内点击
  // 不算外点，开闭仍由上方 effect 随输入/光标重算）；下拉候选行的 mousedown
  // 已 preventDefault + stopPropagation（SessionComposer），不冒泡到
  // document，选候选不会被外点逻辑误杀。
  // code-review item 432c294ae05f：下拉容器自身（滚动条/候选行间空白）也是
  // 内点——候选超过 10 条出现滚动条时，拖动滚动条不得立即收起下拉。
  useEffect(() => {
    if (!showFileDropdown) {
      return;
    }
    const handleMouseDownOutside = (event: MouseEvent) => {
      const textarea = textareaRef.current;
      if (!textarea || !(event.target instanceof Node)) {
        return;
      }
      if (
        !textarea.contains(event.target) &&
        !dropdownRef?.current?.contains(event.target)
      ) {
        setShowFileDropdown(false);
      }
    };
    document.addEventListener('mousedown', handleMouseDownOutside);
    return () => document.removeEventListener('mousedown', handleMouseDownOutside);
  }, [showFileDropdown, textareaRef, dropdownRef]);

  const activeFileMentions = useMemo(() => {
    if (!input || knownFileMentions.length === 0) {
      return [];
    }
    // @ 锚定（code-review item efc20c017bbe）：要求路径前紧邻 @，普通位置的
    // 同名子词（后随空格等边界字符）不再被判为提及而误染色
    return knownFileMentions.filter((path) => input.includes(`@${path}`));
  }, [knownFileMentions, input]);

  const sortedFileMentions = useMemo(() => {
    if (activeFileMentions.length === 0) {
      return [];
    }
    const uniqueMentions = Array.from(new Set(activeFileMentions));
    return uniqueMentions.sort((mentionA, mentionB) => mentionB.length - mentionA.length);
  }, [activeFileMentions]);

  const fileMentionRegex = useMemo(() => {
    if (sortedFileMentions.length === 0) {
      return null;
    }
    const pattern = sortedFileMentions.map(escapeRegExp).join('|');
    // @ 锚定 + 边界前瞻（code-review item efc20c017bbe）：仅「@ 紧邻路径」的
    // 真实提及参与染色（捕获片段连 @ 一并高亮），普通位置的子词不再误染；
    // 后向边界前瞻防同前缀更长文件名（a.ts vs a.tsx）的前缀被误染。
    return new RegExp(`(@${pattern})(?![A-Za-z0-9._/-])`, 'g');
  }, [sortedFileMentions]);

  // 分段含 @ 前缀（与 fileMentionRegex 的捕获形态一致），成员判定按 '@'+path
  const fileMentionSet = useMemo(
    () => new Set(sortedFileMentions.map((p) => `@${p}`)),
    [sortedFileMentions],
  );

  // overlay 着色：已提及路径渲染为高亮 span（视觉层；发送仍为原始文本）。
  const renderInputWithMentions = useCallback(
    (text: string) => {
      if (!text) {
        return '';
      }
      if (!fileMentionRegex) {
        return text;
      }

      const parts = text.split(fileMentionRegex);
      return parts.map((part, index) =>
        fileMentionSet.has(part) ? (
          <span
            key={`mention-${index}`}
            className="-ml-0.5 rounded-md bg-blue-200/70 box-decoration-clone px-0.5 text-transparent"
          >
            {part}
          </span>
        ) : (
          <span key={`text-${index}`}>{part}</span>
        ),
      );
    },
    [fileMentionRegex, fileMentionSet],
  );

  const selectFile = useCallback(
    (file: MentionableFile) => {
      const { text: newInput, cursor: newCursorPosition } = replaceFileMention(
        input,
        atSymbolPosition,
        file.path,
      );

      if (textareaRef.current && !textareaRef.current.matches(':focus')) {
        textareaRef.current.focus();
      }

      setInput(newInput);
      setCursorPosition(newCursorPosition);
      setKnownFileMentions((previousMentions) =>
        previousMentions.includes(file.path)
          ? previousMentions
          : [...previousMentions, file.path],
      );

      setShowFileDropdown(false);
      setAtSymbolPosition(-1);

      if (!textareaRef.current) {
        return;
      }

      requestAnimationFrame(() => {
        if (!textareaRef.current) {
          return;
        }
        textareaRef.current.setSelectionRange(newCursorPosition, newCursorPosition);
        if (!textareaRef.current.matches(':focus')) {
          textareaRef.current.focus();
        }
      });
    },
    [input, atSymbolPosition, textareaRef, setInput],
  );

  const handleFileMentionsKeyDown = useCallback(
    (event: KeyboardEvent<HTMLTextAreaElement>): boolean => {
      // IME 组合态按键属于组词操作（Enter 确认拼音 / Esc 取消组合 / ↑↓ 选词），
      // 不被候选选中拦截——组合期整体让行 IME，与 useComposerState 的发送守卫
      // （composing 态 Enter MUST NOT 发送）口径一致。
      if (event.nativeEvent.isComposing) {
        return false;
      }
      if (!showFileDropdown || filteredFiles.length === 0) {
        return false;
      }

      if (event.key === 'ArrowDown') {
        event.preventDefault();
        setSelectedFileIndex((previousIndex) =>
          previousIndex < filteredFiles.length - 1 ? previousIndex + 1 : 0,
        );
        return true;
      }

      if (event.key === 'ArrowUp') {
        event.preventDefault();
        setSelectedFileIndex((previousIndex) =>
          previousIndex > 0 ? previousIndex - 1 : filteredFiles.length - 1,
        );
        return true;
      }

      if (event.key === 'Tab' || event.key === 'Enter') {
        event.preventDefault();
        if (selectedFileIndex >= 0) {
          selectFile(filteredFiles[selectedFileIndex]);
        } else if (filteredFiles.length > 0) {
          selectFile(filteredFiles[0]);
        }
        return true;
      }

      if (event.key === 'Escape') {
        event.preventDefault();
        setShowFileDropdown(false);
        return true;
      }

      return false;
    },
    [showFileDropdown, filteredFiles, selectedFileIndex, selectFile],
  );

  return {
    showFileDropdown,
    filteredFiles,
    selectedFileIndex,
    renderInputWithMentions,
    selectFile,
    setCursorPosition,
    handleFileMentionsKeyDown,
  };
}
