// pageTitleBarStore.ts — 统一标题栏注册单源（unified-page-title-bar 1.1/1.2）。
//
// 声明-注册-插槽桥接的 store 半边：页面组件（PageTitleBar）在顶栏壳位把 meta
// 写入本单源，app.tsx 顶栏插槽（PageTitleBarHeaderSlot / PageTitleBarFiltersSlot）
// 经 useSyncExternalStore 订阅消费。模块级单例即单源——单 layout 单活跃页，
// 任一时刻至多一个页面持注册。
//
// 与 UI 解耦成纯 TS（零 JSX 零 React 依赖）：node 测试环境 type-stripping 直载
// （embedMount.test.mjs 先例），注册/注销/浅比较行为可直接单测。壳位判定、
// effect 生命周期等 React 侧逻辑留在 PageTitleBar.tsx，由源码扫描守卫
// （tests/pageTitleBar.test.mjs）+ playwright 实拍覆盖。

import type { ReactNode } from 'react';

/** 统一标题栏四槽位声明（页面侧唯一 API 形态）。 */
export interface PageTitleBarMeta {
  /** 标题（18px/700）；富标题（返回+Tag+下拉组合）作为 ReactNode 整体传入，控件透明不拆解。 */
  title: ReactNode;
  /** 副标题（12px 三级灰、与标题基线对齐）；缺省不渲染副标题槽位。 */
  subtitle?: ReactNode;
  /** 返回箭头回调；缺省不渲染箭头。 */
  back?: () => void;
  /** 过滤项（落位由壳位决定：顶栏右上角 / 行壳位行右端）；缺省右上角为空。 */
  filters?: ReactNode;
}

let registeredMeta: PageTitleBarMeta | null = null;
const listeners = new Set<() => void>();

function emitChange() {
  listeners.forEach((l) => l());
}

function shallowEqualMeta(a: PageTitleBarMeta, b: PageTitleBarMeta): boolean {
  return a.title === b.title && a.subtitle === b.subtitle && a.back === b.back && a.filters === b.filters;
}

/** 登记当前页 meta（null=注销）。内容同构（浅比较相等）时静默返回不通知——
 *  页面每次渲染新建 JSX 节点引用会让 effect 反复重跑，不抑制即成渲染环；
 *  同构时连引用也不换：getSnapshot（getPageTitleBarMeta）须引用稳定
 *  （useSyncExternalStore 契约，React 提交后以 Object.is 复查快照，换引用
 *  即触发插槽无意义重渲染）。浅比较覆盖 meta 全部四字段，内容真变（任一
 *  字段引用不同）必走通知路径不会被吞。 */
export function setPageTitleBarMeta(meta: PageTitleBarMeta | null) {
  if (meta === registeredMeta) return;
  if (meta !== null && registeredMeta !== null && shallowEqualMeta(meta, registeredMeta)) {
    return;
  }
  registeredMeta = meta;
  emitChange();
}

export function subscribePageTitleBar(listener: () => void) {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

export function getPageTitleBarMeta(): PageTitleBarMeta | null {
  return registeredMeta;
}
