# session-composer — 会话输入控件能力(新增)

会话接入页签的输入控件从 claudecodeui ChatComposer 迁移而来,承载补全、草稿与移动端布局能力。挂载点与后端契约见 `dashboard-live-session` delta。

## ADDED Requirements

### Requirement: 输入区贴底全宽布局

会话面板内输入控件 SHALL 固定于面板底部并占满可用宽度:消息区在上占满剩余高度(`flex:1`),输入区贴底,桌面与移动端形态一致。

- 移动端(视口宽 <768px)输入区 MUST 全宽(仅保留页边距),MUST NOT 与发送/停止按钮同行挤压文本区。
- textarea 高度 MUST 随内容自适应:单行起步向上生长,移动端上限 40vh,超出后内部滚动且面板整体高度不变。
- 390×844 视口下输入区 MUST 完全在首屏可视范围内。
- 空态(无会话)与加载/错误态的提示内容 MUST 紧凑呈现,MUST NOT 使用视口垂直+水平居中的悬空布局。

#### Scenario: 移动端全宽贴底

- **WHEN** 以 390×844 视口打开一个有在飞会话的项目的会话页签
- **THEN** textarea 的 `getBoundingClientRect()` 宽度等于视口宽减去页边距,且输入区底边贴合面板底部,MUST NOT 出现输入框被按钮挤压到半宽的形态

#### Scenario: 空态不悬空

- **WHEN** 以 390×844 视口打开一个无会话项目的会话页签
- **THEN** 空态提示紧凑呈现,MUST NOT 垂直居中悬空于大段空白中央

#### Scenario: 高度自适应有上限

- **WHEN** 用户在输入框粘贴超过 10 行的文本
- **THEN** textarea 高度到达上限(移动端 40vh)后停止生长并内部滚动,会话面板整体高度不变

### Requirement: 虚拟键盘适配

移动端 SHALL 通过 VisualViewport API 计算虚拟键盘高度,保证键盘弹出时输入区仍完全可见。实现 MUST 只监听 `resize` 事件、MUST NOT 监听 `scroll`(规避 iOS visualViewport offsetTop 抖动);Android Chrome 侧 MUST 以 viewport meta `interactive-widget=resizes-content`(或等效机制)保证键盘压缩布局视口。

#### Scenario: 键盘弹出输入区不被遮挡

- **WHEN** 移动端(390×844)focus 输入框触发虚拟键盘弹出
- **THEN** 输入区的 `getBoundingClientRect().bottom` 不超过可视视口底边(允许 8px 容差),用户无需滚动即可看到正在输入的内容

#### Scenario: viewport meta 声明

- **WHEN** 构建前端并检查 `index.html` 的 viewport meta
- **THEN** 其中 MUST 包含 `interactive-widget=resizes-content`

### Requirement: 斜杠命令与 skill 补全

输入控件 SHALL 支持 `/` 触发的命令/skill 补全:光标处于行首或空白字符之后时键入 `/` 触发;候选列表来自 `GET /api/session/commands`,按使用频次排序(频次存 localStorage 按 project 键);匹配采用 150ms debounce;↑↓ 移动高亮、Tab 或 Enter 选中、Esc 关闭;移动端补全菜单 MUST 全宽锚定于输入区上方(或底部)。

#### Scenario: 触发补全

- **WHEN** 存在在飞会话时在空输入框键入 `/`
- **THEN** 出现补全菜单,候选为 commands 端点返回的 `slash_commands` 与 `skills`

#### Scenario: 键盘导航选中且不误发送

- **WHEN** 补全菜单打开时按 ↓ 再按 Enter
- **THEN** 输入框文本被替换为选中命令名,菜单关闭,且 MUST NOT 触发消息发送

#### Scenario: 无会话不触发

- **WHEN** 无在飞会话时键入 `/`
- **THEN** MUST NOT 出现补全菜单(commands 端点返回空列表,前端空列表不触发)

### Requirement: @ 文件提及

输入控件 SHALL 支持 `@` 触发的文件提及补全:光标前最后一个 `@` 且其后无空格时触发;候选来自 `GET /api/session/files` 的前缀/子串匹配,最多展示 10 条;↑↓/Tab/Enter/Esc 键盘交互与斜杠补全一致;选中后输入框中 `@` 片段 MUST 替换为完整相对路径,且已提及路径在输入框内以高亮 overlay 着色显示;发送的 `text` MUST 为原始文本(`@路径` 原样透传),由 CLI 侧展开,前端 MUST NOT 预读文件内容。

#### Scenario: 触发与选中替换

- **WHEN** 用户键入 `@src` 且文件列表包含 `src/app.tsx`
- **THEN** 菜单列出匹配文件(≤10 条),选中后输入框中 `@src` 片段替换为 `@src/app.tsx` 并着色显示

#### Scenario: 发送内容为原始文本

- **WHEN** 用户发送包含 `@src/app.tsx` 的输入
- **THEN** `POST /api/session/send` 的 `text` 字段原样包含 `@src/app.tsx`,MUST NOT 被 UI 层改写或展开

### Requirement: 草稿持久化

输入控件 SHALL 将未发送草稿按 project 键持久化到 localStorage(键名模式 `draft_input_<project>`):切换页签、切换路由或刷新页面后草稿 MUST 保留;发送成功后草稿 MUST 清除;发送失败时输入内容 MUST 还原为发送前状态。

#### Scenario: 切页签草稿保留

- **WHEN** 用户输入未发送文本后切到其他页签再切回会话页签
- **THEN** 输入框中的文本仍在

#### Scenario: 发送成功清空与失败还原

- **WHEN** 发送请求成功 / 发送请求失败(网络错误或非 2xx)
- **THEN** 成功时输入框清空且草稿清除;失败时输入内容还原为发送前文本并显示错误提示

### Requirement: 发送与停止交互契约

输入控件 SHALL 保持既有发送语义并防误触:Enter 发送、Shift+Enter 换行、IME composing 状态按 Enter MUST NOT 发送(`isComposing` 守卫);发送请求在途时 MUST 禁用发送且 MUST NOT 并发重复发送;停止按钮沿用既有 `stopSession`(终止整个会话进程)语义;会话终态后输入区 MUST 禁用并显示会话已结束提示。

#### Scenario: IME 不误发

- **WHEN** 用户使用中文输入法在 composing 状态按 Enter 确认候选词
- **THEN** MUST NOT 触发发送

#### Scenario: 并发防重

- **WHEN** 上一条消息请求仍在途时用户再次按 Enter
- **THEN** MUST NOT 发起第二条请求

#### Scenario: 会话终态禁用输入

- **WHEN** 会话进程退出或被停止
- **THEN** 输入区禁用,界面显示会话已结束提示(既有行为保持)
