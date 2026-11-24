# 配置页（v3-settings-page）增量

## MODIFIED Requirements

### Requirement: 设置页整体布局

v3 的 `/settings` 路由渲染设置页，采用 ant-design account/settings 风格布局：左侧竖向子项菜单在既有页签集合（LLM Provider / Agent 模型分配 / Prompts / 并行度设置 / Token 预算 / 验证 / 代码质量 / 审批模式 / 杂项 / 系统 / 自进化 / 决策者车道，现产 `BASE_MENU_ITEMS` 全集）基础上新增「界面风格」页签，右侧为当前选中子项的设置面板；页面加载后默认选中「LLM Provider」。

#### Scenario: 打开设置页

- **WHEN** 用户点击左侧菜单「配置」进入 `/settings`
- **THEN** 页面展示左侧子项菜单（含新增的「界面风格」页签），右侧默认渲染「LLM Provider」面板，页面不出现"建设中"占位内容

#### Scenario: 切换设置子项

- **WHEN** 用户点击左侧菜单中任意其它子项（如「界面风格」）
- **THEN** 右侧面板切换为该子项的设置内容，左侧选中态高亮跟随

### Requirement: 界面风格子项

「界面风格」子项提供主题偏好三档单选：跟随系统（缺省）/ 浅色 / 深色。选择后立即全站生效并写入浏览器 localStorage（键 `fenix.theme`，值域 `system|light|dark`）；该项不参与 `PUT /api/config` 保存路径。「跟随系统」档跟随 `prefers-color-scheme` 并随系统外观实时切换；「浅色」/「深色」为显式固定档。嵌入 dsh web（`embed=1`）时该子项 SHALL 渲染为锁定态：三档控件置灰不可改，展示文案「跟随 dsh web」说明主题由宿主控制；嵌入态不读写 localStorage（宿主优先，见 dashboard-dark-theme 能力）。

#### Scenario: 切换深色主题

- **WHEN** 用户在界面风格子项选择「深色」
- **THEN** 页面立即切换为深色配色且 localStorage `fenix.theme` 为 `dark`，刷新后保持；不发起 `PUT /api/config`

#### Scenario: 切换跟随系统

- **WHEN** 用户选择「跟随系统」且当前操作系统为深色外观
- **THEN** localStorage `fenix.theme` 为 `system`，页面呈深色；操作系统切回浅色外观后页面实时切回浅色

#### Scenario: 嵌入态锁定

- **WHEN** dashboard 以 `embed=1` 嵌入 dsh web，用户打开配置页「界面风格」子项
- **THEN** 三档控件置灰不可交互，控件旁展示「跟随 dsh web」文案；改变宿主主题（经 postMessage）时页面主题实时跟随，控件档位不写 localStorage
