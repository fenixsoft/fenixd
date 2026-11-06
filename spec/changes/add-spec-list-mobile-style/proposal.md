# Proposal: add-spec-list-mobile-style

## Why

SPEC 列表是移动端高频巡检面，现产移动卡片形态沿用桌面列字段的直排堆叠（Badge 色点状态、文档/更多链接按钮平铺、无阶段语义进度），信息层级弱、触控目标散，且与桌面列已迁移的 v2 台账形态（语义胶囊 + 阶段进度版式，2026-11-06）不同构。移动端体验滞后于桌面，需要一次专门的移动样式改版。

## What Changes

- 移动端（<768px）SPEC 卡片列表按已批准原型整体重绘（UI 真相源：`specs/dashboard-spec-table/prototype/index.html`，截图凭证 `mobile-390-full.png`）：
  - 卡片结构：英文名主行（14px/600 单行省略）→ 中文标题次行（12px 三阶灰单行省略）→ 状态/等待/模式语义胶囊行（999 软底带色点，镜像 v2 台账）→ 阶段进度区（阶段名 + 「计数 · 百分比」同行在上、阶段 ramp 色进度条）→ 元信息行（优先级 | 创建时间 | 耗时，tabular-nums；运行态绿点「● 运行中」）→ 验证行（✓/⚠）→ 信息行（amber 软底摘要单行省略）
  - fix-* 子卡缩进 26px + `└` 前缀灰符（树形语义保留）
  - 终态紧凑化：已推送/完成卡省略进度区（不重复画 100% 条）；草稿/无任务计数显「—」（0 与口径不可得分离）
  - 整卡点击进详情（specDetailPath 单源不变）；⋮ 更多菜单（查看文档/调整优先级/冻结，触控目标 32px）
- 移动筛选编排改版：搜索框保留（specKeywordHit 单源命中不变）；状态筛选改横向滚动 chips（激活态黑底白字含计数，镜像 overview Radio 惯例）；类型/归档/排序收进「筛选」底部 Drawer（antd Segmented）；分页改磁贴底部「加载更多」+「共 N 条 · 已显示 M 条」
- 内容区背景色 #E3E3E3（2026-11-06 用户批注指定色值，偏离宪法配色单源条款——见 design.md 偏离声明段，实现落 theme.ts 单源常量并登记 DESIGN.md 修正案）
- 桌面表格零改动（含整行点击、名称列、树形展开、排序、信息子行全部现状）
- 顶栏（页面标题栏）不处理保持现状（用户批注明示）

## Capabilities

### New Capabilities

（无——移动卡片形态属既有能力页 `dashboard-spec-table` 的移动端节改版）

### Modified Capabilities

- `dashboard-spec-table`: SPEC 列表/台账能力——移动端卡片形态与移动筛选编排整节改版（桌面节零改动），守卫 `specTitleSubtitle.test.mjs` 移动卡锚点随改

## Impact

- 代码：`core/dashboard/static/src/pages/projects/list.tsx`（SpecCardList 重绘 + DevTab 移动过滤编排）、`core/dashboard/static/src/theme.ts`（#E3E3E3 单源常量）、`core/dashboard/static/tests/specTitleSubtitle.test.mjs`（移动卡锚点改钉）
- 构建：`core/dashboard/static/dist/index.html`（rebuild，gitignored 构建产物非交付物）
- 交互：移动端 SPEC 列表入口全部改走新卡形态；桌面/PC 零影响
