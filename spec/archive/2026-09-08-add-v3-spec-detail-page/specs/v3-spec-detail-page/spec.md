# v3 SPEC 详情页（spec-detail-page）

## ADDED Requirements

### Requirement: 详情页入口与路由

v3 新增路由 `/projects/:name/:spec`；SPEC 列表页中每行的 spec 名称可点击，跳转至该 spec 的详情页；详情页提供返回列表的导航（返回至 `/projects/:name`）。

#### Scenario: 从列表进入详情

- **WHEN** 用户在 SPEC 列表点击某行 spec 名称
- **THEN** 跳转至 `/projects/<project>/<spec>` 详情页，头部展示 spec 名称、状态与元信息，不出现占位内容

#### Scenario: 返回列表

- **WHEN** 用户点击详情页的返回导航
- **THEN** 回到该项目 SPEC 列表页，列表数据保持可用

### Requirement: 常驻信息区

详情页顶部常驻展示（不随页签切换消失）：error 横幅（spec.error 非空时）、验证结论（verdict）、验证进度、Token 用量（tokens_in/out 与成本可用性，成本不可用时展示"成本不可用（网关未回传）"语义）、任务清单（tasks.md 任务分组与勾选状态）。

#### Scenario: 常驻区块展示

- **WHEN** 打开一个已推进到验证阶段的 spec 详情
- **THEN** 页面顶部依次可见验证结论、验证进度、Token 用量与任务清单区块，且切换页签后仍可见

#### Scenario: error 横幅

- **WHEN** spec.error 非空
- **THEN** 页面顶部渲染红色错误横幅展示 error 内容；为空时不渲染

### Requirement: 运行时间轴页签

「运行时间轴」页签按时间序展示 spec 生命周期事件（状态迁移节点含回退原因）与运行记录节点（agent 类型、状态）；运行节点可展开查看该次运行的 LLM 对话流（经 `/api/runs/<run_id>/watch` 系端点，增量语义对齐 v1：按需拉取 + SSE 增量，或实现方论证等价的按需加载方案）。

#### Scenario: 查看时间轴

- **WHEN** 打开有运行记录的 spec 详情的运行时间轴页签
- **THEN** 时间线按时间序展示状态迁移与运行节点，回退节点可见原因

#### Scenario: 查看运行对话流

- **WHEN** 用户展开某个运行节点
- **THEN** 展示该次运行的 LLM 事件对话流（含 agent 类型与状态）；对话流按需加载，不随页面打开全量拉取

### Requirement: 场景结果页签

「场景结果」页签展示验证报告的场景级结果：汇总行（通过/警告/失败/错误计数）、每个场景卡片（状态、scenario_id、描述）及其失败断言与失败步骤明细；`report.json` 损坏或不可读时展示专门错误语义"report.json 损坏或不可读"；无场景数据时展示空态"暂无场景结果"（两种空态语义区分，对齐 v1）。

#### Scenario: 场景汇总与断言明细

- **WHEN** 打开有场景结果的 spec 详情的场景结果页签
- **THEN** 展示汇总计数与场景卡片列表，失败场景可展开断言明细（✓/✗ 与消息）

#### Scenario: 报告损坏语义

- **WHEN** report.json 存在但损坏/不可读
- **THEN** 页签展示"report.json 损坏或不可读"，而非与"暂无场景结果"混用

### Requirement: Bug 列表与失败截图页签

「Bug 列表」页签展示 bug 卡片（severity/来源/描述/关联场景/断言类型/证据），关联截图以缩略图呈现；「失败截图」页签展示全部失败截图缩略图，点击任意缩略图打开全屏 lightbox 预览（`/screenshots/<project>/<spec>/<file>`）。无数据页签展示对应空态文案（暂无 Bug / 暂无失败截图），页签项保持可见可点。

#### Scenario: Bug 卡片与截图缩略图

- **WHEN** 打开有 bug 记录的 spec 详情的 Bug 列表页签
- **THEN** 展示 bug 卡片列表，卡片内可见 severity 标识、描述与关联截图缩略图

#### Scenario: 截图 lightbox

- **WHEN** 用户点击任一截图缩略图
- **THEN** 打开放大预览（antd Image/Image.PreviewGroup 或等价 lightbox），可关闭

#### Scenario: 空页签保持可见

- **WHEN** 某 spec 无 bug 与截图数据
- **THEN** Bug 列表与失败截图页签仍可见可点，点开展示对应空态文案
