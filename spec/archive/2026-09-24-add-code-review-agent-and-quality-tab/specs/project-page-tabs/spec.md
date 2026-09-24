# Spec Delta: project-page-tabs

## MODIFIED Requirements

### Requirement: 「质量」分面承载代码审查质量视图

「质量」分面 SHALL 承载当前代码仓的 code-review 质量视图——问题台账表格、手动触发审查按钮、真实进度条与取消、生成修复 SPEC 入口。该分面 MUST 仅在自身被选中时拉取数据与订阅事件；未选中时 MUST NOT 发起质量数据请求（保持本能力既有的按需加载语义）。分面 MUST 在桌面与移动端两种视口下均可用。

（原「仅空态占位、MUST NOT 展示任何业务数据或控件、MUST NOT 发起任何拉取质量数据的请求」被本 Requirement 取代。）

- 分面内容 MUST 由 `code-review-quality-tab` 能力定义的 `QualityTab` 承载。
- 数据 MUST 经 `GET /api/code-review/items` 拉取并随 SSE/心跳兜底刷新。
- 未选中「质量」分面时，MUST NOT 拉取 `/api/code-review/items` 或订阅质量相关事件。

#### Scenario: 质量分面展示问题视图

- **WHEN** 用户点击「质量」分面
- **THEN** 内容区 MUST 显示 code-review 问题表格（含行复选）与右上角触发按钮，MUST NOT 再显示「建设中」空态

#### Scenario: 未选中时不拉取

- **WHEN** 用户打开项目页并停留在「开发」分面（从未切到「质量」）
- **THEN** 页面 MUST NOT 拉取 `/api/code-review/items` 或订阅质量相关事件

#### Scenario: 切换分面不改变路由

- **WHEN** 用户在「质量」分面触发审查后切回「开发」分面
- **THEN** 浏览器地址 MUST 仍指向 `/projects/A`，MUST NOT 发生整页跳转
