// composerLogic — composer 纯文本逻辑（零 React / 零 DOM 依赖）。
// 斜杠触发判定、@ 提及匹配与片段替换、候选过滤与频次排序、尾随 debounce
// 全部收在本模块，供 hooks 消费、也供 node --test 直测
// （core/dashboard/static/tests/session-composer.test.mjs，零依赖 .ts 源直载）。

/** 斜杠候选查询的 debounce 时长（spec：150ms）。 */
export const COMMAND_QUERY_DEBOUNCE_MS = 150;

/** 常用命令展示条数（频次 > 0 的前 N 个）。 */
export const FREQUENT_COMMANDS_LIMIT = 5;

/** @ 提及候选展示上限（spec：top10）。 */
export const FILE_MENTION_LIMIT = 10;

export interface SlashCommandLike {
  name: string;
  description?: string;
}

// ── 候选规整 ─────────────────────────────────────────────────────────────

export interface SlashCommand {
  name: string;
  description?: string;
  namespace?: string;
  type?: 'builtin' | 'skill' | string;
}

/**
 * 把 commands 端点返回的 slash_commands / skills 字符串数组规整为候选对象。
 * CLI init 数组形态不保证带前导斜杠（skills 为裸名），统一补 `/`。
 */
export function toSlashCommands(
  slashCommands: string[],
  skills: string[],
): SlashCommand[] {
  const normalize = (name: string) => (name.startsWith('/') ? name : `/${name}`);
  const builtin = slashCommands.map((name) => ({
    name: normalize(name),
    type: 'builtin' as const,
  }));
  const skillCommands = skills.map((name) => ({
    name: normalize(name),
    namespace: 'skill',
    type: 'skill' as const,
  }));
  return [...builtin, ...skillCommands];
}

// ── 斜杠触发 ─────────────────────────────────────────────────────────────

/** 判定光标前文本是否处于 ``` 代码块内（``` 出现奇数次）。代码块内不触发补全。 */
export function isInsideCodeBlock(textBeforeCursor: string): boolean {
  const backticksBefore = (textBeforeCursor.match(/```/g) || []).length;
  return backticksBefore % 2 === 1;
}

export interface SlashTriggerMatch {
  /** `/` 在完整输入串中的位置。 */
  position: number;
  /** `/` 之后、光标之前的查询词（不含斜杠）。 */
  query: string;
}

/**
 * 斜杠补全触发判定（spec：光标处于行首或空白字符之后时键入 `/` 触发）。
 * 输入为光标前文本；命中返回 `/` 位置与查询词，未命中返回 null。
 */
export function matchSlashTrigger(textBeforeCursor: string): SlashTriggerMatch | null {
  if (!textBeforeCursor.trim()) {
    return null;
  }
  if (isInsideCodeBlock(textBeforeCursor)) {
    return null;
  }
  // 行首或空白之后的 /word（至光标）
  const match = textBeforeCursor.match(/(?:^|\s)(\/\S*)$/);
  if (!match) {
    return null;
  }
  return {
    position: match.index! + (match[0].length - match[1].length),
    query: match[1].slice(1),
  };
}

// ── @ 文件提及 ───────────────────────────────────────────────────────────

export interface FileMentionMatch {
  /** `@` 在完整输入串中的位置。 */
  atIndex: number;
  /** `@` 之后、光标之前的查询词（@ 后出现空白则不触发）。 */
  query: string;
}

/**
 * @ 提及触发判定（spec：光标前最后一个 `@` 且其后无空白时触发；空白口径与
 * matchSlashTrigger 的 `\S` 对齐，@ 后出现换行同样终止触发，避免跨行选中候选
 * 时 replaceFileMention 丢弃换行后的后续文本）。``` 代码块内不触发，与
 * matchSlashTrigger 的补全纪律一致。
 * 输入为光标前文本；未命中返回 null。
 */
export function matchFileMention(textBeforeCursor: string): FileMentionMatch | null {
  if (isInsideCodeBlock(textBeforeCursor)) {
    return null;
  }
  const lastAtIndex = textBeforeCursor.lastIndexOf('@');
  if (lastAtIndex === -1) {
    return null;
  }
  const textAfterAt = textBeforeCursor.slice(lastAtIndex + 1);
  if (/\s/.test(textAfterAt)) {
    return null;
  }
  return { atIndex: lastAtIndex, query: textAfterAt };
}

/**
 * 选中候选文件后替换输入框中的 `@` 片段（spec：`@src` → `@src/app.tsx`，
 * 替换结果保留 `@` 前缀——发送的 text 原样携带 `@路径` 由 CLI 侧展开）。
 * 紧随查询词的一个空白字符（空格或换行）被吞掉（插入文本自带分隔空格），
 * 避免出现双空格；光标落在 `@路径 ` 之后（即尾部文本起始处）。
 * 边界按首个 `\s` 切分而非仅空格：光标落在文本中部插入 `@` 时（after 形如
 * `@\nworld`），若只认空格会得到 -1 并把换行后的既有内容整体静默丢弃。
 */
export function replaceFileMention(
  input: string,
  atIndex: number,
  path: string,
): { text: string; cursor: number } {
  const before = input.slice(0, atIndex);
  const after = input.slice(atIndex);
  const segmentEnd = after.search(/\s/);
  const tail = segmentEnd !== -1 ? after.slice(segmentEnd + 1) : '';
  const text = `${before}@${path} ${tail}`;
  return { text, cursor: before.length + path.length + 2 };
}

// ── 候选过滤 / 排序 ──────────────────────────────────────────────────────

/**
 * 斜杠候选过滤（迁移自 claudecodeui filterSlashCommands）：名称前缀优先，
 * 其次名称子串，最后描述子串；空查询返回全部。
 */
export function filterSlashCommands<T extends SlashCommandLike>(
  commands: T[],
  query: string,
): T[] {
  const normalizedQuery = query.trim().toLowerCase();
  if (!normalizedQuery) {
    return commands;
  }

  const commandPrefix = normalizedQuery.startsWith('/')
    ? normalizedQuery
    : `/${normalizedQuery}`;
  const namePrefixMatches = commands.filter((command) =>
    command.name.toLowerCase().startsWith(commandPrefix),
  );
  if (namePrefixMatches.length > 0) {
    return namePrefixMatches;
  }

  const nameSubstringMatches = commands.filter((command) =>
    command.name.toLowerCase().includes(normalizedQuery),
  );
  if (nameSubstringMatches.length > 0) {
    return nameSubstringMatches;
  }

  return commands.filter((command) =>
    (command.description || '').toLowerCase().includes(normalizedQuery),
  );
}

/** @ 提及候选匹配（文件名或路径子串，大小写不敏感），截取前 FILE_MENTION_LIMIT 条。 */
export function filterMentionableFiles<T extends { name: string; path: string }>(
  files: T[],
  query: string,
): T[] {
  const normalizedQuery = query.toLowerCase();
  return files
    .filter(
      (file) =>
        file.name.toLowerCase().includes(normalizedQuery) ||
        file.path.toLowerCase().includes(normalizedQuery),
    )
    .slice(0, FILE_MENTION_LIMIT);
}

/** 按使用频次降序（history 缺省计 0；稳定排序保持原相对顺序）。 */
export function sortCommandsByUsage<T extends SlashCommandLike>(
  commands: T[],
  history: Record<string, number>,
): T[] {
  return [...commands].sort(
    (a, b) => (history[b.name] || 0) - (history[a.name] || 0),
  );
}

/** 频次 > 0 的前 FREQUENT_COMMANDS_LIMIT 条（附 usageCount）。 */
export function frequentCommands<T extends SlashCommandLike>(
  commands: T[],
  history: Record<string, number>,
): Array<T & { usageCount: number }> {
  return commands
    .map((command) => ({ ...command, usageCount: history[command.name] || 0 }))
    .filter((command) => command.usageCount > 0)
    .sort((a, b) => b.usageCount - a.usageCount)
    .slice(0, FREQUENT_COMMANDS_LIMIT);
}

// ── debounce ─────────────────────────────────────────────────────────────

export interface TrailingDebounce<Args extends unknown[]> {
  call: (...args: Args) => void;
  cancel: () => void;
}

/** 尾随 debounce：连续 call 只保留最后一次，delayMs 后执行。 */
export function createTrailingDebounce<Args extends unknown[]>(
  fn: (...args: Args) => void,
  delayMs: number,
): TrailingDebounce<Args> {
  let timer: ReturnType<typeof setTimeout> | null = null;
  return {
    call: (...args: Args) => {
      if (timer !== null) {
        clearTimeout(timer);
      }
      timer = setTimeout(() => {
        timer = null;
        fn(...args);
      }, delayMs);
    },
    cancel: () => {
      if (timer !== null) {
        clearTimeout(timer);
        timer = null;
      }
    },
  };
}

// ── 命令角标数字封顶 ───────────────────────────────────────────────────────
// 回归 2026-09-25：命令入口按钮角标是 h-4 w-4 小圆标，三位数（79 命令 +
// 49 skill = 128）溢出图标外被裁切。超过上限显示「99+」。

export const COMMAND_COUNT_BADGE_CAP = 99;

/** 角标展示文本：>99 封顶「99+」；NaN/负数归 '0'；小数向下取整。 */
export function formatCommandCount(count: number): string {
  if (!Number.isFinite(count) || count <= 0) {
    return '0';
  }
  const floored = Math.floor(count);
  if (floored > COMMAND_COUNT_BADGE_CAP) {
    return `${COMMAND_COUNT_BADGE_CAP}+`;
  }
  return String(floored);
}
