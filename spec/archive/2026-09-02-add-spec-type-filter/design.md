## Context

项目视图（`#project/<name>`）的 SPEC 列表由 `core/dashboard/static/app.js` 前端渲染：`/api/specs?project=<name>` 一次性返回该项目的全部 SPEC，前端在 `renderProject()` 中先按 `specFilter`（名称关键字 + 状态）过滤，再交给 `buildSpecRows()` 构建带 fix 树层级（fix-* 挂在基名 SPEC 下）的表格行。过滤为纯前端、跨 2 秒自动刷新保持（`specFilter` 为模块级状态）。

用户面对混排的需求与 `fix-*` 问题时，缺少按类型分开查看的能力。本变更在既有过滤栏增加第三个下拉「全部 / 仅需求 / 仅问题」。

## Goals / Non-Goals

**Goals:**
- 在既有过滤栏加入类型下拉，三个选项行为明确：「全部」保持现状、「仅需求」隐藏 `fix-*`、「仅问题」只显示 `fix-*`
- 与名称、状态过滤 AND 组合；纯前端，无 API 变更；跨自动刷新保持
- 「仅问题」视图保持 fix 树层级（`fix-fix-a` 仍挂在 `fix-a` 下）

**Non-Goals:**
- 不改动服务端 `/api/specs`（不新增 `type` 查询参数）
- 不引入新的 SPEC 命名语义（`fix-` 前缀判定沿用既有 `startsWith('fix-')` 约定）
- 不做分页、虚拟滚动等列表性能改造

## Decisions

### D1: 过滤在既有管线最前端叠加，类型筛选作用于 specs 数组而非表格行

`renderProject()` 现有的过滤管线是 `specs 数组 → specFilter 过滤 → buildSpecRows(fix 树) → 渲染`。类型过滤在数组阶段执行（与 `q`/`status` 同处 `filter()` 闭包），而不是在树构建后逐行隐藏。这样 `buildSpecRows()` 的 fix 树逻辑无需任何改动：被过滤掉的 fix SPEC 从 `specs` 集合中消失，其子树自然不渲染，孤儿行（无父级）也一并剔除；「仅问题」视图下剩余的 fix SPEC 之间仍按既有逻辑建立父子关系并保持缩进层级。

- **备选 A**：树构建后按行隐藏 → 需同步处理缩进与孤儿占位行，且 fix 子树仍会残留，复杂度高，否决。
- **备选 B**：服务端加 `?type=` 参数 → 触碰 API 契约，而该过滤纯为展示关注点，且每次切换重新请求，否决。

### D2: 类型状态为 `specFilter.type`，取值 `''`（全部）/ `req`（仅需求）/ `issue`（仅问题）

复用模块级 `specFilter` 对象（app.js:80），新增 `type` 键与 `q`/`status` 并列，天然获得跨自动刷新的保持能力（刷新只重渲染表格，不重置状态）。过滤谓词：

- `req`：排除 `s.name.startsWith('fix-')`
- `issue`：仅保留 `s.name.startsWith('fix-')`
- `''`：不过滤

与既有过滤合并为一个闭包，三条件 AND。

- **备选**：独立于 `specFilter` 的单独状态变量 → 自动刷新时需额外处理回填/保持，且与「全部默认」的两外两个下拉行为不一致，否决。

### D3: 空态复用既有文案

过滤后无结果沿用「无匹配的 SPEC」空态（app.js:781 已有 `filtered.length === 0` 分支），不新增文案；「该项目暂无 SPEC」仍只在 `specs.length === 0` 时出现。

## Risks / Trade-offs

- 「仅问题」视图下，若 `fix-a` 的基名 SPEC `a` 不存在于过滤集合中，`fix-a` 会落入既有「无父级」分组（orphan 分支，排在列表末尾并以缩进呈现）→ 该分组展示是既有设计，可在实现后于任务验证环节确认视觉可接受，必要时微调分组说明文案
- 过滤栏控件增至 3 个（输入框 + 两个下拉），小屏可能换行 → 复用 `.spec-filter` 现有布局，验证时检查小屏表现，必要时补充样式
- `fix-` 前缀判定从 `buildSpecRows` 内已存在的 `isFix` 闭包外移到过滤谓词，两处需保持一致（均为 `startsWith('fix-')`）→ 仅一处使用同一判定语义，实现时直接内联同构判断即可

## Migration Plan

纯前端增量改动，无数据迁移、无后端变更、无部署顺序约束。直接随 NEXT 发布会话交付。

## Open Questions

无。