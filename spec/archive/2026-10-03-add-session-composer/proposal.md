# add-session-composer

## Why

会话接入页签的输入框在移动设备上不可用:375px 视口下 TextArea 被同行按钮挤压到约 150px 宽 × 32px 高,空态内容垂直居中悬空,虚拟键盘弹出时输入区可能被遮挡。参考实现 claudecodeui(/root/claudecodeui,前次消息展示控件 claude-msg 的来源)有一个为移动端打磨过的成熟输入控件 ChatComposer(斜杠/skill 补全、@文件提及、草稿持久化),迁移它可同时解决移动端可用性与输入效率两个问题。

## What Changes

- **输入区布局重做(P0)**:输入区从「同行三控件」改为贴底全宽形态(消息区 flex:1 在上、输入区固定底部),移动端引入 VisualViewport 键盘高度适配(参照 claudecodeui AppContent 的 `--keyboard-height` 方案),textarea 高度自适应上限移动端 40vh;`height: calc(100vh - 222px)` 的 222 常数仅按桌面 chrome 推导,移动端重新实测各断点常数;空态/加载态不再用视口居中悬空布局。
- **迁移 ChatComposer 输入控件(P1)**:从 claudecodeui 迁移三层结构(逻辑核心 useChatComposerState + 业务壳 ChatComposer + 无样式原语 PromptInput)及配套 hooks(useSlashCommands、useFileMentions、useComposerMenuAnchor)、子组件(CommandMenu、ComposerMenuPrimitives)、localStorage 封装(chatStorage),落位 `core/dashboard/static/src/components/claude-composer/`;按 fenixd 场景裁剪:不做排队消息/权限模式菜单/模型菜单/token 徽章/语音/附件(P2 范围,本次明确不做);发送逻辑从 ws `chat.send` 替换为现有 REST `sendSessionMessage`;保留 tailwind className 原样迁移(既有 tailwind 管道自动编译,零扩展);i18n 文案改为中文常量,不引入 react-i18next。
- **补全能力(P1)**:斜杠命令/skill 补全(输入 `/` 触发,150ms debounce,↑↓/Tab/Enter/Esc 键盘导航)与 @文件提及(光标前 `@` 无空格触发,top10 匹配,overlay 着色,选中替换文本);草稿按 project 键持久化 localStorage,切页签不丢。
- **后端新增两个只读端点(P1)**:`GET /api/session/files?project=`(项目文件列表,供 @ 提及,`git ls-files --cached --others --exclude-standard` 实现,上限 5000 条)与 `GET /api/session/commands?project=`(斜杠命令/skill 列表,取自会话 stdout `init` 事件的 `slash_commands`/`skills` 数组,SessionManager 缓存;无在飞会话返回空数组)。Session dataclass 增加 init 事件缓存字段。
- **不改变**:消息渲染组件 claude-msg 不动;会话进程管理(send/stop/空闲回收/SSE 推送协议)不动;不新增任何 fenixd 配置项(高度上限等用模块常量,规避「新增配置项必须带 Dashboard 界面」约定)。

## Capabilities

### New Capabilities

- `session-composer`: 会话输入控件能力——斜杠命令/skill 补全、@文件提及、草稿持久化、发送/停止交互契约、输入区移动端贴底布局与虚拟键盘适配。

### Modified Capabilities

- `dashboard-live-session`: 会话面板输入区从内联 antd TextArea 替换为 composer 控件(挂载契约、空态布局要求变化);后端会话 API 面新增 `/api/session/files` 与 `/api/session/commands` 两个只读端点及 SessionManager 的 init 事件缓存要求。原「发送与终止」语义不变,仅输入侧承载组件变化。

## Impact

- **前端**:`core/dashboard/static/src/pages/projects/components/SessionPanel.tsx`(输入行替换、布局重做)、新增 `core/dashboard/static/src/components/claude-composer/`(迁移组件)、`core/dashboard/static/src/global.less`(screen-xs 作用域补会话面板规则,如需)、`core/dashboard/static/src/services/dashboard.ts`(files/commands 两个 API 封装)。
- **后端**:`core/dashboard/routes/base.py`(路由表)、`core/dashboard/routes/session_routes.py`(两个 handler)、`core/dashboard/session_manager.py`(init 事件捕获与缓存)。
- **构建**:前端改动需 `npm run build` 重建 dist(dist 不入库,主树生效需合并后重建——人工运维步骤);viewport meta 需评估补 `interactive-widget=resizes-content`(Android Chrome 键盘压缩布局)。
- **测试**:`tests/test_dashboard_session.py` 现有 23 用例不回归;新增 files/commands 端点用例;前端 `node --test` 补 composer 纯逻辑用例。
- **依赖**:零新第三方依赖(react-dropzone 等附件依赖属 P2 不引入);tailwind 管道既有。
- **已验证前提(2026-09-25 实测)**:`claude -p --input-format stream-json` 输入下 `@文件` 被 CLI 展开注入;`init` 事件含 `slash_commands`/`skills` 完整数组;未知 `/命令` 透传给模型并友好降级——补全 UI 只列有效项、无需本地校验。
