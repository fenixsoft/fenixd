## ADDED Requirements

### Requirement: 质量分面问题表格

项目页「质量」分面 SHALL 展示当前代码仓的 code-review 问题台账，以可复选表格呈现。

- 表格 MUST 含列：严重度、问题、状态；MUST 支持按严重度 / 状态过滤与排序。
- 「问题」列 MUST 三行堆叠展示：第一行问题标题、第二行 `文件:行`、第三行内容（`[category] description`）。
- 内容行 MUST 最多显示两行（`ellipsis.rows=2`），超出部分 MUST 可通过悬浮浮层查看全文；浮层 MUST 形制对齐开发分面「名称」列（Popover + Markdown 渲染）。
- 表格 MUST 支持行复选（`rowSelection`），并显示已选条数。
- 表格 MUST 提供逐条「忽略」操作（行操作或操作列）：触发后调 `POST /api/code-review/items/status` 将条目置 `ignored`，成功后该条目 MUST 从默认列表移除——`ignored` 是「用户显式标记」而非「系统自动置入」的状态，其唯一入口就在本分面，缺此入口则 `code-review-items` 的状态机中 `ignored` 无法被触发。
- 表格 MUST 提供逐条「清除归属」操作（仅对 `in_spec` 条目）：把条目重置回 `open` 并清空 `spec_name`——否则条目一旦生成修复 SPEC 即被 `in_spec` 永久占用（`resolved` 仅由全仓核销置入、`ignored` 只是用户忽略），用户无法撤回误选。
- 默认列表 MUST 仅含 `open` 状态条目（`resolved` / `ignored` 默认隐藏，可经状态过滤查看）。
- 数据 MUST 经 `GET /api/code-review/items` 拉取，并随 SSE（`/api/stream`）与心跳兜底刷新，MUST NOT 仅在页面首次加载时拉取一次。
- 仅当「质量」分面被选中时才拉取数据与订阅；未选中时 MUST NOT 发起质量数据请求（保持 `project-page-tabs` 的按需加载语义）。

#### Scenario: 展示问题表格

- **WHEN** 用户切到项目 `A` 的「质量」分面且台账有 open 问题
- **THEN** MUST 显示问题表格（含严重度、问题、状态列）与行复选框；「问题」列每行含标题 / 文件:行 / 内容三行

#### Scenario: 未选中分面不发请求

- **WHEN** 用户停留在「开发」分面
- **THEN** 页面 MUST NOT 拉取 `/api/code-review/items` 或订阅质量相关事件

#### Scenario: 复选问题项

- **WHEN** 用户勾选表格中的若干行
- **THEN** 已选条数 MUST 实时更新，底部「生成修复 SPEC」按钮 MUST 在有选中项时可用、无选中项时禁用

### Requirement: 手动触发审查按钮

质量分面 SHALL 在问题表格右上角提供两个触发按钮：「全仓库审查」与「当期提交审查」。

- 两个触发按钮 MUST 使用同一视觉样式（同为默认 `outlined`，MUST NOT 一主一次）。
- 「全仓库审查」MUST 以 `scope=full` 调 `POST /api/code-review/run`。
- 「当期提交审查」MUST 以 `scope=window` 调 `POST /api/code-review/run`。
- 已有审查运行中时，再次点击 MUST 被拒绝（后端返回 409），前端 MUST 给出明确提示而非静默失败。
- 手动触发 MUST 走「写文件信号 → daemon 消费」链路；若该项目的文件信号无消费方（daemon 未运行或未受 supervisor 托管，`hosting_state == "unmanaged"`），后端 MUST 拒绝写信号并返回明确错误（先例 `request_spec_approve_push`：无人消费的信号会永久滞留，并可能在 daemon 下次启动时被消费成一次用户并未请求的审查），前端 MUST 原样提示该拒绝。
- 触发成功后 MUST 进入运行中态，展示进度条与取消按钮。

#### Scenario: 触发全仓审查

- **WHEN** 用户点击「全仓库审查」
- **THEN** 前端 MUST 调 `POST /api/code-review/run` 且 `scope=full`，并进入运行中态

#### Scenario: 触发本周期审查

- **WHEN** 用户点击「当期提交审查」
- **THEN** 前端 MUST 调 `POST /api/code-review/run` 且 `scope=window`

#### Scenario: 运行中重复触发被拒

- **WHEN** 一次审查运行中，用户再次点击任一触发按钮
- **THEN** 后端 MUST 返回 409，前端 MUST 提示「已有审查在进行中」，MUST NOT 启动第二个 run

### Requirement: 真实进度条与取消

手动触发审查后，质量分面 SHALL 展示基于文件总数的真实进度条与取消按钮。

- 运行中 MUST 轮询 `GET /api/code-review/progress`（或经 SSE）获取 `{running, total, done, current}`，并渲染真实百分比（`done/total`）。
- 进度条 MUST 展示当前正在审查的文件（`current`）。
- 取消按钮 MUST 调 `POST /api/run-cancel`（携带当前 `review_id` 映射的 run_id），成功后 MUST 给出受理反馈。
- 运行结束后 MUST 收起进度条与取消按钮，并刷新问题表格。
- 无运行中审查时 MUST NOT 显示进度条与取消按钮。

#### Scenario: 展示真实进度

- **WHEN** 一次全仓审查运行中（total=42，done=17，current=`core/foo.py`）
- **THEN** MUST 显示约 40% 的进度条与「当前：core/foo.py」文案

#### Scenario: 取消审查

- **WHEN** 用户在运行中点击取消
- **THEN** 前端 MUST 调 `POST /api/run-cancel`，随后进度 MUST 转为 `running=false`，进度条与取消按钮 MUST 收起

#### Scenario: 空闲时不显示进度区

- **WHEN** 当前无任何 code-review 运行
- **THEN** 分面 MUST NOT 渲染进度条或取消按钮

### Requirement: 生成修复 SPEC 入口

质量分面 SHALL 提供底部「生成修复 SPEC」按钮，把选中的问题项批量生成一个修复 SPEC。

- 按钮 MUST 仅在选中项数 > 0 时可用。
- 点击后 MUST 调 `POST /api/code-review/generate-spec`，body 携带选中 `item_ids`。
- 成功 MUST 提示生成的 SPEC 名，并从默认 open 列表移除已流转为 `in_spec` 的条目。

#### Scenario: 生成修复 SPEC

- **WHEN** 用户选中 3 条问题并点击「生成修复 SPEC」
- **THEN** 前端 MUST 调该端点，成功提示 SPEC 名，选中条目 MUST 变为 `in_spec` 并不再出现在 open 列表

#### Scenario: 无选中时禁用

- **WHEN** 表格无任何选中项
- **THEN**「生成修复 SPEC」按钮 MUST 处于禁用态
