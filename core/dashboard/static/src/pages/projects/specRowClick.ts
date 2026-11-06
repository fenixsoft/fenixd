// SPEC 列表整行点击导航与事件守卫单源（add-spec-subtitle-and-row-click
// 任务 2.1/3.2）。守卫语义（specs/dashboard-spec-table「整行点击进详情」）：
// 行内既有交互 MUST NOT 被行点击吞并——展开钮命中不导航；操作列单元格既有
// stopPropagation 守卫（list.tsx 零改动命中）；展开行内容渲染于行外
// ant-table-expanded-row，天然不在 onRow 命中面；名称链接自有跳转与行导航
// 同目标不拦截（连跳同路由无害）。node:test 直测（同 specTitle.ts 习语）。
import type { MouseEvent } from 'react';

/** 展开钮判定锚：fix-* 树展开与 error 信息行展开共用 antd 展开图标类。 */
export const ROW_EXPAND_ICON_SELECTOR = '.ant-table-row-expand-icon';

/**
 * 行点击守卫：事件目标命中展开钮（含其内部 svg/path，closest 沿冒泡链向上
 * 判定）时返回 true，调用方 SHALL 跳过行级导航。target 缺失/非元素节点
 * （合成事件、文本节点）按不命中处理，不吞导航。
 */
export function rowClickHitsExpandIcon(event: MouseEvent<HTMLElement>): boolean {
  const target = event.target as HTMLElement | null;
  return !!target?.closest?.(ROW_EXPAND_ICON_SELECTOR);
}

/**
 * SPEC 详情路由路径单源：项目名/SPEC 名源于目录名不限字符集，含 #/?/% 时
 * 裸拼接会路由错乱（# 截断为 hash），统一经 encodeURIComponent（与
 * index.tsx 路由表、SpecNameCell 既有跳转同形口径）。
 */
export function specDetailPath(project: string, name: string): string {
  return `/projects/${encodeURIComponent(project)}/${encodeURIComponent(name)}`;
}
