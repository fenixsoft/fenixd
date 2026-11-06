# dashboard-spec-table（移动端卡片形态与筛选编排改版）

## MODIFIED Requirements

### Requirement: SPEC 列表移动端卡片形态

现产移动卡片（<768px，`SpecCardList`）按已批准原型重绘：卡片信息层级 = 英文名主行 → 中文标题次行 → 语义胶囊行 → 阶段进度区 → 元信息行 → 验证行 → 信息行。桌面表格分支零改动。

界面原型（UI 真相源）：`specs/dashboard-spec-table/prototype/index.html`（截图凭证 `prototype/mobile-390-full.png`）。**界面布局与组件形态以 prototype/ 为准**（冲突须升级用户裁决）；数值与交互语义以本 Scenario 为准。

- **THEN** 卡片承载体为白磁贴（圆角 12px、发丝边框、卡间发丝线分隔，Bento 磁贴通用条款），置于内容区左右留白 15px 内
- **THEN** 英文名主行 14px/600 单行省略（tap 目标为整卡）；中文标题次行 12px 三阶灰单行省略；title 缺失不渲染次行（缺失=无该行）
- **THEN** 状态胶囊 = STATUS_META tone 色对（999 软底、带色点）；等待标记组（定时/待激活/前置依赖）为独立灰软底胶囊；模式胶囊「快速」=橙软底 warning、「标准」=灰软底 muted
- **THEN** 阶段进度区：阶段名（出题/实现/门禁/验证）+「计数 · 百分比」同行置于进度条上方，进度条色随阶段 ramp（#0891b2/#2563eb/#ea580c/#16a34a，DESIGN.md 数据编码色豁免），与桌面「任务进度」列共用 phaseProgressOf 单源推导
- **THEN** 终态（已推送/完成）卡省略进度区；草稿/无任务计数显「—」（MUST NOT 显示假 0）
- **THEN** 元信息行 = 优先级 | 创建时间 | 耗时（12px tabular-nums，分隔竖线）；run 活跃时追加「● 运行中」（success 色，静态）
- **THEN** 验证行：通过 ✓ 绿、异常 ⚠ 红（VerifyCell 语义随迁）
- **THEN** 有 error 的卡渲染信息行：amber 软底圆角条、 orange「信息」前缀、摘要单行省略
- **THEN** fix-* 子卡缩进 26px 并以 `└` 前缀灰符标识父子弹 relations（树形归并 buildTree 单源不变）
- **THEN** 整卡点击进详情（`specDetailPath` 单源）；⋮ 更多菜单（32px 触控目标）含 查看文档/调整优先级/冻结 既有项
- **THEN** 移动断点 <768px；桌面（≥768px）表格与现产逐像素一致（零改动）

#### Scenario: 移动端打开 SPEC 列表看卡片形态

- **WHEN** 用户以 <768px 视口打开项目 SPEC 列表
- **THEN** 列表渲染为磁贴内卡片流，卡片字段与层级符合上述 THEN 组
- **AND** 界面布局与组件形态以 specs/dashboard-spec-table/prototype/ 为 UI 真相源

#### Scenario: 桌面零回归

- **WHEN** 用户以 ≥768px 视口打开同一列表
- **THEN** 桌面表格形态与改版前完全一致（列结构/排序/整行点击/树形展开/信息子行）

### Requirement: SPEC 列表移动端筛选编排

- **THEN** 搜索框保留现产语义（specKeywordHit 单源：英文名 OR 中文标题命中）
- **THEN** 状态筛选改为横向滚动 chips（全部/各状态 + 计数徽标；激活态黑底白字，镜像 overview Radio 惯例）
- **THEN** 「筛选」按钮打开底部 Drawer：类型（全部/开发/fix-*）、归档（未归档/已归档）、排序（名称/优先级/进度/创建时间）经 Segmented 承载；「查看结果」关闭生效
- **THEN** 分页改磁贴底部「加载更多」按钮 +「共 N 条 · 已显示 M 条」caption（替代 antd 分页器）
- **THEN** 内容区背景色 #E3E3E3（2026-11-06 用户批注指定；色值落 theme.ts 单源常量并登记 DESIGN.md 修正案，见 design.md 偏离声明）
- **THEN** 顶栏（页面标题栏）不处理保持现状（用户批注明示豁免）

#### Scenario: 移动端按状态筛选

- **WHEN** 用户点选状态 chip「实现中」
- **THEN** 列表仅保留实现中 SPEC，chip 激活态黑底白字且计数可见

#### Scenario: 移动端筛选抽屉

- **WHEN** 用户点击「筛选」按钮
- **THEN** 底部 Drawer 弹出类型/归档/排序三组 Segmented
- **AND** 点「查看结果」关闭 Drawer 并按所选过滤排序
