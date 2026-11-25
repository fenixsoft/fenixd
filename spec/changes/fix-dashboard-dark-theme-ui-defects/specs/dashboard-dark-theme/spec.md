# 仪表盘深色主题验收缺陷修复（dashboard-dark-theme MODIFIED）

## MODIFIED Requirements

### Requirement: 全站呈现（原 dashboard-dark-theme「深档全站呈现」requirement 修订）

深色档下 dashboard 全部页面 SHALL 达成：主色族（主色/链接及其派生消费面——页签选中态与墨条、复选框、进度条、单选/分段控件）取 D2 深档显式值；时间轴卡片整卡深档化（无浅底残留与同卡双层反转）；页签计数徽标不遮挡页签文字；次级文本对比度对齐 dsh 深档 label-tertiary 系。浅色档 SHALL 与修复前逐字节一致。

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

- **WHEN** 深色档（浅色档同理）查看 SPEC 详情子页签「场景结果」「测试截图」计数徽标
- **THEN** 徽标位于页签文字旁不遮挡文字，数字可读

#### Scenario: 次级文本对比度

- **WHEN** 深色档下查看 SPEC 列表创建时间等次级文本与任务清单分组标题
- **THEN** 次级文本色取深档 tertiary（#adb2b8 系），浅档 #64748b 内联值不再出现在深档

#### Scenario: 浅档逐字节回归

- **WHEN** 独立访问切回浅色档（fenix.theme=light 或跟随系统浅色）
- **THEN** 本 SPEC 全部改动面（页签/卡片/徽标/次级文本）视觉与修复前一致，既有 theme 测试全量通过
