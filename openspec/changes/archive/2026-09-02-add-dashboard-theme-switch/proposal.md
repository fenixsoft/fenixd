# Proposal: add-dashboard-theme-switch

## Why

Dashboard 目前仅有深色（黑色）风格，配色硬编码于 `style.css` 的 `:root` 变量及散落规则中。部分用户偏好浅色界面，缺少切换入口导致审美需求无法满足。目标是在配置页新增「界面风格」页签，提供一套白色风格并允许用户在黑色/白色之间即时切换。

## What Changes

- **新建白色主题**：在 `style.css` 中新增浅色调色板（覆盖同名 CSS 变量），并将现有散落的硬编码颜色（顶栏背景、按钮文字色、遮罩、状态色等）收敛为 CSS 变量，保证两套主题共用同一变量面，浅色主题无需逐条覆盖。
- **配置页新增「界面风格」页签**：在现有 4 个页签（LLM Provider / Agent 模型分配 / 并行度 / 审批模式）之外新增页签，提供「黑色风格」「白色风格」两个单选选项，切换即时生效（无需保存按钮、无需重启 daemon）。
- **偏好持久化（浏览器本地）**：主题选择写入 `localStorage`（键如 `fenix.theme`），刷新或重开页面自动恢复。主题是 Dashboard 自身的展示属性，不属于 fenix 配置信息，**不写入 config.yaml**、不改动后端 schema。
- **首帧防闪烁**：在样式加载前于 `<head>` 内联应用主题的脚本，避免浅色用户刷新时闪一下深色。
- **默认行为兼容**：未设置过偏好时保持黑色（现状），新主题不影响既有页面结构与全部既有功能。

## Capabilities

### New Capabilities

- `ui-theme`: 界面主题能力 —— 覆盖浅（白）/深（黑）两套配色、主题的全局应用与即时切换、偏好的浏览器本地持久化、配置页「界面风格」页签入口。

### Modified Capabilities

（无现有 spec 命名空间受 requirements 级影响，属纯前端样式与交互新增。）

## Impact

- `core/dashboard/static/style.css` —— 新增浅色调色板变量；将散落硬编码颜色收敛为变量；默认仍为深色。
- `core/dashboard/static/app.js` —— `renderConfig` 新增「界面风格」页签与切换交互（聚合进既有 `collectConfigData()` 的保存语义之外，切换读/写 localStorage 并即时重绘）。
- `core/dashboard/static/index.html` —— `<head>` 内联首帧主题应用脚本（<100 行，无外部依赖）。
- 后端、`/api/config`、config.yaml schema、daemon 运行逻辑均**无改动**。
- 验证：`tests/` 中如存在 dashboard UI 的浏览器验证用例需同步扩展浅色主题断言。