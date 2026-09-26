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

const whyCache = new Map<string, { status: 'loading' | 'done' | 'empty'; promise?: Promise<string | null>; text?: string; cachedAt?: number }>();

// done/empty 结果的缓存有效期：proposal.md 运行期可能被更新（Why 区块新增/改写），
// 过期后重新拉取，避免 SPA 长会话中悬停提示长期展示过期内容。
const WHY_CACHE_TTL_MS = 60 * 1000;

export function fetchProposalWhy(project: string, spec: string): Promise<string | null> {
  const key = `${project}│${spec}`;
  const cached = whyCache.get(key);
  if (cached) {
    if (cached.status === 'loading' && cached.promise) {
      return cached.promise; // 在途请求直接复用，保持并发去重
    }
    if (cached.cachedAt !== undefined && Date.now() - cached.cachedAt < WHY_CACHE_TTL_MS) {
      return Promise.resolve(cached.text || null);
    }
    whyCache.delete(key); // 已过期，当作未命中重新拉取
  }
  const p = getSpecDoc(project, spec, 'proposal')
    .then((d) => {
      const why = d.found ? extractProposalWhy(d.content) : null;
      whyCache.set(key, { status: why ? 'done' : 'empty', text: why || undefined, cachedAt: Date.now() });
      return why;
    })
    .catch(() => {
      whyCache.delete(key); // 失败不缓存，下次自动重试
      return null;
    });
  whyCache.set(key, { status: 'loading', promise: p });
  return p;
}