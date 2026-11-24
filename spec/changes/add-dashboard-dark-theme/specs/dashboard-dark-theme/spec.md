# 仪表盘深色主题（dashboard-dark-theme）

## ADDED Requirements

### Requirement: 双主题 token 单源

dashboard 前端 SHALL 提供浅色与深色两套完整主题，色值实现单源为 `core/dashboard/static/src/theme.ts`（DESIGN.md 配色单源红线）。浅色档 SHALL 与本 SPEC 落地前的现状渲染逐字节一致（零视觉回退）；深色档 SHALL 按 design.md D2 映射表逐项翻译自 dsh web 深色调色板（`body[data-ds-dark-theme]` 档 `--dsw-*` alias 语义对位）。antd 侧深色档 SHALL 使用 `theme.darkAlgorithm` 加显式 token 覆写；MUST NOT 挂 theme 级 `borderRadius` 覆写（2026-11-03 用户裁决）；MUST NOT 引入 CSS 动画/transition（静态渲染红线）。

#### Scenario: 浅色零回退

- **WHEN** 用户使用浅色主题（缺省或手动浅色）打开任意页面
- **THEN** 页面配色与落地前浅色现状一致，theme.ts 浅色档常量值与既有值逐字节相同

#### Scenario: 深色对齐宿主调色板

- **WHEN** 用户切换到深色主题
- **THEN** 页面背景/文字/边框/链接/状态色取自 theme.ts 深色档（值来自 design.md D2 映射表，如背景层 `#151517/#232324/#2c2c2e/#353638`、主文字 `#f9fafb`、链接 `#7aaaff`、错误 `#f25a5a`），与 dsh web 深色 UI 视觉统一，不出现黑底黑字或白块残留

#### Scenario: 界面颜色单源

- **WHEN** 审计任意界面元素的颜色取值
- **THEN** 颜色均取自 theme.ts（antd 语义 token 或 DSH_* 深浅档常量），无散落硬编码新色值

### Requirement: 主题偏好状态机

系统 SHALL 提供主题偏好三档 `system / light / dark`，持久化于浏览器 localStorage 键 `fenix.theme`（值域即三档字符串）。缺省（无键或非法值）SHALL 为 `system`，跟随 `prefers-color-scheme`；`system` 档 SHALL 监听媒体查询变化实时切换（监听器随组件生命周期挂载/卸载对称清理）。effective scheme 解析为 `light|dark` 后应用于文档根（`data-fenix-theme` 属性）与 React ConfigProvider（对应 ThemeConfig）。主题切换 SHALL 即时重渲染生效，无过渡动画。

#### Scenario: 缺省跟随系统

- **WHEN** 用户从未手动设置主题，且操作系统为深色外观
- **THEN** dashboard 以深色呈现；操作系统切回浅色外观后页面实时切回浅色

#### Scenario: 手动深色持久化

- **WHEN** 用户手动选择「深色」后刷新页面
- **THEN** localStorage `fenix.theme` 为 `dark`，刷新后仍为深色呈现

#### Scenario: 手动浅色覆盖系统深色

- **WHEN** 操作系统为深色外观，用户手动选择「浅色」
- **THEN** dashboard 呈现浅色且不随系统外观变化；`fenix.theme` 为 `light`

### Requirement: 首帧防闪烁

首帧渲染 SHALL 无主题闪烁：页面加载时，主题解析（localStorage 偏好 + `embed=1` URL 参数 + prefers-color-scheme）与应用（`data-fenix-theme` 属性）SHALL 在样式表应用前由内联脚本完成（经 `config/config.ts` headScripts 注入，脚本逻辑与主题状态模块同构并注释互指）。

#### Scenario: 深色偏好首帧即深

- **WHEN** localStorage 偏好解析结果为深色，用户刷新页面
- **THEN** 首帧即为深色背景，不出现先白后黑的闪变

#### Scenario: 内联脚本缺省行为

- **WHEN** 无 localStorage 键且系统为浅色外观（独立访问）
- **THEN** 首帧为浅色，行为与无脚本时一致

### Requirement: 嵌入态主题跟随

嵌入 dsh web（`embed=1`）时主题 SHALL 跟随宿主：初始主题经挂载 search 可选参数 `theme=dark|light` 注入（值域白名单，非法/缺省回退独立逻辑）；运行期宿主经 postMessage 广播 `{kind:'fenix-theme', theme:'dark'|'light'}` 实时切换。iframe 侧 SHALL 校验消息来源（`event.source === window.parent`）与 `kind`/`theme` 值域白名单，不合法消息 SHALL 静默忽略。嵌入态宿主值 SHALL 优先于 localStorage 独立偏好：嵌入态不读取也不写入 `fenix.theme`（不污染独立偏好）。本要求只定义 iframe 侧行为；宿主侧监听与广播由 dsh-plugins 桥接插件（独立立项 `add-bridge-theme-channel`）实现。

#### Scenario: 嵌入初始注入

- **WHEN** 宿主以 `<prefix>/?embed=1&apiBase=<prefix>&theme=dark` 加载 iframe
- **THEN** 首帧即为深色，与宿主当前主题一致，不读取 localStorage

#### Scenario: 宿主切换实时跟随

- **WHEN** 用户在 dsh web 中把 UI 从浅色切为深色（dashboard iframe 已挂载）
- **THEN** iframe 收到 `{kind:'fenix-theme', theme:'dark'}` 后即时切换为深色，无需刷新

#### Scenario: 非法消息忽略

- **WHEN** iframe 收到 `{kind:'fenix-theme', theme:'purple'}` 或来源非父窗口的主题消息
- **THEN** 消息被忽略，主题保持当前档，控制台与页面无错误

#### Scenario: 独立偏好不被污染

- **WHEN** 用户曾在独立访问时设深色（`fenix.theme=dark`），随后以 `theme=light` 参数嵌入宿主
- **THEN** 嵌入期间呈现浅色（宿主优先），localStorage 仍为 `dark`；退出嵌入独立访问时恢复深色

### Requirement: 全站深色呈现

六页（overview/projects/settings/help/activities/command-center）与全局组件 SHALL 在深色档下完整可用、可读：嵌入毛玻璃标题带深档 rgb 通道 MUST 与深档 `DSH_BG_SOFT` 一致且透明度小于 1（layout-chrome-tinting 守卫）；StatusTag 六种 tone 深档逐项可读；markdown 代码块、表格、Menu、Input/Select 焦点态均呈深档；配置页灰底准例深档卡底/边框按 design.md D2 取值。`global.less` 存量硬编码浅色色值 SHALL 收敛为主题 CSS 变量（双档定义，值源 theme.ts 档位），收敛完成后 global.less MUST NOT 残留未归类硬编码界面色（迁移件豁免族 claude-msg/claude-composer 除外）。

#### Scenario: 六页深色核查

- **WHEN** 以深色主题逐页打开六个页面
- **THEN** 各页无白底残留、无黑字黑底、文字对比度可读，状态色语义正确

#### Scenario: 毛玻璃守卫深档成立

- **WHEN** 以深色主题渲染嵌入态标题带
- **THEN** 毛玻璃色 rgba 通道等于深档 DSH_BG_SOFT 且 alpha<1，滚动后回实底档同规则

#### Scenario: 既有测试回归

- **WHEN** 运行 dashboard 前端既有测试套件
- **THEN** 全部通过；新增主题模块（偏好解析/防闪烁/消息通道）有直载测试覆盖三档解析、值域白名单与消息校验

### Requirement: 知识页回填

本能力落地后 SHALL 回填 `spec/knowledge/domains/dashboard-frontend/ui-theme.md`：标注 v1 老面板双主题规则已退役，重写为现产双主题规则（三档偏好、键 `fenix.theme`、嵌入跟随契约、token 单源与映射表指针），消除知识页与现产代码的偏差。

#### Scenario: 知识页与现产一致

- **WHEN** 后续会话按 index-first 读取 dashboard-frontend 域 ui-theme 页
- **THEN** 页面描述与现产实现一致（三档缺省跟随系统、嵌入跟随、键名），不再出现 v1 默认深色等退役行为
