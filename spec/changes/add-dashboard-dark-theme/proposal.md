## Why

fenix dashboard 前端当前只有浅色一套 UI（`src/theme.ts` 单向翻译 dsh web 浅色 token）。当 dashboard 以 iframe 嵌入 dsh web、宿主切换为深色 UI 时，浅色页面与宿主严重割裂；独立访问时用户也没有深色可选项。本变更让 dashboard 具备浅/深双主题能力，并保证与 dsh web 深色调色板视觉统一。

## What Changes

- 依据 dsh web 深色调色板（`dsh-client-ui-theme` 包 `design_platform_css_default`，`body[data-ds-dark-theme]` 档 201 个 `--dsw-*` 变量，已逐项提取）生成 dashboard 深色 token 族：`src/theme.ts` 扩展为浅/深双档，antd 侧切 `theme.darkAlgorithm` + 深色 token 覆写。
- 引入主题状态机：三档偏好 `system / light / dark`（默认 `system` 跟随 `prefers-color-scheme`），localStorage 持久化，首帧防闪烁内联脚本。
- 嵌入 dsh web 时（`embed=1`）：主题跟随宿主——挂载 URL 可带初始 `theme` 参数；运行期经 host→iframe postMessage 主题消息实时切换；此时配置页「界面风格」控件锁定显示「跟随 dsh web」不可改（桥接侧订阅宿主 `theme/change` 事件并在 `dsh-plugins` 项目单独立项，本 SPEC 只定义 iframe 侧契约）。
- 独立访问时：配置页新增「界面风格」控件（跟随系统 / 浅色 / 深色），即时生效并持久化。
- 全站深色回归：`global.less` 硬编码浅色值改经主题变量（或深色档覆写），六页（overview/projects/settings/help/activities/command-center）+ 毛玻璃标题带/Bento 磁贴/StatusTag 状态色/指挥中心控制台在深色档下统一可读。
- 回填知识页 `spec/knowledge/domains/dashboard-frontend/ui-theme.md`（其描述的 v1 双主题规则已 stale）。

## Capabilities

### New Capabilities

- `dashboard-dark-theme`: 主题状态机与双调色板——偏好三档与缺省、localStorage 键、首帧防闪烁、浅/深 token 单源翻译、嵌入跟随（初始注入 + postMessage 实时切换 + 控件锁定）、独立访问设置控件、全站深色呈现要求。

### Modified Capabilities

- `dashboard-embed-mount`: 挂载 search 参数契约从「embed + apiBase 两参数」扩展为新增可选 `theme` 参数（初始主题注入，与既有参数独立解析、可组合、同安全纪律）。
- `v3-settings-page`: 配置页新增「界面风格」设置控件（嵌入态锁定显示「跟随 dsh web」，独立态三档可选即时生效）。

## Impact

- `core/dashboard/static/src/theme.ts`：浅/深双 token 族 + antd ThemeConfig 深色档（核心改动面）。
- `core/dashboard/static/src/global.less`：硬编码浅色颜色值收敛为主题变量，新增深色档。
- `core/dashboard/static/src/utils/embedMount.ts`：新增 `theme` 参数解析（沿用既有惰性缓存与测试注血模式）。
- 新增主题状态模块（偏好读写/应用/postMessage 通道）与首帧防闪烁注入（`config/config.ts` headScripts 或等价模板机制）。
- `core/dashboard/static/src/pages/settings/`：新增「界面风格」控件；`app.tsx` ConfigProvider 按当前主题切换 ThemeConfig。
- 组件层深色适配：PageTitleBar / StatusTag（TONE_HEX 深色档）/ DshIconButton / markdown-shared 等直接引用 theme 常量的消费面；六页深色回归。
- 跨仓依赖（非本仓交付物）：dsh-plugins `fenix-dsh-dashboard-bridge` 订阅宿主 `ctx.theme.getTheme()`/`theme/change`，初始经 URL `theme` 参数注入、变化经 postMessage 广播——该侧在 dsh-plugins 项目独立立项（`add-bridge-theme-channel`），本 SPEC 的嵌入跟随 Scenario 以「收到合法主题消息/参数即生效」定义 iframe 侧行为，不依赖桥接侧实现落地时序。
- 无后端/API/数据迁移影响；无破坏性变更（浅色为缺省渲染结果，未启用深色时视觉不变）。
