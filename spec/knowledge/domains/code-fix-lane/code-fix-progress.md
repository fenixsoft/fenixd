# 修复进度聚合与呈现

<!-- knowledge: capability=code-fix-progress rev=4
     sources=spec/archive/2026-09-26-add-code-review-auto-fix,spec/archive/2026-09-28-add-code-fix-batch-failure-selfheal,spec/knowledge/_inbox/done/memory-distill-unspec-landed-rules.md,spec/knowledge/_inbox/done/memory-distill-user-rulings.md -->

自动修复链的结构化进度快照、只读 API 与项目页进度呈现。

## 规则

### 进度快照
- 进度落盘为单文件覆盖式快照 `.fenix/code-review/fix-progress.json`（形态对齐 `.fenix/regression/last-run.json`），不依赖多轮历史。
- 结构至少含：`running`(bool)、`phase`(str)、`total`(int)、`done`(int)、`current`(str)、`batch_no`(int)、`reason`(可空)、`activation_id`(可空)、`chain_skipped`(条目 id 列表，可空)。
- `phase` 取值：`idle` / `selecting` / `fixing` / `regressing` / `retrying` / `merging` / `blocked` / `failed`。
- `activation_id` 由编排器在新激活链起点生成并持久化；同链内的自驱动再投递沿用同一值；同链再投递重算分母不产生进度倒退（活口径下 `done` 与 open 池在链内单调，见下条）。
- `total` 为活口径 `done + total_open`（`core/code_fix.py:5066`）：核销转移（`done`+1 / open−1）不变分母，链在飞期间新审查 arrivals 推高分母、外部核销缩小分母；链内 done 写点（如 `_process_deferred_merges`）不回写 `total`，不变式由公式自动保持。`done` = 实际被置 `resolved` 的条目累计数（各批 `mark_resolved` 命中数之和），不以批条数计（`skipped` 与未命中 `item_id` 不计入）。
- 分母语义取舍：链身份「稳定分母」与「中途 arrivals 可见」冲突时后者优先——进度条撒谎比分母跳动更伤。改 `total` 语义 MUST 跑 `test_chain_total_grows_on_midchain_new_items` 与 `test_activation_id_total_preserved_across_chain`（双测试锁「arrivals 推高 / 同链不变倒退」双向语义）。
- `running` 由编排器在途判据决定（`_in_flight` 标记或存在 `code-fix-` 前缀在飞 run），不得以「进度文件存在」近似判定。
- `chain_skipped` 为链内跳过集，承载本链被瞬态跳过的条目，选批排除口径含它；新链启动时重置为空（写侧显式传空覆盖），生命周期语义见 [code-fix-batch-selfheal](code-fix-batch-selfheal.md)。
- 进度文件缺失时读侧返回缺省态 `{running: false, phase: "idle", total: 0, done: 0, ...}`，不得报错。

### 只读 API
- `GET /api/code-review/fix-progress?project=<name>`：接受 `project` 参数，项目不存在/不可用 → 404；复用既有 code-review 进度路由的注册与守卫形态；纯读端点，不得触发任何激活或派发。

### 项目页呈现
- 可见性验收口径：修复链可以不推进到 100%，但不能没有显示——准备期与换挡期不得呈现为无进度的空档（空档会被感知为卡死）；可见性优先于进度精度，与分母语义取舍同取向。
- 「代码审查」页签读取该 API，呈现「已处理 {done}/{total} 条」、进度条（`percent=done/total*100`）、当前阶段与 `current` 描述；与既有「审查进行中」进度卡片同款式（`Card` + `Progress` + 次级文案），不引入新视觉范式。
- `running=true` 时按 2s 周期轮询（复用页签既有轮询形态）；结束或 `phase ∈ {blocked, failed}` 时停止轮询并刷新条目表格。
- 「宁停不错」的停轮询终态必须带环境性失败的恢复路径：进度卡片连续读取失败（约 6s）停轮询落红条后，监听 `visibilitychange`，回到可见即重置 retryKey 重启主轮询并立即补刷一帧（对齐列表/总览页既有补刷模式）——否则移动端切后台被掐 fetch 后回前台将永不恢复。验证手法：playwright route `--status=500` 持续 9s 复现红条 → unroute → dispatch visibilitychange → 2s 内恢复轮询。
- 阻塞态展示原因文案，不得显示为「运行中」而无限轮询。
- `total` 为 0 或进度读取失败时静默降级（非关键路径），不得阻断页签既有代码审查列表与触发布局。
- 与既有代码审查进度（`GET /api/code-review/progress`）并存展示，二者不得共用同一响应字段互相覆盖；既有审查进度卡片、问题表格、手动触发按钮与「生成修复 SPEC」通道保持可用。

## 溯源

- 2026-09-26 2026-09-26-add-code-review-auto-fix（spec/archive/2026-09-26-add-code-review-auto-fix） — 新建本页：fix-progress.json 快照结构与 activation_id 链内 total 不变语义、只读进度 API、审查页签进度呈现与双进度并存。
- 2026-09-28 2026-09-28-add-code-fix-batch-failure-selfheal（spec/archive/2026-09-28-add-code-fix-batch-failure-selfheal） — 快照结构增 `chain_skipped` 链内跳过集字段及其新链重置语义。
- 2026-11-04 memory-distill-unspec-landed-rules（spec/knowledge/_inbox/done/memory-distill-unspec-landed-rules.md） — 链进度 total 由「链首 open 定格」改写为活口径 done+total_open（核销转移不变分母、arrivals 推高/外部核销缩小，双测试锁双向语义）；进度卡片停轮询终态补 visibilitychange 恢复路径。
- 2026-11-04 memory-distill-user-rulings（spec/knowledge/_inbox/done/memory-distill-user-rulings.md） — 折叠可见性验收口径：可以不推进 100% 但不能没有显示，准备期空档即被感知为卡死，可见性优先于进度精度。
