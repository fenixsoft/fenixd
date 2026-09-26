// chatStorage — composer 的 localStorage 安全封装（add-session-composer 2.1）。
// 迁移自 claudecodeui chatStorage.ts，按 fenixd 场景裁剪：
//  - 只保留「草稿」与「命令使用频次」两类键，均按 project 命名
//    （draft_input_<project> / command_history_<project>），切项目互不串扰；
//  - 排队消息（queued_message_*）与 Claude 设置键属 P2 裁剪项，不迁。
// 超额（QuotaExceededError）时按前缀清空全部草稿/命令频次键（含其他项目草稿与当前写入键，无新旧筛选）后重试一次，与原实现同策略。

const DRAFT_PREFIX = 'draft_input_';
const COMMAND_HISTORY_PREFIX = 'command_history_';

export const draftKey = (project: string) => `${DRAFT_PREFIX}${project}`;
export const commandHistoryKey = (project: string) => `${COMMAND_HISTORY_PREFIX}${project}`;

export const safeLocalStorage = {
  setItem: (key: string, value: string) => {
    try {
      localStorage.setItem(key, value);
    } catch (error) {
      if ((error as { name?: string })?.name === 'QuotaExceededError') {
        console.warn('localStorage quota exceeded, clearing old composer data');

        const keys = Object.keys(localStorage);
        const composerKeys = keys.filter(
          (k) => k.startsWith(DRAFT_PREFIX) || k.startsWith(COMMAND_HISTORY_PREFIX),
        );
        composerKeys.forEach((k) => localStorage.removeItem(k));

        try {
          localStorage.setItem(key, value);
        } catch (retryError) {
          console.error('Failed to save to localStorage even after cleanup:', retryError);
        }
      } else {
        console.error('localStorage error:', error);
      }
    }
  },
  getItem: (key: string): string | null => {
    try {
      return localStorage.getItem(key);
    } catch (error) {
      console.error('localStorage getItem error:', error);
      return null;
    }
  },
  removeItem: (key: string) => {
    try {
      localStorage.removeItem(key);
    } catch (error) {
      console.error('localStorage removeItem error:', error);
    }
  },
};

export function readDraft(project: string): string {
  return safeLocalStorage.getItem(draftKey(project)) || '';
}

export function writeDraft(project: string, text: string): void {
  safeLocalStorage.setItem(draftKey(project), text);
}

export function clearDraft(project: string): void {
  safeLocalStorage.removeItem(draftKey(project));
}

export function readCommandHistory(project: string): Record<string, number> {
  const raw = safeLocalStorage.getItem(commandHistoryKey(project));
  if (!raw) {
    return {};
  }
  try {
    const parsed = JSON.parse(raw);
    if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) {
      // 值类型校验：手改/旧格式残留的非 number 值会让消费方按值排序/比较出 NaN
      // （trackCommandUsage 的 || 0 自增还会字符串拼接），逐条剔除、只留非 NaN number。
      return Object.fromEntries(
        Object.entries(parsed).filter(
          ([, value]) => typeof value === 'number' && !Number.isNaN(value),
        ),
      ) as Record<string, number>;
    }
    return {};
  } catch (error) {
    console.error('Error parsing command history:', error);
    return {};
  }
}

export function saveCommandHistory(project: string, history: Record<string, number>): void {
  safeLocalStorage.setItem(commandHistoryKey(project), JSON.stringify(history));
}
