## Context

v3 dashboard（React 19 + antd v6 + UmiJS Max 4）此前已建立移动端适配双轨机制：CSS 轨依赖 ProLayout 根节点自动生成的断点类（`#root .screen-xs`，<576px），JS 轨为 `hooks/useIsMobile.ts`（同步 matchMedia `(max-width: 767.98px)`）。2026-09-07 playwright 实测（390×844 / 600×900 / 1920×1080）确认两个事实：

1. ProLayout 根 div 在 390px 挂 `screen-xs`、600px 挂 `screen-sm`（`global.less` L133–135 旧注释「screen-sm/md/lg 命中不了」有误）。
2. HookManager 三张 Table 无 `scroll.x`：生效合并表 `tableLayout="fixed"` 固定列宽合计 1055px，390px 视口下表格 wrapper 仅 340px，整页 body 被撑到 1080px，全页横滚 ~2.7 屏且同页内容压扁；设置页项目作用域面板同组件同病（列头一字一行竖排 + 38px 溢出）。

既有可复用资产：`pages/projects/list.tsx` 的 SpecCardList（表格→卡片范式，`List.Item` 内 `minWidth:0` div 防 antd List.Item flex 坑）、`useIsMobile`（useState 初始化防首帧闪烁）。

## Goals / Non-Goals

**Goals:**
- 任何视口宽度下 HookManager 三表不得引起整页横向滚动
- <768px 视口下 HookManager 呈现卡片化，字段与交互完整；≥768px 桌面渲染逐字节不变
- 移动端 CSS 作用域与 JS 断点统一到 768px，消除 576–768px 空窗
- 全站 Modal 移动端宽度防御上限

**Non-Goals:**
- 不引入 antd-mobile 或任何新依赖（antd 官方 FAQ 明示未为移动优化，自适配是既定路线）
- 不改桌面端 Table 的列定义与交互路径
- 不处理 spec B/C 范围（概览页、detail 顶部、触控目标、activities 折叠）

## Decisions

1. **断点统一采用 `:is(.screen-xs, .screen-sm)` 而非原生 `@media (max-width: 767.98px)`**：前者沿用仓库既有机制（15 条规则 + 注释心智已付），`:is()` 特异性与并列书写等价，browserslist 全支持；media query 化收益仅是书写简洁，成本是风格漂移。实测已证实 screen-sm 类真实存在，旧注释一并更正。
2. **两步走：先 `scroll={{ x: 'max-content' }}` 兜底，再卡片化**：兜底 3 行改动风险近零，卡片化涉及交互迁移需独立验证；兜底层在卡片化后仍保留（服务 PC 窄窗口场景，1280 笔记本减侧栏内容区 <1055px 时现状本就溢出）。用 `'max-content'` 而非写死 1055：antd 按列宽生成 min-width，列宽日后调整无需同步数字。
3. **卡片化在 HookManager 组件内自持 `useIsMobile()` 分支渲染，而非消费方下传**：两个消费方（detail.tsx、HooksPanel.tsx）接口零改动；useIsMobile 已是同步首帧取值的成熟范式，无闪烁。
4. **卡片结构复用 SpecCardList 范式**：`List.Item` + 内层 `width:'100%', minWidth:0` div（防 antd v6 List.Item flex 坑，list.tsx L357 注释在案）；字段与桌面列一一对应，参数全文 break-all 替代桌面 320px ellipsis（移动端空间宝贵，截断无意义）。
5. **Modal 上限走全站 CSS（`max-width: calc(100vw - 32px)`）而非改 `width` prop**：一条规则全站 Modal（确认弹窗等）受益，纯防御上限不改变 PC 行为。

## Risks / Trade-offs

- [`:is()` 兼容性] → browserslist "last 2 versions" 全支持；如需降级可一键展开为并列选择器。
- [卡片化交互迁移遗漏（Switch 回调、Modal 回填、readOnly）] → 三表卡片字段清单已逐列映射进 specs；验收含启停即保存、弹窗回填、终态只读三个交互场景。
- [三 spec 并行触碰 global.less] → 本 spec 改既有规则选择器（L120–190），spec B/C 为文件尾部追加，git 可自动合并；若 merge-back 冲突按既有 agent 自救 merge main 模式处理。
- [防收工守卫误拦] → tasks.md Deliverables 声明仅含入库的 src 文件（modify），dist 不入库不声明，merge 后框架自动重建。

## Migration Plan

单 commit 落地，无数据迁移。回滚 = revert 该 commit。构建走 `max build`，dist 不入库、:8787 实时读盘，merge 后框架自动重建，无需重启 daemon。

## Open Questions

（无）
