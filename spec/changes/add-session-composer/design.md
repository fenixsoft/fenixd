# add-session-composer — 设计

## Context

- 会话接入页签(SessionPanel)输入区现状:antd `Input.TextArea` + 发送 + 停止同行排列(`SessionPanel.tsx:452-486`),全部内联 style 常量(`:50-84`),无移动端分支;`global.less` 的 `screen-xs` 作用域未覆盖会话面板;面板高度靠 `height: calc(100vh - 222px)` 显式填充(222 为桌面 chrome 实测常数,memory `fenixd-session-panel-viewport-height`)。
- 参考实现 claudecodeui(`/root/claudecodeui`,`@cloudcli-ai/cloudcli` v1.37.2,siteboon/claudecodeui fork):React 18 + Vite + Tailwind。输入控件三层:`useChatComposerState.ts`(1317 行,逻辑核心)、`ChatComposer.tsx`(517 行,业务壳)、`shared/view/ui/PromptInput.tsx`(219 行,无样式原语);配套 `useSlashCommands.ts`(494)、`useFileMentions.tsx`(273)、`useComposerMenuAnchor.ts`(82)、`CommandMenu.tsx`(324)、`ComposerMenuPrimitives.tsx`(94)、`chatStorage.ts`。textarea 为普通 `<textarea>` + 绝对定位 overlay 着色 @提及,非 contentEditable。
- fenixd dashboard 前端:UmiJS Max + antd 6 + React 19 + less;**tailwind 管道已存在**(`prebuild: tailwindcss -i ./tailwind.css -o ./src/components/claude-msg/tailwind.gen.css --minify`,输入为裸 `@tailwind` 指令,CLI 默认扫描全 `src`,新组件的 tailwind 类自动编译;消费方式参照 `claude-msg/index.ts` import `tailwind.gen.css`)。
- 后端会话链路:`session_manager.py` 每项目至多一个 `claude -p --input-format stream-json --output-format stream-json --verbose --permission-mode bypassPermissions --replay-user-messages` 子进程,`send()` 向 stdin 写一行 user JSON;`_stdout_reader` 逐行 JSON 解析入 deque 并 SSE 广播;事件缓冲 4000 条、空闲回收 1800s。
- 已实测验证(2026-09-25,写入 specs 依据):①stream-json 输入下 `@文件` 被 CLI 展开注入(单测式探针,模型答出仅文件名推不出的内容,input_tokens 24865);②`init` 事件含完整 `slash_commands`/`skills` 数组;③未知 `/命令` 透传给模型并友好降级。

## Goals / Non-Goals

**Goals**

- 移动端(390×844 基准)输入区全宽贴底、虚拟键盘不遮挡、高度自适应。
- 迁移补全(斜杠 + @提及)与草稿持久化,tailwind 样式原样保留。
- 后端新增 files/commands 两个只读端点与 init 缓存。
- 既有 23 个 `test_dashboard_session.py` 用例零回归。

**Non-Goals(明确不做,留 P2)**

- 附件/图片粘贴上传(需上传端点 + stream-json content 数组改造)。
- 中断当前回合(control_request 协议)——停止仍为杀整个会话进程。
- 排队消息、权限模式菜单、模型菜单、token 徽章、语音输入。
- 消息历史向前分页、事件持久化(deque 4000 条 + 截断提示维持现状)。
- 新增任何 fenixd 配置项(规避「新增配置必须带 Dashboard 界面」约定;高度/上限等用模块常量)。

## Decisions

### D1 迁移形态:三层结构整体搬入新目录,裁剪而非重写

新目录 `core/dashboard/static/src/components/claude-composer/`,迁入:逻辑核心(裁剪版 useChatComposerState)、ChatComposer、PromptInput 原语、useSlashCommands、useFileMentions、useComposerMenuAnchor、CommandMenu、ComposerMenuPrimitives、chatStorage。裁剪项:排队消息状态机、ComposerPermissionMenu、ComposerModelMenu、TokenUsageSummary、语音三件套、react-dropzone 附件链。

- 备选「antd AutoComplete/Mentions 重写」被否:Mentions 移动端体验一般,overlay 着色/键盘导航/菜单锚定细节重写成本高于搬运;原控件即为移动端打磨过的形态,且用户指名迁移。
- 备选「保留在 pages/ 下内联」被否:组件体量大(迁移后预计 1500+ 行),独立目录便于复用与测试。

### D2 样式:tailwind className 原样保留,不重写为 antd/less

既有 tailwind 管道扫描全 `src`,新目录类名自动进 `tailwind.gen.css`;组件内 import 该 css(与 claude-msg 同模式)。需一并搬的自定义 CSS 段(claudecodeui `index.css` 中 `chat-input-*`/`chat-composer-*`/`chat-activity-*` 相关)落为新组件目录内独立 css 文件随组件 import。深浅色:dashboard 全站强制亮色,原 token(HSL 变量)直接给亮色值。

### D3 发送通道:handleSubmit 单点适配到既有 REST

`useChatComposerState` 中 ws `sendMessage({type:'chat.send',...})` 调用点替换为 `services/dashboard.ts` 既有 `sendSessionMessage(project, text)`;`buildSendOptions`(model/effort/permissionMode 等)整体删除——fenixd 发送协议就是 `{text}` 纯文本。中断按钮语义映射到既有 `stopSession`。isComposing 守卫、发送中禁用、失败还原草稿三条既有交互保留。

### D4 移动端键盘:VisualViewport + viewport meta 双轨

- 新 hook `useVisualViewportHeight`(组件目录内):`window.visualViewport` resize 事件计算 `keyboardHeight = innerHeight - visualViewport.height - offsetTop`,写入面板容器 CSS 变量 `--keyboard-height`,输入区容器 `paddingBottom` 消费;只监听 `resize` 不监听 `scroll`(claudecodeui `AppContent.tsx:191-203` 同款,规避 iOS offsetTop 抖动)。
- `config.ts` 或静态 `index.html` 模板的 viewport meta 追加 `interactive-widget=resizes-content`(Android Chrome 键盘压缩布局视口)。
- 移动端判定复用既有 `useIsMobile.ts`(同步 matchMedia,边界 767.98px)。

### D5 面板高度常数:桌面保留 222,移动端独立实测

`PANEL_LAYOUT_STYLE` 的 `calc(100vh - 222px)` 仅桌面有效(顶栏 56 + 页头 72 + Tabs 46 + 间距 32 + padding 16)。移动端 ProLayout 形态不同(`global.less:173` 收紧 padding-inline 为 12),须以 390×844 实测重新推导移动端常数(或移动端改用 `dvh` 单位组合),实现时以 playwright 量 `textarea.getBoundingClientRect().bottom` 与视口差验证。空态/加载/错误分支弃用 `FILL_CENTER_STYLE` 居中,改紧凑顶部呈现。

### D6 files 端点:git ls-files 子进程,上限 5000

`git ls-files --cached --others --exclude-standard` 一次拿 tracked+未忽略 untracked,扁平相对路径数组,cwd=registry 注册路径,`subprocess.run(timeout=10)` 超时返回已收集部分或空数组(不 500);>5000 截断。备选「Python 遍历 + pathspec 忽略规则」被否:重实现 gitignore 语义易漂移。备选「返回树形结构」被否:@提及只需扁平路径前缀匹配,树形徒增体积。

### D7 commands 端点:init 事件缓存,禁自扫目录

`session_manager.py` 的 `_stdout_reader` 增加对 `type=system, subtype=init` 的捕获,取 `slash_commands`/`skills` 存 `Session` dataclass 新字段(如 `slash_commands: list[str]`、`skills: list[str]`,缺省空);init 事件本身维持既有系统事件口径不广播。进程重启后新 init 覆盖;Session 移除即缓存消亡。备选「后端扫 ~/.claude/skills + .claude/skills 目录」被否:插件/内建命令口径难以对齐,init 是 CLI 官方口径且零扫描成本。

### D8 i18n 与依赖:中文常量,零新第三方依赖

claudecodeui 文案走 react-i18next(`locales/en/chat.json` 的 `input.*`/`composer.*` 段),迁移时改为组件内中文常量(dashboard 全站中文,无 i18n 框架)。`react-dropzone`/`lucide-react` 等 P2 依赖不引入;图标用既有 `@ant-design/icons`(锁定 6.3.2)替换 lucide 图标位。

## Risks / Trade-offs

- [React 18 → 19 / Vite → UmiJS 语义差异] → 迁移后跑 `umi build` 全量类型检查;`forwardRef`/`useSyncExternalStore` 等点重点核对;JSX 转换差异由构建器兜底。
- [textarea + overlay 着色在 iOS 的滚动同步偏差] → 沿用原实现滚动同步逻辑(syncInputOverlayScroll),390×844 实测验证;着色仅视觉层,发送为纯文本,偏差不影响正确性只影响观感。
- [移动端 222px 常数失效导致高度错位] → D5 独立实测;验证脚本量化 bottom 差值,不靠目测。
- [git ls-files 在超大仓库超时] → timeout=10 + 5000 条上限兜底;超时返回空数组,补全降级为无候选,不阻塞输入。
- [init 事件未到达时补全静默不可用] → 无缓存返回空数组,前端空列表不触发菜单(已是既有降级路径);不弹错误。
- [tailwind 类名与 antd 全局样式的特异性冲突] → composer 根节点独立类名空间(chat-composer-*),不使用 antd 组件包裹输入路径;迁移后 playwright 双端截图比对。
- [键盘适配 hook 与 antd 弹层(Portal 到 body)定位冲突] → 补全菜单沿用原实现的相对锚定/portal 方案,不依赖 antd Popup;验证场景覆盖菜单在键盘弹出态的锚定。

## Migration Plan

1. 后端先行:session_manager init 缓存 + 两个端点 + 路由表 + 测试(纯新增,零破坏,可独立合并)。
2. 前端组件落位:claude-composer 目录迁移 + 单测(纯新增文件,不动既有组件)。
3. SessionPanel 切换:输入行替换 + 布局重做 + global.less 移动端规则(唯一动既有行为的步骤)。
4. 构建 `npm run build` + playwright 390×844 / 1280×800 双端验证。
5. 回滚:步骤 3 单点还原 SessionPanel 即回退(claude-composer 目录与端点为孤儿代码,无害);dist 重建即生效。

主树生效依赖合并后 `npm run build` 重建 dist(dist 不入库)——人工运维步骤,由 merge 流程照既有惯例处理,不进 tasks.md。
