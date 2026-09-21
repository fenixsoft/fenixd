## ADDED Requirements

### Requirement: 自动修复进度结构

系统 SHALL 把自动修复的工作情况以结构化进度暴露，供 Dashboard 呈现「已处理数 / 总数 / 进度条」。

- 进度 MUST 落盘为单文件覆盖式快照 `.fenix/code-review/fix-progress.json`（形态对齐既有 `.fenix/regression/last-run.json`），MUST NOT 依赖多轮历史。
- 结构 MUST 至少含：`running`（bool）、`phase`（字符串）、`total`（int）、`done`（int）、`current`（字符串）、`batch_no`（int）、`reason`（失败/阻塞原因，可为空）。
- `total` MUST 为本次激活开始时的 `open` 条目总数（激活期间不变的快照）；`done` MUST 为已合回主树的条目累计数。
- `phase` MUST 取下列之一：`idle` / `selecting` / `fixing` / `regressing` / `retrying` / `merging` / `blocked` / `failed`。
- `running` MUST 由编排器在途判据决定（`_in_flight` 标记或存在 `code-fix-` 前缀在飞 run），MUST NOT 以「进度文件存在」近似判定。
- 进度文件缺失时，读侧 MUST 返回 `{running: false, phase: "idle", total: 0, done: 0, ...}` 的缺省态，MUST NOT 报错。

#### Scenario: 修复中可查真实进度

- **WHEN** 本次激活 `open` 总数 60，已合回 20 条，当前正在修复第 2 批
- **THEN** `GET /api/code-review/fix-progress` MUST 返回 `running=true, phase="fixing", total=60, done=20, batch_no=2`，前端据此渲染进度条

#### Scenario: 无进度文件返回缺省态

- **WHEN** 从未有过自动修复激活（`.fenix/code-review/fix-progress.json` 不存在）
- **THEN** 读侧 MUST 返回 `running=false, phase="idle", total=0, done=0`，MUST NOT 抛异常或 500

### Requirement: 进度只读 API

系统 SHALL 暴露只读端点 `GET /api/code-review/fix-progress`，MUST NOT 有副作用。

- 端点 MUST 接受 `project` query 参数；项目不存在/不可用 → 404。
- 端点 MUST 复用既有 code-review 进度路由的注册与守卫形态（`_project_from_query` + `self._json` / `self._error`）。
- 端点 MUST NOT 触发任何激活或派发（纯读）。

#### Scenario: 读取进度

- **WHEN** 客户端请求 `GET /api/code-review/fix-progress?project=fenixd`
- **THEN** 服务 MUST 返回 `{running, phase, total, done, current, batch_no, reason}`，状态码 200

#### Scenario: 未知项目 404

- **WHEN** 客户端请求 `GET /api/code-review/fix-progress?project=不存在的项目`
- **THEN** 服务 MUST 返回 404

### Requirement: 项目页呈现自动修复进度

项目页「代码审查」页签 SHALL 呈现自动修复的工作情况，含已处理数量、总数与进度条。

- 页签 MUST 读取 `GET /api/code-review/fix-progress` 并呈现：`已处理 {done}/{total} 条`、`Progress percent={done/total*100}`、当前阶段与 `current` 描述。
- `running` 为 true 时 MUST 周期轮询（复用页签既有 2s 轮询形态），结束或 `phase ∈ {blocked, failed}` 时 MUST 停止轮询并刷新条目表格。
- `total` 为 0 或进度读取失败时 MUST 静默降级（非关键路径），MUST NOT 阻断页签既有代码审查列表与触发布局。
- 呈现 MUST 与既有「审查进行中」进度卡片同款式（`Card` + `Progress` + 次级文案），MUST NOT 引入新的视觉范式。

#### Scenario: 显示已处理/总数与进度条

- **WHEN** 自动修复进行中，`total=60`、`done=40`
- **THEN** 页签 MUST 显示「已处理 40/60 条」与约 67% 的进度条，并在运行中每 2 秒刷新

#### Scenario: 阻塞态可见原因

- **WHEN** 进度 `phase="blocked"`、`reason="regression_contract_missing"`
- **THEN** 页签 MUST 展示阻塞态与原因文案，MUST NOT 显示为「运行中」而无限轮询

### Requirement: 进度不影响既有审查呈现

自动修复进度 SHALL 与既有代码审查进度并存展示，MUST NOT 替换或屏蔽后者。

- 页签 MUST 同时可读到代码审查进度（`GET /api/code-review/progress`）与自动修复进度（`GET /api/code-review/fix-progress`），二者 MUST NOT 共用同一响应字段而互相覆盖。
- 既有审查进度卡片、问题表格、手动触发按钮与「生成修复 SPEC」通道 MUST 保持可用。

#### Scenario: 两条进度并存

- **WHEN** 一次 code-review run 在跑，同时自动修复正在处理上一轮已落账的条目
- **THEN** 页签 MUST 同时呈现审查进度与自动修复进度，任一 MUST NOT 覆盖另一者
