# 会话输入控件

<!-- knowledge: capability=session-composer rev=1
     sources=spec/archive/2026-10-03-add-session-composer -->

会话页签的输入控件：承载斜杠命令/skill 补全、@ 文件提及、草稿持久化、输入区贴底布局与虚拟键盘适配，挂载于[实时会话视图](dashboard-live-session.md)的会话面板。

## 规则

- 组件落位与分层：输入控件整体位于前端 `components/claude-composer/` 目录，三层结构——逻辑核心（useComposerState）、业务壳（SessionComposer）、无样式原语（PromptInput），配套 useSlashCommands / useFileMentions / useComposerMenuAnchor hooks、CommandMenu / ComposerMenuPrimitives 子组件与 chatStorage（localStorage 封装）；补全的纯逻辑（触发判定、候选过滤、片段替换、键名）收口在 composerLogic.ts 供 `node --test` 直测。消息流渲染与本控件无关，仍由 `claude-msg` 承载。
- 输入区布局：消息区在上占满剩余高度（`flex:1`），输入区贴底全宽，桌面与移动端形态一致；移动端（视口 <768px，复用 `useIsMobile` 的 matchMedia 边界）输入区仅保留页边距，MUST NOT 与发送/停止按钮同行挤压文本区；textarea 高度单行起步随内容向上生长，移动端上限 40vh，超出后内部滚动且面板整体高度不变；空态/加载/错误态提示紧凑顶部呈现，MUST NOT 视口垂直居中悬空。面板高度常数两端独立：桌面 `calc(100vh - 222px)`（222 为桌面 chrome 实测常数），移动端 `calc(100dvh - 234px)`（dvh 随工具栏收展，按 390×844 实测校准）——两端常数各自推导不共用，调整布局后须以 playwright 量 `getBoundingClientRect().bottom` 与视口差验证，不靠目测。
- 虚拟键盘适配：以 VisualViewport API 计算键盘高度（`max(0, innerHeight - visualViewport.height)`，不读 offsetTop）写入面板 CSS 变量 `--keyboard-height` 供输入区容器消费；只监听 `resize`、MUST NOT 监听 `scroll`（iOS visualViewport offsetTop 随滚动抖动）；viewport meta 恒含 `interactive-widget=resizes-content`（Android Chrome 键盘压缩布局视口）；键盘弹出时输入区底边不超出可视视口（8px 容差）。
- 斜杠补全：行首或空白字符之后键入 `/` 触发；候选来自 commands 端点返回的 `slash_commands` 与 `skills`，按使用频次排序（频次存 localStorage `command_history_<project>`，按 project 隔离），查询 150ms debounce；↑↓ 移动高亮、Tab 或 Enter 选中、Esc 关闭；补全菜单打开期间键盘事件由菜单优先消费——选中只替换输入框文本，MUST NOT 触发发送；候选为空不弹菜单、不报错。
- @ 文件提及：光标前最后一个 `@` 且其后无空格时触发；候选来自 files 端点的相对路径做文件名/路径子串匹配（大小写不敏感），至多 10 条（`FILE_MENTION_LIMIT`）；选中后输入框中 `@` 片段替换为完整相对路径，已提及路径以绝对定位 overlay 着色呈现（普通 textarea + overlay，非 contentEditable），滚动同步沿用 overlay 方案；发送的 `text` 恒为原始文本，`@路径` 原样透传由 CLI 侧展开注入，前端 MUST NOT 预读文件内容或改写发送文本。
- 草稿持久化：未发送草稿按 project 键写 localStorage（`draft_input_<project>`），切页签、切路由或刷新页面后保留；发送成功清空输入并清除草稿；发送失败（网络错误或非 2xx）还原为发送前文本并显示错误提示。
- 发送与停止契约：Enter 发送、Shift+Enter 换行；IME composing 状态按 Enter MUST NOT 发送（isComposing 守卫）；请求在途时禁用发送且 MUST NOT 并发重复发送；发送走既有 REST `sendSessionMessage`，协议就是纯 `{text}`，MUST NOT 出现 model/effort/permissionMode 等发送选项；停止按钮沿用 `stopSession`（终止整个会话进程，控件内没有「中断当前回合」能力）；会话终态后输入区禁用、placeholder 变「会话已结束」并显示终态提示。
- 样式管线：组件使用 tailwind className（目录已注册进 tailwind content 数组，机制见 ADR-207），组件内 import `tailwind.gen.css` 与 `composer.css`；根节点用独立类名空间（`fenix-composer` / `chat-composer-*`），输入路径 MUST NOT 被 antd 组件包裹；补全菜单沿用相对锚定/portal 方案，不依赖 antd Popup，避免与键盘弹出态冲突。
- 能力边界：控件不含附件/图片上传、排队消息、权限模式菜单、模型菜单、token 徽章、语音输入；文案为组件内中文常量（dashboard 无 i18n 框架），图标用 `@ant-design/icons`，零新增第三方依赖。

## 溯源

- 2026-10-03 add-session-composer（spec/archive/2026-10-03-add-session-composer） — 新建本能力：输入控件整体迁入 `claude-composer/` 目录并按 fenixd 场景裁剪（发送通道适配 REST `sendSessionMessage`、删除 model/effort 选项与排队/附件/语音链），确立贴底布局、VisualViewport 键盘适配、斜杠/@ 补全、草稿持久化与发送/停止契约；配套后端 files/commands 端点与 init 缓存记录于 dashboard-live-session
