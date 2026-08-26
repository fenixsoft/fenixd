## ADDED Requirements

### Requirement: SPEC 行提供「背景」「设计」按钮

系统 SHALL 在 SPEC 列表页（项目视图）的每一行 SPEC 内提供「背景」「设计」两个操作按钮，分别对应读取该 SPEC 的 `proposal.md` 与 `design.md`。按钮 SHALL 始终可见（不要求文档文件存在）。点击按钮 SHALL 触发展示文档，且 SHALL 不触发行级跳转（进入详情页）的既有交互；点击行其余区域 SHALL 保持原有跳转行为。

#### Scenario: 每行均可看到两个按钮
- **WHEN** 打开项目视图，某 SPEC 行正常渲染
- **THEN** 该行内显示「背景」「设计」两个按钮

#### Scenario: 点按钮不触发进入详情
- **WHEN** 点击某行的「背景」按钮
- **THEN** 弹窗打开该 SPEC 的 proposal 文档，页面 URL 不变，未跳转到 SPEC 详情视图

#### Scenario: 点行空白区域仍进入详情
- **WHEN** 点击该行非按钮区域的空白处
- **THEN** 跳转到该 SPEC 详情视图（既有行为不变）

### Requirement: 文档弹窗展示

系统 SHALL 在点击「背景」或「设计」按钮时于当前页弹出模态窗展示对应文档：标题包含 SPEC 名称与文档类型（「背景」/"背景" 对应 proposal，`design` 对应「设计」）；正文 SHALL 以 Markdown 渲染（复用既有 `marked` 渲染管线，支持 GFM 语法，执行既有链接白名单与转义约束）。弹窗 SHALL 支持通过关闭按钮、点击遮罩关闭；加载期间 SHALL 显示加载状态。弹窗打开期间 SHALL 不阻塞列表页状态，关闭后列表页保持原状。

#### Scenario: 打开并渲染 Markdown 文档
- **WHEN** 某 SPEC 存在 proposal.md（含标题、列表、代码块等 Markdown 语法），点击其「背景」按钮
- **THEN** 弹窗标题显示 SPEC 名称与「背景」，正文为渲染后的格式（标题变粗、列表带符号、代码块等宽），而非原始文本

#### Scenario: 加载与异步失败
- **WHEN** 点击按钮后网络请求未返回时显示加载占位；请求失败（非 200/404、网络中断）
- **THEN** 弹窗内显示错误提示，不显示空文档

### Requirement: 文档缺失空态

系统 SHALL 在该 SPEC 的 `proposal.md` 或 `design.md` 文件不存在时，于弹窗内展示明确的空态提示（如「该 spec 未提供背景/设计文档」），而非空白或报错。两个按钮在文档缺失时 SHALL 保持可见可点。

#### Scenario: 缺失文档显示空态
- **WHEN** 某 SPEC 没有 design.md，点击其「设计」按钮
- **THEN** 弹窗正常打开，正文显示「该 spec 未提供设计文档」一类空态文案