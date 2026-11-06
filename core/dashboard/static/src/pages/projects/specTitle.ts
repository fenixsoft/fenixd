// SPEC 中文标题纯逻辑助手（add-spec-chinese-title 任务 2.2/2.4）。
//
// id/name 关系定调（specs/spec-chinese-title）：英文名 = id，中文标题 = name
// 纯展示；标题参与匹配的唯一例外就是列表名称关键字过滤——本模块把该匹配
// 语义单点化，v1 列表（list.tsx）消费，供 node:test 直测（同 qualityGates.ts
// 习语：渲染行为由 npm run build 与浏览器冒烟覆盖）。

/**
 * 名称关键字命中判定：英文名包含匹配之外 OR 命中中文标题
 * （大小写不敏感包含匹配，任一命中即保留该行）。
 *
 * kw 为关键词（空串按不过滤处理，恒 true）；调用方惯例已 trim +
 * toLowerCase（v1 列表 debouncedQ 口径），此处对 kw 再做防御性
 * toLowerCase，标题侧同样折小写比对，两侧大小写形态不敏感。
 * title 缺失（null/undefined/空串）时仅英文名参与——存量无标题 SPEC 的
 * 过滤行为与引入本能力之前完全一致。
 */
export function specKeywordHit(name: string, title: string | null | undefined, kw: string): boolean {
  const needle = kw.toLowerCase();
  if (!needle) return true;
  if (name.toLowerCase().includes(needle)) return true;
  return !!title && title.toLowerCase().includes(needle);
}

/**
 * SPEC 详情标题栏中文副标题组合（add-spec-subtitle-and-row-click 任务 1.3，
 * v2 specDetail 消费）：「中文标题 · branch」中点分隔两侧带空格；branch 空
 * 只显中文标题、title 空维持 branch 单独显示、双空不渲染（返回 undefined，
 * 调用方副标题槽即不渲染）。缺失容错与列表副标题规则一致。
 */
export function combineSpecSubtitle(
  title: string | null | undefined,
  branch: string | null | undefined,
): string | undefined {
  const parts = [title, branch].filter((p): p is string => !!p);
  return parts.length ? parts.join(' · ') : undefined;
}
