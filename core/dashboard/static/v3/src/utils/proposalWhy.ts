import { getSpecDoc } from '@/services/dashboard';

// 从 proposal 文档提取 `## Why` 区块（到下一个二级标题为止）。
// spec 列表悬停提示与任务详情页「任务背景描述」共用同一提取逻辑，避免两处漂移。
export function extractProposalWhy(markdown: string): string | null {
  if (!markdown) return null;
  const lines = String(markdown).split('\n');
  let start = -1;
  for (let i = 0; i < lines.length; i++) {
    if (/^##\s+why\s*$/i.test(lines[i])) {
      start = i + 1;
      break;
    }
  }
  if (start === -1) return null;
  const collected: string[] = [];
  for (let i = start; i < lines.length; i++) {
    if (/^##\s/.test(lines[i])) break; // 下一个二级标题即段尾（### 子标题不影响）
    collected.push(lines[i]);
  }
  const text = collected.join('\n').trim();
  return text || null;
}

const whyCache = new Map<string, { status: 'loading' | 'done' | 'empty'; promise?: Promise<string | null>; text?: string }>();

export function fetchProposalWhy(project: string, spec: string): Promise<string | null> {
  const key = `${project}│${spec}`;
  const cached = whyCache.get(key);
  if (cached) {
    return cached.status === 'loading' && cached.promise
      ? cached.promise
      : Promise.resolve(cached.text || null);
  }
  const p = getSpecDoc(project, spec, 'proposal')
    .then((d) => {
      const why = d.found ? extractProposalWhy(d.content) : null;
      whyCache.set(key, { status: why ? 'done' : 'empty', text: why || undefined });
      return why;
    })
    .catch(() => {
      whyCache.delete(key); // 失败不缓存，下次自动重试
      return null;
    });
  whyCache.set(key, { status: 'loading', promise: p });
  return p;
}