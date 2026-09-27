# code-fix-lane — 批失败自愈语义改写（增量规格）

本变更改写 `add-code-review-auto-fix` 所立 `code-fix-lane` 能力中「批失败处置」分支的
既有 requirement：原「保留现场待人工 + 人工解除断重派」语义被「现场即弃 + 失败档案
预算内自动重试」取代（动机与机制见 `code-fix-batch-selfheal`）。成功路径、进度链身份、
手动授权链（manual_authorized）、回归锁根等 requirement 不变。

## MODIFIED Requirements

### Requirement: 批次编排循环

编排器 SHALL 按 `batch_size` 把台账 `open` 条目切成批，一批一次 `code-fix` run，通过全量回归的批合回主树后推进下一批；批收尾为三态（`success`/`consumed`/`halt`，语义见 `code-fix-batch-selfheal`），`success` 与 `consumed` 均自驱动推进下一批，仅 `halt` 终止链。

- 选批 MUST 取当前台账 `open` 条目中最早者优先（按 `first_seen_at` 升序，缺省按 `item_id` 稳定排序），每批条目数 MUST 为 `admin.code_review_fix.batch_size`（末批可少于该值）。
- 每批 MUST 新建一个从当前 HEAD 起的 worktree，MUST NOT 复用上一批合回后的 worktree。
- `worktree_manager.create(spec_name="code-review-fix", agent_type="code-fix")` 返回 `None`（同名锁占用 / git 建树失败）时 MUST 中止本次激活：不派 run、不合回，进度 `phase="failed"`、`reason="worktree_create_failed"`，条目保持 `open`（下一轮 full scan 重试）。
- 批收尾 MUST 释放现场：成功批 MUST 调 `worktree_manager.cleanup(wt_path, success=True)`；凡已建树的批失败路径（含两次回归均失败与合回冲突，语义见 `code-fix-batch-selfheal`）MUST 在收尾前清理 worktree 并释放 `code-review-fix:code-fix` 进程内 spec 锁，MUST NOT 保留现场等待人工（否则下一批 `create()` 因 `_spec_locks` 残留恒返回 `None`，车道在首批成功后即死）。
- run_id MUST 采用 `code-fix-<epoch>` 形式，MUST NOT 经 `_execute_agent`（不占 spec 维度预算、不计入每日 agent 计数）。
- 批 worker 收尾后 MUST 经 executor 再次投递检查点以推进下一批（三态中 `success`/`consumed`）；仅 `halt` 终止链不再投递；MUST NOT 在批 worker 内递归直调形成阻塞或嵌套。consumed 自驱动的收敛性由「consumed 批条目已全部离开可选池」保证（可选池严格单调缩小，循环必然终止）。
- 台账无 `open` 条目时，编排 MUST 收尾（进度 `running=false`），MUST NOT 空转派发。

#### Scenario: 按批大小切批

- **WHEN** 台账有 45 条 `open` 条目，`admin.code_review_fix.batch_size` 为 20
- **THEN** 编排 MUST 依次处理 20 条、20 条、5 条三批，逐批在通过回归后合回

#### Scenario: 批间推进

- **WHEN** 第 1 批（20 条）修复完成、全量回归通过、已合回主树且 worktree 已 cleanup
- **THEN** 编排 MUST 自动投递第 2 批 `code-fix` run，MUST NOT 等待下一轮 full scan

#### Scenario: 建树失败即收尾

- **WHEN** 某批调用 `worktree_manager.create` 返回 `None`
- **THEN** 编排 MUST NOT 派 `code-fix` run、MUST NOT 合回，进度 `phase` MUST 为 `failed` 且 `reason` 为 `worktree_create_failed`，条目 MUST 保持 `open`

#### Scenario: 无 open 条目收尾

- **WHEN** 台账当前无 `open` 条目
- **THEN** 编排检查点 MUST 返回 `no_open_items` 且 MUST NOT 投递任何 `code-fix` run

### Requirement: 全量回归门与合回

每批修复 SHALL 经全量回归通过后才合回主树，MUST NOT 在回归未通过时合回。

- 回归 MUST 复用 `core.regression.run_regression` 执行原语与项目 `verify.yaml` 的 `regression` 段契约。
- 回归 MUST 在**该批的 worktree 内**执行（针对该批修复后的代码）：执行根 = worktree，故 `run_regression` 的 `project_root` 参数取 worktree 路径。
- 回归执行 MUST 与主树共用同一把主机级套件锁：调用 MUST 显式传 `lock_root=<主树根>`，使锁文件为 `<主树根>/.fenix/full-suite.lock`，保证同一主机同一时刻只跑一套全量测试。
- 门面 `core/agent_runner/maintenance_runs.run_regression` SHALL 同时接受可选 `project_root`（缺省回落 `runner.project_root`）与 `lock_root`（缺省 `None`），二者透传至 `core.regression.run_and_write_regression` → `core.regression.run_regression`；既有调用点不传时语义逐字不变。
- worktree 内回归的快照随执行根落盘于 worktree（门禁用途），MUST NOT 被当作主树「测试回归」分面的数据源。
- 回归 `status == "passed"` 时 MUST 经 `worktree_manager.merge_back(wt_path)` 合回主树，MUST NOT 绕过既有 merge-back 闸门（merge-tree 预演 / WIP 重叠 / spec 目录在飞）。
- 合回成功后 MUST 把该批中**产物行 `status == "fixed"`** 的条目按 `item_id` 精确置 `resolved`，MUST NOT 置未参与该批的条目，MUST NOT 置被 agent 判为 `skipped` 的条目。
- **零有效修复拒合回**：批内产物行无一条 `status == "fixed"`，或 worktree 分支相对建树点无任何提交时，MUST NOT 合回、MUST NOT 置任何条目 `resolved`（`merge_back` 对「分支已是 HEAD 祖先」返回成功，无此守卫会把全 `skipped` 的批白洗成 `resolved`）；拒合回收尾 MUST 清理 worktree 并把该批条目写入进度快照 `chain_skipped`（链内跳过，语义见 `code-fix-batch-selfheal`），进度以非终态文案记原因 `no_effective_fix`，链继续推进下一批（零产物批按 halt 终止链会使最早队列头永久堵塞车道，违背批失败不堵塞的自愈目标）。

#### Scenario: 回归通过则合回并核销

- **WHEN** 第 1 批修复完成，产物行含 `status: fixed` 的条目，worktree 内全量回归 `status=passed`
- **THEN** 框架 MUST 把该批分支 merge-back 主树，并把该批 `fixed` 条目置 `resolved`（`skipped` 条目 MUST 保持 `open`），进度 `done` MUST 按实际置 `resolved` 的条数增加

#### Scenario: 零有效修复拒合回

- **WHEN** 某批产物行全部为 `status: skipped`（或 worktree 分支相对建树点无提交），且回归 `passed`
- **THEN** 框架 MUST NOT 合回、MUST NOT 置任何条目 `resolved`，worktree 被清理，该批条目写入 `chain_skipped`，链继续推进下一批（MUST NOT 终止链）

### Requirement: 回归失败的自动重试与丢弃

单批全量回归未通过时，系统 SHALL 自动重试一次；仍失败则**现场即弃**（MUST NOT 保留 worktree 待人工），条目入失败档案并按跨链重试预算自动重试（预算语义见 `code-fix-batch-selfheal`）。

- 首次回归非 `passed` 时 MUST 在**同一 worktree** 内再派一次 `code-fix` run，prompt MUST 注入上一轮回归的失败用例摘要。
- 第二次回归 `passed` 时 MUST 按正常路径合回并核销该批条目。
- 第二次回归仍未 `passed` 时 MUST 丢弃该批：MUST NOT 合回、MUST NOT 置 `resolved`，条目 MUST 保持 `open`（进入失败档案）。
- 丢弃时 MUST 在清理现场**前**把 `branch` 与 `tip_sha`（连同 `reason`、`failed_at`）写入失败档案记录，随后 MUST 清理失败 worktree 并释放 spec 锁（替代原「保留失败 worktree 不自动删除」语义；`branch`/`tip_sha` 留作 git reflog 追溯线索），并写入 warning 告警（含条目集与失败用例摘要，措辞为「已跳过，下轮自动重试」，MUST NOT 再表述为「待人工处置」）。
- 失败档案中的条目，后续检查点 MUST 跳过（同链内 MUST NOT 重复派发同一批）；新链启动时按 `fail_count` 预算自动释放（`fail_count < FAIL_RETRY_MAX`，等效原人工 `release_failed_batch`），预算内条目 MUST NOT 要求人工解除才能重试。
- 达到预算上限（`fail_count ≥ FAIL_RETRY_MAX`）的条目集 MUST 永久跳过，并在 `fail_count` 递增至上限那次入档时发一次性 warning 告警（点名录）、同时在 `.fenix/todo.md` 追加待人工清理项（替代原「每次丢弃即追加 todo 人工项」语义——预算内可自动重试的失败不产生人工项；todo 项指引按 `branch`/`tip_sha` 追溯，MUST NOT 再引用已清理的 worktree 路径）。

#### Scenario: 首次失败重试一次后成功

- **WHEN** 第 1 批首次回归 `status=failed`，重试后回归 `status=passed`
- **THEN** 框架 MUST 合回该批并核销条目，进度 `done` MUST 增加该批条数

#### Scenario: 重试仍失败则现场即弃并入档

- **WHEN** 第 1 批两次回归均非 `passed`
- **THEN** 框架 MUST NOT 合回、MUST NOT 置 `resolved`，失败档案记录含 `branch`/`tip_sha`/`reason`/`failed_at`，worktree 被清理（spec 锁释放），warning 告警措辞为「已跳过，下轮自动重试」，条目 MUST 保持 `open`，链继续推进下一批

#### Scenario: 预算内失败批下轮自动重试

- **WHEN** 上一轮因回归失败丢弃了第 1 批（条目在失败档案且 `fail_count < FAIL_RETRY_MAX`），其后新链启动
- **THEN** 检查点 MUST 自动释放该记录并重新组批该批条目，MUST NOT 要求人工调 `release_failed_batch` 解除
