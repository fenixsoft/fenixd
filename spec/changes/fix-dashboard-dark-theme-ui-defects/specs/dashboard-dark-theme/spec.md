# 仪表盘深色主题验收缺陷修复（dashboard-dark-theme MODIFIED）

## MODIFIED Requirements

### Requirement: 全站深色呈现

六页（overview/projects/settings/help/activities/command-center）与全局组件 SHALL 在深色档下完整可用、可读：嵌入毛玻璃标题带深档 rgb 通道 MUST 与深档 `DSH_BG_SOFT` 一致且透明度小于 1（layout-chrome-tinting 守卫）；StatusTag 六种 tone 深档逐项可读；markdown 代码块、表格、Menu、Input/Select 焦点态均呈深档；配置页灰底准例深档卡底/边框按 design.md D2 取值。`global.less` 存量硬编码浅色色值 SHALL 收敛为主题 CSS 变量（双档定义，值源 theme.ts 档位），收敛完成后 global.less MUST NOT 残留未归类硬编码界面色（迁移件豁免族 claude-msg/claude-composer 除外）。

本次修订新增（2026-11-25 验收缺陷修复）：深色档下主色族（主色/链接及其派生消费面——页签选中态与墨条、复选框、进度条、单选/分段控件）SHALL 取 D2 深档显式值（ProLayout 主内容/侧栏 scope 计算变量 `--ant-color-primary`=#f9fafb 系、`--ant-color-link`=#7aaaff）；SpecTimeline 时间轴卡片 SHALL 整卡深档化（无浅底残留、无同卡双层反转）；SPEC 详情子页签计数徽标 SHALL 不遮挡页签文字；次级文本 SHALL 经双源同步校准（theme.ts `OV_TEXT_TERTIARY_DARK` 与 global.less `--fenix-ov-text-tertiary` 深档值）对齐 dsh 深档 label-tertiary #adb2b8 系。浅色档 SHALL 与修复前逐字节一致。

#### Scenario: 六页深色核查

- **WHEN** 以深色主题逐页打开六个页面
- **THEN** 各页无白底残留、无黑字黑底、文字对比度可读，状态色语义正确

#### Scenario: 毛玻璃守卫深档成立

- **WHEN** 以深色主题渲染嵌入态标题带
- **THEN** 毛玻璃色 rgba 通道等于深档 DSH_BG_SOFT 且 alpha<1，滚动后回实底档同规则

#### Scenario: 既有测试回归

- **WHEN** 运行 dashboard 前端既有测试套件
- **THEN** 全部通过；新增主题模块（偏好解析/防闪烁/消息通道）有直载测试覆盖三档解析、值域白名单与消息校验

#### Scenario: 深档页签选中态可见

- **WHEN** 深色档下访问 `#/projects/fenixd`（或任一带 antd Tabs 页签的页面）
- **THEN** 当前选中页签文字与墨条为 D2 深档值（文字近白 #f9fafb 系、可见），主内容/侧栏 scope 计算变量 `--ant-color-primary` 解析为 #f9fafb 系、`--ant-color-link` 解析为 #7aaaff

#### Scenario: 深档主色族消费面归位

- **WHEN** 深色档下查看任务清单复选框与进度条、项目页分段/单选控件
- **THEN** 取色为 #f9fafb/#7aaaff 主色族显式值或其合法深档形态，非浅档派生 muddy 值（#6b94dc/#101115 系不得出现）

#### Scenario: 时间轴卡片整卡深档

- **WHEN** 深色档下打开 SPEC 详情「验证 → 运行时间轴」
- **THEN** 时间轴卡片底为深档卡底（#232324 系），卡内文字近白、引文框与卡片同层协调，无白底卡与黑底引文框并存的反转形态

#### Scenario: 页签徽标不压字

- **WHEN** 深色档（浅色档同理）查看 SPEC 详情全部子页签计数徽标（场景结果/缺陷/测试截图）
- **THEN** 徽标位于页签文字旁不遮挡文字，数字可读

#### Scenario: 次级文本对比度

- **WHEN** 深色档下查看 SPEC 列表创建时间等次级文本与任务清单分组标题
- **THEN** 次级文本计算色为深档 tertiary #adb2b8 系（`--fenix-ov-text-tertiary` 深档值与 theme.ts `OV_TEXT_TERTIARY_DARK` 双源同步校准），非校准前深值 #8b8f94；浅档 #64748b 不变

#### Scenario: 浅档逐字节回归

- **WHEN** 独立访问切回浅色档（fenix.theme=light 或跟随系统浅色）
- **THEN** 本 SPEC 全部改动面（页签/卡片/徽标/次级文本）视觉与修复前一致，既有 theme 测试全量通过
