# 修复进度聚合与呈现

<!-- knowledge: capability=code-fix-progress rev=2
     sources=spec/archive/2026-09-26-add-code-review-auto-fix,spec/archive/2026-09-28-add-code-fix-batch-failure-selfheal -->

自动修复链的结构化进度快照、只读 API 与项目页进度呈现。

## 规则

### 进度快照
- 进度落盘为单文件覆盖式快照 `.fenix/code-review/fix-progress.json`（形态对齐 `.fenix/regression/last-run.json`），不依赖多轮历史。
- 结构至少含：`running`(bool)、`phase`(str)、`total`(int)、`done`(int)、`current`(str)、`batch_no`(int)、`reason`(可空)、`activation_id`(可空)、`chain_skipped`(条目 id 列表，可空)。
- `phase` 取值：`idle` / `selecting` / `fixing` / `regressing` / `retrying` / `merging` / `blocked` / `failed`。
- `activation_id` 由编排器在新激活链起点生成并持久化；同链内的自驱动再投递沿用同一值；读到 `running=true` 且 `activation_id` 未变时不得重算 `total`（否则每批收尾复位单飞后再投递会把 total 重置为已缩小的 open 数，前端出现进度倒退）。
- `total` = 本次激活链开始时的 `open` 条目总数（链内不变）；`done` = 实际被置 `resolved` 的条目累计数（各批 `mark_resolved` 命中数之和），不以批条数计（`skipped` 与未命中 `item_id` 不计入）。
- `running` 由编排器在途判据决定（`_in_flight` 标记或存在 `code-fix-` 前缀在飞 run），不得以「进度文件存在」近似判定。
- `chain_skipped` 为链内跳过集，承载本链被瞬态跳过的条目，选批排除口径含它；新链启动时重置为空（写侧显式传空覆盖），生命周期语义见 [code-fix-batch-selfheal](code-fix-batch-selfheal.md)。
- 进度文件缺失时读侧返回缺省态 `{running: false, phase: "idle", total: 0, done: 0, ...}`，不得报错。

### 只读 API
- `GET /api/code-review/fix-progress?project=<name>`：接受 `project` 参数，项目不存在/不可用 → 404；复用既有 code-review 进度路由的注册与守卫形态；纯读端点，不得触发任何激活或派发。

### 项目页呈现
- 「代码审查」页签读取该 API，呈现「已处理 {done}/{total} 条」、进度条（`percent=done/total*100`）、当前阶段与 `current` 描述；与既有「审查进行中」进度卡片同款式（`Card` + `Progress` + 次级文案），不引入新视觉范式。
- `running=true` 时按 2s 周期轮询（复用页签既有轮询形态）；结束或 `phase ∈ {blocked, failed}` 时停止轮询并刷新条目表格。
- 阻塞态展示原因文案，不得显示为「运行中」而无限轮询。
- `total` 为 0 或进度读取失败时静默降级（非关键路径），不得阻断页签既有代码审查列表与触发布局。
- 与既有代码审查进度（`GET /api/code-review/progress`）并存展示，二者不得共用同一响应字段互相覆盖；既有审查进度卡片、问题表格、手动触发按钮与「生成修复 SPEC」通道保持可用。

## 溯源

- 2026-09-26 2026-09-26-add-code-review-auto-fix — 新建本页：fix-progress.json 快照结构与 activation_id 链内 total 不变语义、只读进度 API、审查页签进度呈现与双进度并存。
- 2026-09-28 2026-09-28-add-code-fix-batch-failure-selfheal — 快照结构增 `chain_skipped` 链内跳过集字段及其新链重置语义。
