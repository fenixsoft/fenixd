// CommandMenu — 斜杠命令补全菜单（add-session-composer 2.4）。
// 迁移自 claudecodeui CommandMenu.tsx：portal 到 body、fixed 定位、桌面左对齐
// 锚定 <输入区上方、<640px 全宽贴输入区下缘上方（spec：移动端补全菜单全宽
// 锚定于输入区上方）。lucide 图标换 @ant-design/icons，分组文案改中文常量
// （D8：不引入 react-i18next）。
// portal 弹层挂 .fenix-composer-portal 注入 HSL 语义变量（tailwind 语义色
// 依赖，面板内变量在 .claude-msg-pane、portal 到 body 后缺失——见 composer.css）。
import { useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import type { CSSProperties, ComponentType, ReactElement } from 'react';
import {
  CodeOutlined,
  EnterOutlined,
  FolderOutlined,
  MessageOutlined,
  StarOutlined,
  ThunderboltOutlined,
  UserOutlined,
} from '@ant-design/icons';

import type { SlashCommand } from './useSlashCommands';

type CommandMenuCommand = SlashCommand & {
  metadata?: { type?: string; [key: string]: unknown };
  [key: string]: unknown;
};

type CommandMenuProps = {
  commands?: CommandMenuCommand[];
  selectedIndex?: number;
  onSelect?: (command: CommandMenuCommand, index: number, isHover: boolean) => void;
  onClose: () => void;
  position?: { left: number; bottom?: number };
  isOpen?: boolean;
  frequentCommands?: CommandMenuCommand[];
};

type CommandMenuRow = {
  command: CommandMenuCommand;
  commandIndex: number;
  renderKey: string;
};

const menuBaseStyle: CSSProperties = {
  maxHeight: '360px',
  overflowY: 'auto',
  borderRadius: '8px',
  boxShadow: '0 24px 60px rgba(2, 6, 23, 0.18), 0 0 0 1px rgba(148, 163, 184, 0.12)',
  zIndex: 1000,
  padding: '6px',
  backdropFilter: 'blur(12px)',
};

// D8：中文常量替换 react-i18next 文案
const namespaceLabels: Record<string, string> = {
  frequent: '常用',
  builtin: '内置命令',
  skill: 'Skills',
  project: '项目命令',
  user: '用户命令',
  other: '其他命令',
};

type IconComponent = ComponentType<{ className?: string }>;

const namespaceIcons: Record<string, IconComponent> = {
  frequent: StarOutlined,
  builtin: CodeOutlined,
  skill: ThunderboltOutlined,
  project: FolderOutlined,
  user: UserOutlined,
  other: MessageOutlined,
};

const namespaceAccentClasses: Record<string, string> = {
  frequent: 'border-amber-200 bg-amber-50 text-amber-700',
  builtin: 'border-sky-200 bg-sky-50 text-sky-700',
  skill: 'border-emerald-200 bg-emerald-50 text-emerald-700',
  project: 'border-indigo-200 bg-indigo-50 text-indigo-700',
  user: 'border-rose-200 bg-rose-50 text-rose-700',
  other: 'border-gray-200 bg-gray-50 text-gray-600',
};

const MENU_EDGE_GAP = 16;
const MENU_MAX_HEIGHT = 360;
const MENU_MIN_HEIGHT = 160;
// 桌面分支菜单宽度与未给 bottom 时的默认锚定间距（code-review item
// 4b90dbe0dd88）：clamp 上限与 width 必须同源，避免只改一处右缘被裁切。
const MENU_WIDTH = 440;
export const DEFAULT_ANCHOR_BOTTOM = 90;

const getCommandKey = (command: CommandMenuCommand) =>
  `${command.name}::${command.namespace || command.type || 'other'}::${command.path || ''}`;

const getNamespace = (command: CommandMenuCommand) =>
  command.namespace || command.type || 'other';

const getNamespaceIcon = (namespace: string) =>
  namespaceIcons[namespace] || namespaceIcons.other;

const getNamespaceAccentClass = (namespace: string) =>
  namespaceAccentClasses[namespace] || namespaceAccentClasses.other;

const getMenuPosition = (position: {
  left: number;
  bottom?: number;
}): CSSProperties => {
  if (typeof window === 'undefined') {
    return { position: 'fixed', top: '16px', left: '16px' };
  }
  const maxAnchorBottom = Math.max(
    MENU_EDGE_GAP,
    window.innerHeight - MENU_EDGE_GAP - MENU_MIN_HEIGHT,
  );
  // 移动端（<640px）：全宽锚定输入区上方（spec：移动端补全菜单全宽锚定）
  if (window.innerWidth < 640) {
    const anchorBottom = Math.min(
      Math.max(MENU_EDGE_GAP, position.bottom ?? DEFAULT_ANCHOR_BOTTOM),
      maxAnchorBottom,
    );
    return {
      position: 'fixed',
      bottom: `${anchorBottom}px`,
      left: '16px',
      right: '16px',
      width: 'auto',
      maxWidth: 'calc(100vw - 32px)',
      maxHeight: `min(54vh, calc(100vh - ${anchorBottom}px - ${MENU_EDGE_GAP}px))`,
    };
  }
  const anchorBottom = Math.min(
    Math.max(MENU_EDGE_GAP, position.bottom ?? DEFAULT_ANCHOR_BOTTOM),
    maxAnchorBottom,
  );
  const clampedLeft = Math.max(
    MENU_EDGE_GAP,
    Math.min(position.left, window.innerWidth - MENU_WIDTH - MENU_EDGE_GAP),
  );

  return {
    position: 'fixed',
    bottom: `${anchorBottom}px`,
    left: `${clampedLeft}px`,
    width: `min(${MENU_WIDTH}px, calc(100vw - 32px))`,
    maxWidth: 'calc(100vw - 32px)',
    maxHeight: `min(${MENU_MAX_HEIGHT}px, calc(100vh - ${anchorBottom}px - ${MENU_EDGE_GAP}px))`,
  };
};

export default function CommandMenu({
  commands = [],
  selectedIndex = -1,
  onSelect,
  onClose,
  position = { left: 0 },
  isOpen = false,
  frequentCommands: frequent = [],
}: CommandMenuProps) {
  const menuRef = useRef<HTMLDivElement | null>(null);
  const selectedItemRef = useRef<HTMLDivElement | null>(null);
  // code-review item d5ad5dadc4a6：menuPosition 基于视口尺寸仅在渲染时计算，
  // resize 时需触发重渲染重算，避免弹层停在基于旧视口的过期位置。
  const [, bumpViewportVersion] = useState(0);
  const menuPosition = getMenuPosition(position);

  useEffect(() => {
    if (!isOpen) {
      return;
    }
    const handleViewportResize = () => bumpViewportVersion((version) => version + 1);
    window.addEventListener('resize', handleViewportResize);
    return () => window.removeEventListener('resize', handleViewportResize);
  }, [isOpen]);

  useEffect(() => {
    if (!isOpen) {
      return;
    }
    const handleClickOutside = (event: MouseEvent) => {
      if (!menuRef.current || !(event.target instanceof Node)) {
        return;
      }
      if (!menuRef.current.contains(event.target)) {
        onClose();
      }
    };
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, [isOpen, onClose]);

  useEffect(() => {
    if (!selectedItemRef.current || !menuRef.current) {
      return;
    }
    const menuRect = menuRef.current.getBoundingClientRect();
    const itemRect = selectedItemRef.current.getBoundingClientRect();
    if (itemRect.bottom > menuRect.bottom || itemRect.top < menuRect.top) {
      selectedItemRef.current.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
    }
  }, [selectedIndex]);

  if (!isOpen) {
    return null;
  }

  const hasFrequentCommands = frequent.length > 0;
  const frequentCommandKeys = new Set(frequent.map(getCommandKey));
  const commandIndexesByKey = new Map<string, number[]>();
  commands.forEach((command, index) => {
    const key = getCommandKey(command);
    const commandIndexes = commandIndexesByKey.get(key) ?? [];
    commandIndexes.push(index);
    commandIndexesByKey.set(key, commandIndexes);
  });
  const frequentCommandOccurrences = new Map<string, number>();
  const getFrequentCommandIndex = (command: CommandMenuCommand): number => {
    const key = getCommandKey(command);
    const occurrence = frequentCommandOccurrences.get(key) ?? 0;
    frequentCommandOccurrences.set(key, occurrence + 1);

    const commandIndexes = commandIndexesByKey.get(key) ?? [];
    return commandIndexes[occurrence] ?? commandIndexes[0] ?? -1;
  };

  const groupedCommands = commands.reduce<Record<string, CommandMenuRow[]>>(
    (groups, command, index) => {
      if (hasFrequentCommands && frequentCommandKeys.has(getCommandKey(command))) {
        return groups;
      }
      const namespace = getNamespace(command);
      if (!groups[namespace]) {
        groups[namespace] = [];
      }
      groups[namespace].push({
        command,
        commandIndex: index,
        renderKey: `${namespace}-${index}-${getCommandKey(command)}`,
      });
      return groups;
    },
    {},
  );
  if (hasFrequentCommands) {
    groupedCommands.frequent = frequent
      .map((command, index) => {
        const commandIndex = getFrequentCommandIndex(command);
        return {
          command,
          commandIndex,
          renderKey: `frequent-${index}-${commandIndex}-${getCommandKey(command)}`,
        };
      })
      .filter((row) => row.commandIndex >= 0);
  }

  const preferredOrder = hasFrequentCommands
    ? ['frequent', 'builtin', 'skill', 'project', 'user', 'other']
    : ['builtin', 'skill', 'project', 'user', 'other'];
  const extraNamespaces = Object.keys(groupedCommands).filter(
    (namespace) => !preferredOrder.includes(namespace),
  );
  const orderedNamespaces = [...preferredOrder, ...extraNamespaces].filter(
    (namespace) => groupedCommands[namespace],
  );
  const renderInPortal = (node: ReactElement) =>
    typeof document === 'undefined' ? node : createPortal(node, document.body);

  if (commands.length === 0) {
    return renderInPortal(
      <div
        ref={menuRef}
        className="fenix-composer-portal command-menu border border-border bg-popover/95 text-sm text-muted-foreground"
        style={{
          ...menuBaseStyle,
          ...menuPosition,
          overflowY: 'hidden',
          padding: '20px',
          textAlign: 'center',
        }}
      >
        无可用命令
      </div>,
    );
  }

  return renderInPortal(
    <div
      ref={menuRef}
      id="command-menu-listbox"
      role="listbox"
      aria-label="可用命令"
      className="fenix-composer-portal command-menu border border-border bg-popover/95 text-popover-foreground"
      style={{ ...menuBaseStyle, ...menuPosition }}
    >
      {orderedNamespaces.map((namespace) => (
        <div key={namespace} className="command-group">
          {orderedNamespaces.length > 1 && (
            <div className="flex items-center justify-between px-2 pb-1.5 pt-2 text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
              <span>{namespaceLabels[namespace] || namespace}</span>
              <span className="rounded border border-border bg-muted px-1.5 py-0.5 text-[10px] text-muted-foreground">
                {(groupedCommands[namespace] || []).length}
              </span>
            </div>
          )}

          {(groupedCommands[namespace] || []).map(
            ({ command, commandIndex, renderKey }) => {
              const isSelected = commandIndex === selectedIndex;
              const NamespaceIcon = getNamespaceIcon(namespace);
              const accentClass = getNamespaceAccentClass(namespace);
              return (
                <div
                  key={renderKey}
                  id={`command-menu-opt-${commandIndex}`}
                  ref={isSelected ? selectedItemRef : null}
                  role="option"
                  aria-selected={isSelected}
                  className={`command-item group relative mb-1 flex cursor-pointer items-start gap-2 rounded-md border px-2.5 py-2 transition-all ${
                    isSelected
                      ? 'border-primary/30 bg-primary/10 shadow-sm'
                      : 'border-transparent bg-transparent hover:border-border hover:bg-accent'
                  }`}
                  onMouseEnter={() =>
                    onSelect && commandIndex >= 0 && onSelect(command, commandIndex, true)
                  }
                  onClick={() =>
                    onSelect && commandIndex >= 0 && onSelect(command, commandIndex, false)
                  }
                  onMouseDown={(event) => event.preventDefault()}
                >
                  {isSelected && (
                    <span className="absolute bottom-1.5 left-1.5 top-1.5 w-0.5 rounded-full bg-primary" />
                  )}
                  <span
                    className={`mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-md border ${accentClass}`}
                  >
                    <NamespaceIcon className="text-[14px]" />
                  </span>
                  <div className="min-w-0 flex-1 pr-1">
                    <div
                      className={`flex min-w-0 items-center gap-2 ${
                        command.description ? 'mb-1' : 'mb-0'
                      }`}
                    >
                      <span
                        className="min-w-0 truncate font-mono text-[13px] font-semibold text-foreground"
                        title={command.name}
                      >
                        {command.name}
                      </span>
                      {command.metadata?.type && (
                        <span className="command-metadata-badge shrink-0 rounded border border-border bg-muted px-1.5 py-0.5 text-[10px] font-medium text-muted-foreground shadow-sm">
                          {command.metadata.type}
                        </span>
                      )}
                    </div>
                    {command.description && (
                      <div
                        className="truncate whitespace-nowrap text-[12px] leading-4 text-muted-foreground"
                        title={command.description}
                      >
                        {command.description}
                      </div>
                    )}
                  </div>
                  {isSelected && (
                    <span className="mt-1 flex h-6 w-6 shrink-0 items-center justify-center rounded border border-primary/30 bg-card text-primary shadow-sm">
                      <EnterOutlined className="text-[13px]" />
                    </span>
                  )}
                </div>
              );
            },
          )}
        </div>
      ))}
    </div>,
  );
}
