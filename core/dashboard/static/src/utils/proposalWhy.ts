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
  // 段界探测围栏感知（code-review item cc7049690387）：Why 区块可能贴含行首
  // 「## 」的代码围栏示例，裸 /^##\s/ 会在围栏内第一个二级标题处提前截断——
  // 逐行跟踪 ``` / ~~~ 围栏开合，仅在围栏外匹配下一个二级标题
  // （与 pm_engine/family.py _inject_verify_fix_task 同口径）。
  let fenceChar = "";
  let fenceLen = 0;
  for (let i = start; i < lines.length; i++) {
    const stripped = lines[i].trim();
    if (fenceChar) {
      // 闭栏：同字符、长度不小于开栏的裸标记行（不得带 info 串）
      if (
        stripped.length >= fenceLen &&
        stripped.split("").every((c) => c === fenceChar)
      ) {
        fenceChar = "";
      }
    } else if (stripped.startsWith("```") || stripped.startsWith("~~~")) {
      fenceChar = stripped[0];
      let run = 0;
      while (run < stripped.length && stripped[run] === fenceChar) run++;
      fenceLen = run;
    } else if (/^##\s/.test(lines[i])) {
      break; // 下一个二级标题即段尾（### 子标题不影响）
    }
    collected.push(lines[i]);
  }
  const text = collected.join('\n').trim();
  return text || null;
}

const whyCache = new Map<string, { status: 'loading' | 'done' | 'empty'; promise?: Promise<string | null>; text?: string; cachedAt?: number }>();

// done/empty 结果的缓存有效期：proposal.md 运行期可能被更新（Why 区块新增/改写），
// 过期后重新拉取，避免 SPA 长会话中悬停提示长期展示过期内容。
const WHY_CACHE_TTL_MS = 60 * 1000;
// 容量上限（code-review item d3a693828097）：跨项目跨 spec 悬停浏览会持续新增
// 缓存键，TTL 过期条目仅在同名键再次命中时删除（不再访问的条目永不回收），
// 无上限则 SPA 长驻留会话内存无界增长；对齐 services/dashboard.ts etagCache
// 先例（ETAG_CACHE_MAX），写满按插入序淘汰最旧。
const WHY_CACHE_MAX = 100;

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
      // 回包到达时该键可能已被 TTL 过期后的新请求占位（loading），此时放弃写入，
      // 避免迟到旧回包覆盖新条目、让陈旧文本带着新 cachedAt 重新回潮。
      if (whyCache.get(key)?.promise === p) {
        whyCache.set(key, { status: why ? 'done' : 'empty', text: why || undefined, cachedAt: Date.now() });
      }
      return why;
    })
    .catch(() => {
      // 同理：仅当缓存条目仍是本次请求时才清除，避免误删新请求的在途去重入口。
      if (whyCache.get(key)?.promise === p) {
        whyCache.delete(key); // 失败不缓存，下次自动重试
      }
      return null;
    });
  // 新键写入前写满先淘汰最旧键（Map 保持插入序，首键即最旧）；已存在键覆盖写
  // 不增条数，跳过淘汰以免误伤（口径与 etagCache 一致）。
  if (!whyCache.has(key) && whyCache.size >= WHY_CACHE_MAX) {
    const oldest = whyCache.keys().next().value;
    if (oldest !== undefined) whyCache.delete(oldest);
  }
  whyCache.set(key, { status: 'loading', promise: p });
  return p;
}