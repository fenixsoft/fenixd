<!-- knowledge: capability=project-page-tabs rev=3 sources=spec/archive/2026-09-23-add-project-detail-tabs,spec/archive/2026-09-24-add-code-review-agent-and-quality-tab,spec/archive/2026-09-26-add-spec-list-filter-stickiness -->

# 项目详情页签

项目页（`/projects/:name`）的分面导航容器：开发/质量/回归/会话四分面与按需加载门控。

## 现行规则

- 项目页在项目名称下方渲染 `Tabs` 分面导航容器，分面组成为「开发」「质量」「回归」「会话」四个分面（顺序固定），默认选中「开发」；Tabs 容器在桌面与移动端两种视口下均渲染。
- 页签选中态持久化到 URL 查询参数 `tab`（合法值 `dev`/`quality`/`regression`/`session`，缺省 `dev` 且缺省不写参——选中态为缺省值时 URL 无 `tab` 参数）；写入采用 replace 语义，不为切换操作新增浏览器历史条目；刷新页面后恢复刷新前选中分面，URL 无 `tab` 参数时回到「开发」。
- 页签切换原地切换内容：不整页刷新、路由路径保持 `/projects/:name` 不变。
- 「开发」分面承载既有项目 SPEC 列表及其全部能力——搜索框、状态/类型/归档筛选、桌面表格与移动端卡片、行操作菜单、文档弹窗等，行为与引入分面前保持一致（零回归）。
- 「质量」分面承载当前代码仓的 code-review 质量视图——问题台账表格、手动触发审查按钮、真实进度条与取消、生成修复 SPEC 入口；内容由 `code-review-quality-tab` 能力的 `QualityTab` 承载，数据经 `GET /api/code-review/items` 拉取并随 SSE/心跳兜底刷新。
- 「会话」分面内联承载项目级自由会话界面：消息流区复用既有 `claude-msg` 展示控件，消息渲染由 `runEventsToChatMessages()` 转换（不另写一套）；输入区为多行输入 + 发送 + 停止；会话未启动时显示空态与「开始会话」按钮，点击后才启动会话进程，切到本分面不隐式启动；会话终止事件以明确终态提示呈现并禁用输入区，不静默无响应。
- 按需加载门控：各分面仅在自身被选中时拉取数据与订阅事件——未选中「质量」不拉取 `/api/code-review/items` 或订阅质量事件，未选中「会话」不拉取会话状态或注册事件订阅（避免项目页首屏无谓请求与订阅泄漏）；切离分面时释放该分面持有的会话事件订阅，不终止会话进程本身。

## 溯源

- 2026-09-23 add-project-detail-tabs — 建立项目页分面导航（开发/质量/会话三分面、默认开发、选中态不持久化）、开发分面零回归承载、质量空态占位与会话分面内联契约（含按需加载门控）
- 2026-09-24 add-code-review-agent-and-quality-tab — 「质量」分面由空态占位改为承载 code-review 质量视图（QualityTab、按需拉取、桌面与移动端可用）
- 2026-09-26 add-spec-list-filter-stickiness — 页签选中态改为 URL `tab` 参数持久化（replace 语义、刷新恢复、缺省不写参），分面扩为含「回归」的四分面
