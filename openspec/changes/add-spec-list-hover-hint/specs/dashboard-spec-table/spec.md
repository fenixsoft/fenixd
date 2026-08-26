## ADDED Requirements

### Requirement: SPEC 名称 hover 显示 Why 提示

系统 SHALL 在 SPEC 列表页中，当鼠标悬停（hover）于某 SPEC 名称单元格时，显示一个 div 模拟的悬浮提示框（hint），内容为该 SPEC `proposal.md` 中 `## Why` 段的 Markdown 渲染结果；提示框 SHALL 使用 DOM div 而非浏览器 `title` 属性实现，以便渲染 Markdown 样式。

提示数据 SHALL 按需获取：首次悬停某 SPEC 时，通过既有 `GET /api/spec-doc?doc=proposal` 端点读取 proposal 原文，在前端从 Markdown 源文本提取 `## Why` 段（自 `## Why` 标题行（标题文本大小写不敏感）之后的内容起，到下一个二级标题（`## `）或文档末尾止），再经既有 `marked` Markdown 渲染管线（含 GFM 与既有链接白名单/转义约束）渲染为 HTML。获取结果 SHALL 按 `(project, spec名称)` 键在内存缓存，同一 SPEC 再次悬停时 SHALL 直接使用缓存，不再发起请求。加载期间 SHALL 显示轻量加载占位。

提示框交互：鼠标离开该名称单元格（或进入并离开提示框自身）时 SHALL 隐藏；点击该行触发跳转时 SHALL 同时隐藏；视口边缘 SHALL 自动翻转定位以避免溢出。hover 提示 SHALL 不改变行点击跳转、排序、过滤等既有列表行为。

#### Scenario: 悬停名称显示 Why 内容
- **WHEN** 某 SPEC 的 proposal.md 含 `## Why` 段，鼠标悬停其名称单元格
- **THEN** 出现 div 悬浮提示框，内容为该段文案

#### Scenario: 提示内容为 Markdown 渲染而非原文
- **WHEN** 该 SPEC 的 Why 段含粗体、列表等 Markdown 语法（如 `**需要**`、`- 条目`），悬停其名称
- **THEN** 提示框内显示渲染后的样式（粗体加粗、列表带符号），而非原始 Markdown 文本

#### Scenario: 重复悬停使用缓存
- **WHEN** 同一 SPEC 此前已悬停过一次（内容已缓存），再次悬停
- **THEN** 提示框立即出现，不发新的文档请求

#### Scenario: 无 Why 段不显示提示
- **WHEN** 某 SPEC 的 proposal.md 缺失、不存在 `## Why` 标题，或提取后无内容，悬停其名称
- **THEN** 不出现悬浮提示框，名称单元格无任何变化

#### Scenario: 离开与点击时关闭
- **WHEN** 鼠标从名称单元格移开（未进入提示框），或点击该行任意区域触发跳转
- **THEN** 悬浮提示框隐藏，且行点击跳转到 SPEC 详情的既有行为不受影响

### Requirement: SPEC 信息子行替换「错误」列

系统 SHALL 从 SPEC 列表页移除名为「错误」的表格列（表头、列内单元格及以 `error` 为键的排序能力一并移除）。当某 SPEC 的状态消息字段（`STATE.md` 条目 `error` 字段，语义为说明性信息）非空时，系统 SHALL 在该 SPEC 行正下方渲染一个跨全部列宽的信息子行，以完整文本展示该消息并允许自动换行，SHALL NOT 截断内容。该消息为空或 `null` 时 SHALL 不渲染信息子行，不占用额外行高。信息子行 SHALL 在列表过滤、排序、2 秒自动刷新后保持正确渲染。

#### Scenario: 有消息时行下显示完整信息子行
- **WHEN** 某 SPEC 的 `error` 字段为一段长消息（如 `Recovered from interrupted state: ...`），打开项目视图
- **THEN** 该 SPEC 行下渲染一个跨全列的子行，消息完整显示、换行可读，不出现「…」截断

#### Scenario: 无消息时不渲染子行
- **WHEN** 某 SPEC 的 `error` 字段为 `null` 或空，打开项目视图
- **THEN** 该 SPEC 只有一行，行下无任何额外子行

#### Scenario: 表格不再有错误列
- **WHEN** 打开项目视图查看表头与任意行
- **THEN** 表头不含「错误」列，行内也无该列的单元格；原有排序交互按剩余表头列工作

#### Scenario: 刷新后信息子行仍显示
- **WHEN** 某 SPEC 存在非空消息，页面经过一次自动刷新（重渲染）后
- **THEN** 该 SPEC 行下信息子行仍然显示，内容与刷新前一致