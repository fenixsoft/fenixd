## MODIFIED Requirements

### Requirement: 前端会话界面的入口与呈现

系统 SHALL 在 SPEC 列表页（项目页）的「会话」分面内提供会话界面，作为项目页 Tabs 分面导航的一部分（分面容器见 `project-page-tabs` 能力）。

- 会话界面 MUST 以内联面板形态呈现，MUST NOT 以 Modal 弹窗呈现，MUST NOT 在页面标题栏单独设置「接入会话」按钮。
- 该界面 MUST 包含：消息流区（复用既有 `claude-msg` 展示控件）与输入区（多行输入 + 发送）。
- 会话是项目级语义，MUST NOT 与任何具体 SPEC 绑定，MUST NOT 出现在单行 SPEC 的操作菜单（「更多」）中。
- 消息流 MUST 由既有 `runEventsToChatMessages()` 将事件转换为消息；MUST NOT 另写一套消息渲染。
- 发送中 MUST 有明确的进行中指示，且 MUST NOT 允许并发重复发送同一轮。
- 会话终止事件 MUST 以明确的终态提示呈现给用户，MUST NOT 表现为静默无响应。
- 会话界面 MUST 仅在「会话」分面被选中时激活（拉取会话状态、订阅事件流）；未被选中时 MUST NOT 产生会话相关请求或订阅。

#### Scenario: 会话界面位于会话分面

- **WHEN** 用户打开项目 `A` 的项目页并点击「会话」分面
- **THEN** MUST 在分面内容区显示会话界面（消息流区 + 输入区），且 MUST NOT 弹出 Modal

#### Scenario: 标题栏不含会话入口

- **WHEN** 用户打开项目 `A` 的项目页
- **THEN** 页面标题栏 MUST NOT 显示独立的「接入会话」按钮

#### Scenario: 操作菜单不含会话入口

- **WHEN** 用户展开任一 SPEC 行的「更多」菜单
- **THEN** 菜单中 MUST NOT 出现会话相关项

#### Scenario: 发送一轮并看到回复

- **WHEN** 用户在会话界面输入文本并发送
- **THEN** 该轮输入 MUST 出现在消息流中，且随后显示的 assistant 回复 MUST 使用与 run 输出面板相同的渲染形态（Markdown / 工具卡片 / thinking 折叠）

#### Scenario: 会话终止有明确提示

- **WHEN** 会话因空闲超时或进程退出而结束
- **THEN** 界面 MUST 显示明确的会话已结束提示，且输入区 MUST 不再接受发送
