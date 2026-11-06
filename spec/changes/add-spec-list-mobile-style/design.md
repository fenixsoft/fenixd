# Design: add-spec-list-mobile-style

## Context

桌面 SPEC 列表已迁移 v2 台账形态（语义胶囊 + 阶段进度版式 + Bento 磁贴，2026-11-06），移动端卡片形态仍是旧字段直排。本次按已批准原型（specs/dashboard-spec-table/prototype/index.html，vendor 层真组件、具约束力）重绘移动卡与筛选编排，桌面零改动。设计约束以 DESIGN.md 为准（当前摘录注入原型生成）。

## Goals

- 移动端信息层级与触控体验对齐桌面台账语态（同构不同形）
- 桌面零回归；SSE 增量 patch 下卡片按 rowKey 复用语义不变
- 原型定稿即实现基准（UI 真相源绑定）

## Decisions

- **D1 卡列表语态 = 台账磁贴**：整页一张白磁贴（12px 圆角发丝边）内发丝线分卡，镜像桌面 `.ov-bento` 磁贴语态，不逐卡开卡框（信息密度优先）。
- **D2 胶囊色对镜像 v2**：状态/等待/模式胶囊取 STATUS_META tone × v2 软底色对（同桌面列 Pill 单源），移动端不另造色。
- **D3 终态紧凑化与草稿「—」**：终态卡省略 100% 进度条（重复信息）；草稿/无计数显「—」（宪法 0 与口径不可得分离）——两处均为密度设计决策，原型已批准。
- **D4 筛选渐进披露**：高频的状态筛选外露为横滚 chips（激活黑底白字，overview Radio 惯例）；低频的类型/归档/排序收底部 Drawer；排序键集合与桌面表头一致。
- **D5 分页**：「加载更多」+ 计数 caption 替代 antd 分页器（pageSize 20 语义保持，数据层分页不变）。
- **D6 样式落点**：卡片样式走 JSX 内联（现产移动卡同款习语），不新增 less；#E3E3E3 落 theme.ts 单源常量（消费点仅本页内容区）。
- **D7 守卫随改**：`specTitleSubtitle.test.mjs`「桌面表格与移动卡片共用 SpecNameCell」锚在移动卡改版后失真（新卡自绘英文名+中文标题行），随本 SPEC 改钉——桌面列锚不动，移动卡锚改钉新结构（英文名主行/中文标题次行/胶囊行）；桌面零回归由同文件既有桌面锚继续钉住。

## 偏离声明（DESIGN.md 治理）

- **偏离条目**：内容区背景色 `#E3E3E3`——不在宪法 token 表内。
- **理由**：2026-11-06 用户原型批注明示指定（「内容区域的背景色设置为 #E3E3E3」）。
- **适用范围**：仅 SPEC 列表页移动端内容区（<768px），桌面不改。
- **收口**：实现落 theme.ts 单源常量并在 DESIGN.md 修正案登记该色值条款（缺登记 = 审计违规）。

## Risks

- SSE patch 高频刷新下卡片重渲染开销：沿用 rowKey 身份复用（既有 List rowKey 单源），不自引入索引复用。
- chips 横滚行与 Drawer 的 antd v6 弃用参数（如 Drawer `height`）——实现按 antd 6.6 现行 API（styles.wrapper）。
- 移动端进度 ramp 色条与桌面列配色漂移——两处共用 progressPhase 单源，禁止移动端另写色值表。
