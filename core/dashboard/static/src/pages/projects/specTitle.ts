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

// combineSpecSubtitle（add-spec-subtitle-and-row-click 1.3 中文标题 · branch
// 组合）已于 2026-11-07 随 v2 界面域退役删除——唯一消费方 pages/v2/specDetail
// 消失后按死代码清理；详情页下方行走 richTitle 内部自拼形态。
