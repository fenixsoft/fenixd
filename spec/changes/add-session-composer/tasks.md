## Deliverables

```yaml
- path: core/dashboard/session_manager.py
  kind: modify
- path: core/dashboard/routes/session_routes.py
  kind: modify
- path: core/dashboard/routes/base.py
  kind: modify
- path: core/dashboard/static/src/components/claude-composer/index.ts
  kind: new
- path: core/dashboard/static/src/components/claude-composer/SessionComposer.tsx
  kind: new
- path: core/dashboard/static/src/components/claude-composer/useComposerState.ts
  kind: new
- path: core/dashboard/static/src/components/claude-composer/useSlashCommands.ts
  kind: new
- path: core/dashboard/static/src/components/claude-composer/useFileMentions.tsx
  kind: new
- path: core/dashboard/static/src/components/claude-composer/useComposerMenuAnchor.ts
  kind: new
- path: core/dashboard/static/src/components/claude-composer/useVisualViewportHeight.ts
  kind: new
- path: core/dashboard/static/src/components/claude-composer/CommandMenu.tsx
  kind: new
- path: core/dashboard/static/src/components/claude-composer/ComposerMenuPrimitives.tsx
  kind: new
- path: core/dashboard/static/src/components/claude-composer/PromptInput.tsx
  kind: new
- path: core/dashboard/static/src/components/claude-composer/chatStorage.ts
  kind: new
- path: core/dashboard/static/src/components/claude-composer/composer.css
  kind: new
- path: core/dashboard/static/src/pages/projects/components/SessionPanel.tsx
  kind: modify
- path: core/dashboard/static/src/services/dashboard.ts
  kind: modify
- path: core/dashboard/static/config/config.ts
  kind: modify
- path: core/dashboard/static/tailwind.config.js
  kind: modify
- path: core/dashboard/static/tests/session-composer.test.mjs
  kind: new
- path: tests/test_dashboard_session.py
  kind: modify
```

## 1. 后端:init 事件缓存与两个只读端点

- [x] 1.1 `core/dashboard/session_manager.py`:`Session` dataclass 新增 `slash_commands: list[str]` 与 `skills: list[str]`(缺省空);`_stdout_reader` 捕获 `type=system` 且 `subtype=init` 事件,取其 `slash_commands`/`skills` 覆盖写入缓存;init 事件本身不转发 SSE(既有过滤仅丢弃 `system/hook_*`、init 当前会广播,本次捕获后丢弃属有意行为变化,前端 runEvents.ts SILENT_KINDS 已含 init、零渲染依赖);缓存随 Session 移除消亡、进程重启后新 init 覆盖
- [x] 1.2 `core/dashboard/routes/session_routes.py` + `base.py` 路由表:新增 `GET /api/session/files?project=`,project 校验复用 `_project_from_query`,校验失败返回 404(与既有 `_session_context` 样板对未注册项目的口径一致,非 400);以注册路径为 cwd 跑 `git ls-files --cached --others --exclude-standard`(子进程,timeout 10s),返回相对路径字符串数组,上限 5000 条截断;非 git 仓库返回 200 空数组;注意路由表登记顺序不得破坏既有 `watch` regex 前置先例
- [x] 1.3 同上模式新增 `GET /api/session/commands?project=`:读 SessionManager 该项目 Session 的 init 缓存,返回 `{"slash_commands": [...], "skills": [...]}`;无在飞会话或 init 未到返回两个空数组(200)
- [x] 1.4 `tests/test_dashboard_session.py` 新增用例:init 缓存写入/覆盖/随终止消亡、files 正常/非 git/非法 404/5000 截断、commands 有会话/无会话;假 Popen 注入模式与既有用例一致;全文件(含既有 23 例)通过

## 2. 前端:claude-composer 组件迁移落位

- [x] 2.1 新建 `core/dashboard/static/src/components/claude-composer/` 骨架:迁入 claudecodeui `shared/view/ui/PromptInput.tsx` 原语、`ComposerMenuPrimitives.tsx`、`chatStorage.ts`(localStorage 键模式改按 project:`draft_input_<project>`、`command_history_<project>`);i18n 调用改中文常量,lucide 图标换 `@ant-design/icons`
- [x] 2.2 迁入 `useSlashCommands.ts`、`useFileMentions.tsx`(参考实现为 .tsx、含 overlay JSX 渲染)、`useComposerMenuAnchor.ts`:候选数据源改为 `services/dashboard.ts` 的 commands/files 端点封装( props 注入,组件内不直接 fetch);保留 150ms debounce、↑↓/Tab/Enter/Esc 键盘导航、频次排序、@提及 top10 匹配与选中替换逻辑
- [x] 2.3 迁入裁剪版 `useComposerState.ts`:删除排队消息/权限模式菜单/模型菜单/token 徽章/语音/附件全部逻辑;发送调用单点替换为 `sendSessionMessage(project, text)` 纯文本;保留 isComposing 守卫、发送中禁用、失败还原草稿、textarea 高度自适应(移动端上限 40vh)与 overlay 滚动同步
- [x] 2.4 组装 `SessionComposer.tsx` + `CommandMenu.tsx` + `composer.css`(claudecodeui `index.css` 中 `chat-input-*`/`chat-composer-*` 相关段,tailwind 类名原样保留,组件 import 既有 `tailwind.gen.css` 与 composer.css);新增 `useVisualViewportHeight.ts`(只监听 resize、不读 offsetTop,写 `--keyboard-height` 变量);`tailwind.config.js` content 扩入 `./src/components/claude-composer/**/*.{ts,tsx}`(不扩则新组件类名不进 tailwind.gen.css);`index.ts` 导出
- [x] 2.5 前端单测 `core/dashboard/static/tests/session-composer.test.mjs`(node --test):草稿存取、@提及片段替换、斜杠触发条件(行首/空白后)、debounce 行为的纯逻辑用例

## 3. SessionPanel 切换与移动端布局

- [x] 3.1 `core/dashboard/static/src/services/dashboard.ts`:新增 `fetchSessionFiles(project)` 与 `fetchSessionCommands(project)` 封装(错误吞掉返回空数组,不打断输入)
- [x] 3.2 `SessionPanel.tsx`:输入行(TextArea+发送+停止,`:452-486`)替换为 SessionComposer,stop/start/终态禁用接既有逻辑;`PANEL_LAYOUT_STYLE` 高度拆桌面(保留 222 常数)与移动端分支(useIsMobile,常数按 390×844 实测重推或 dvh 组合);空态/加载/错误分支弃用 `FILL_CENTER_STYLE` 视口居中,改紧凑呈现
- [x] 3.3 `core/dashboard/static/config/config.ts`:viewport meta 源头追加 `interactive-widget=resizes-content`——config.ts 现无 metas 字段(dist viewport 来自 umi 内置默认),新增 metas 同名 viewport 须给完整 content(在既有 `width=device-width, user-scalable=no, initial-scale=1.0, maximum-scale=1.0, minimum-scale=1.0` 基础上追加),并在 3.4 确认产物仅一条 viewport meta;composer.css 内补 `screen-xs` 作用域规则(composer 根类名空间,移动端输入区全宽、菜单全宽锚定)
- [x] 3.4 `core/dashboard/static` 内 `npm run build` 构建通过;确认 dist 产物含新 chunk 与 viewport meta 新值

## 4. 双端行为验证与回归

- [x] 4.1 playwright(390×844,worktree serve 实例,勿打主树 8787):textarea 全宽贴底(getBoundingClientRect 宽≈视口减页边距、bottom 贴面板底)、空态不垂直居中、CDP 模拟 visualViewport resize 后输入区不被键盘高度遮挡、键入 `/` 菜单全宽锚定
- [x] 4.2 playwright(1280×800):有会话项目发送一轮(含 @文件 提及),消息流渲染走 claude-msg 既有形态,输入成功后草稿清除
- [x] 4.3 交互回归:输入未发送文本切页签再切回草稿仍在;IME composing 态 Enter 不发送;发送失败还原草稿;会话终止后输入禁用
- [x] 4.4 全量回归:`tests/test_dashboard_session.py` 全部用例(含新增)通过;`core/dashboard/static` 内 `node --test tests/*.test.mjs` 全通过
