## Context

三类实测问题（2026-09-07 playwright 390×844）：触控目标（「更多」「文档」等小字链接 <44px）、detail 头部三层堆叠（顶栏全局面包屑 = app.tsx L73–76 `HeaderCrumb` 经 `actionsRender` 注入，页面级面包屑已 `breadcrumbRender={false}` 关闭）、运维记录单卡 markdown 全文展开（整页 8646px）。

既有先例：手写折叠（detail.tsx spec-detail-alert 自定义折叠，避免每页 15 个 antd Collapse 实例的 DOM/动画开销）；CSS 渐隐 mask；移动端 CSS 作用域约定 `#root :is(.screen-xs, .screen-sm)`（spec A 确立）。

## Goals / Non-Goals

**Goals:**
- 四处小字链接命中区 ≥32px 且视觉零变化
- detail 移动端头部压缩为两层（返回+标题 / Tag 行）
- 运维记录长摘要移动端默认折叠、安全信息不折叠、SSE 不串卡
- PC 端全部现状不变（面包屑可见、全文展开、无工具类）

**Non-Goals:**
- 不做底部导航栏改造（页面数少，顶栏汉堡菜单够用，改造成本高）
- 不改运维记录 PC 端信息架构
- 不处理触控间距新规（相邻可点元素间距由现有 Space/gap ≥8 保证）

## Decisions

1. **touch-expand 采用 padding 8px + 负 margin -8px**：命中区扩到 ≥32px（AA 最低 24 的 1.33 倍）同时负 margin 完全抵消，视觉/布局零变化；不追求 44px 避免卡片行高跳动。工具类一次定义四处落地。
2. **「查看处置过程」按钮内联 `padding:0, height:'auto'` 冲突**：实施时改为兼容形式（去内联 padding 或移到类外按需覆盖），以 devtools 实测命中区为准。
3. **面包屑隐藏走 CSS（`display:none`）而非 app.tsx 条件渲染**：layout 运行时配置无断点响应式重算的可靠钩子，CSS 作用域是最稳路径；HeaderCrumb 加 className 作锚点。
4. **activities 折叠用手写 max-height + 渐隐 mask，不用 antd Collapse**：15 卡 = 15 个 Collapse 实例（DOM+动画+自带 header 结构）过重；max-height 方案不截断 markdown 源文本（按字符截断会切坏语法）。折叠阈值 300 字符 + `isMobile` 双条件，桌面恒 false 输出与现状一致。
5. **isMobile 页面级持有下传**（ActivityTimeline → ActivityCard 各加一个 prop）：与 detail.tsx L508 页面级持有范式一致，避免每卡一个 matchMedia 监听器。
6. **Timeline items 补 `key={a.id}`**：现状缺失，React 位置复用导致展开态可能串卡，属顺手修复。

## Risks / Trade-offs

- [折叠态下用户误以为内容缺失] → 渐隐 mask + 「展开全文」按钮双提示；安全信息永不折叠兜底。
- [SSE 高频推送下展开态管理] → useState 展开态 + 稳定 key 已覆盖；若实测仍有异常，升级为按记录 id 的受控展开集合。
- [三 spec 并行触碰 global.less / ProjectCards.tsx] → 本 spec 对 global.less 仅尾部追加；对 ProjectCards.tsx 仅 2 处 className（与 spec B 的 1 处不同 hunk），git 可自动合并。

## Migration Plan

单 commit 落地，`max build` 后 :8787 实时生效。回滚 = revert。

## Open Questions

（无）
