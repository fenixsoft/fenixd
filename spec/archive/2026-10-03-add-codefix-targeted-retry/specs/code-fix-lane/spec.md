# code-fix-lane delta：定向重试轮

## MODIFIED Requirements

### Requirement: 全量回归门与合回

每批修复 SHALL 经回归通过后才合回主树，MUST NOT 在回归未通过时合回。回归门范围分轮：**首轮为全量回归；定向重试轮（见「回归失败的自动重试与丢弃」）的回归范围为上一轮失败用例集，定向重试轮回归通过即视为该批回归门通过**。

- 回归 MUST 复用 `core.regression.run_regression` 执行原语与项目 `verify.yaml` 的 `regression` 段契约。
- 回归 MUST 在**该批的 worktree 内**执行（针对该批修复后的代码）：执行根 = worktree，故 `run_regression` 的 `project_root` 参数取 worktree 路径。
- 回归执行 MUST 与主树共用同一把主机级套件锁：调用 MUST 显式传 `lock_root=<主树根>`，使锁文件为 `<主树根>/.fenix/full-suite.lock`，保证同一主机同一时刻只跑一套全量测试。
- 门面 `core/agent_runner/maintenance_runs.run_regression` SHALL 同时接受可选 `project_root`（缺省回落 `runner.project_root`）与 `lock_root`（缺省 `None`），二者透传至 `core.regression.run_and_write_regression` → `core.regression.run_regression`；既有调用点不传时语义逐字不变。
- **定向子集执行**：门面 SHALL 另接受可选失败用例集参数；项目命令为 pytest 形态时 MUST 以该子集 nodeids **取代命令中的既有收集位置参数**（如 `tests/` 目录，保留 `-q`/`--junit-xml` 等非收集旗标）的方式只执行该子集，MUST NOT 在命令尾部追加 nodeid（pytest 多位置参数为收集目标并集，追加会静默退化全量）；子集为空或项目命令非 pytest 形态时 MUST 回退全量（fail-closed 到现状语义）。主机级锁与执行根语义对子集执行逐字不变。
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

#### Scenario: 定向轮通过即过回归门

- **WHEN** 首轮全量回归失败 k 例，定向重试轮修复后子集回归（只重跑 k 例）`status=passed`
- **THEN** 该批视为回归门通过，MUST 按正常路径合回并核销，MUST NOT 再强制执行一次全量回归

### Requirement: 回归失败的自动重试与丢弃

单批首轮全量回归未通过时，系统 SHALL 进入**定向重试轮**（上限 `admin.code_review_fix.targeted_retry_max`，缺省 3）：每轮在同一 worktree 内派一次 `code-fix` run，prompt MUST 注入上一轮失败用例的结构化明细（nodeid + 失败摘要），并明确指令**只修复与失败用例相关的问题，MUST NOT 扩面重做全批**；修复对象由 agent 依据用例信息判定——可以是产品代码缺陷，也可以是测试本身缺陷（断言过时、替身失真、超时替身自旋类）。耗尽轮数仍失败则**现场即弃**（语义同原「两次回归均失败」，MUST NOT 保留 worktree 待人工），条目入失败档案并按跨链重试预算自动重试（预算语义见 `code-fix-batch-selfheal`）。

- 失败用例明细 MUST 结构化落盘（nodeid + 失败摘要，如 `.fenix/code-review/fix-reg-failures-<run_id>.json`，首轮与每个定向轮回归非 passed 时各落一份、文件名含该轮 run_id），供重试注入与事后审计；nodeid 映射以 junit `classname` 主导重构（pytest junitxml 不产 `file` 属性属预期，MUST NOT 因此判映射失败），映射失败（不足以唯一重构 nodeid）时 MUST 回退为全量重试（fail-closed 到现状语义）并留日志。
- 每轮重试 MUST 在**同一 worktree** 内进行；轮间 MUST 注入累计失败明细（上一轮失败集，含此前修过的用例若再次失败）。
- 某定向轮回归（失败子集重跑）`passed` 时 MUST 按正常路径合回并核销该批条目。
- 耗尽 `targeted_retry_max` 轮仍未 `passed` 时 MUST 丢弃该批：MUST NOT 合回、MUST NOT 置 `resolved`，条目 MUST 保持 `open`（进入失败档案）。
- 丢弃时 MUST 在清理现场**前**把 `branch` 与 `tip_sha`（连同 `reason`、`failed_at`、最后一轮失败用例明细引用）写入失败档案记录，随后 MUST 清理失败 worktree 并释放 spec 锁，并写入 warning 告警（含条目集与失败用例摘要，措辞为「已跳过，下轮自动重试」，MUST NOT 再表述为「待人工处置」）。
- 失败档案中的条目，后续检查点 MUST 跳过（同链内 MUST NOT 重复派发同一批）；新链启动时按 `fail_count` 预算自动释放（`fail_count < FAIL_RETRY_MAX`），预算内条目 MUST NOT 要求人工解除才能重试。
- 达到预算上限（`fail_count ≥ FAIL_RETRY_MAX`）的条目集 MUST 永久跳过，并在 `fail_count` 递增至上限那次入档时发一次性 warning 告警（点名录）、同时在 `.fenix/todo.md` 追加待人工清理项。

#### Scenario: 定向轮修复后通过

- **WHEN** 首轮全量回归失败 3 例，第 1 轮定向重试只修复该 3 例相关问题，子集回归只重跑该 3 例且通过
- **THEN** 框架 MUST 合回该批并核销条目，MUST NOT 重跑全量回归，子集回归的实际执行用例数 MUST 等于失败集大小

#### Scenario: 测试自身缺陷被修复

- **WHEN** 失败用例经 agent 判定为测试本身缺陷（如断言过时、替身真自旋）且修复测试后子集回归通过
- **THEN** 框架 MUST 按通过路径合回，且该轮产物行 MUST 带 `fix_scope=test` 标注供审计

#### Scenario: 轮数耗尽现场即弃

- **WHEN** 连续 `targeted_retry_max`（缺省 3）轮定向重试后子集回归仍失败
- **THEN** 框架 MUST 按既有丢弃语义入失败档案（`branch`/`tip_sha`/明细引用入档）、清理 worktree、释放 spec 锁、链继续推进下一批

#### Scenario: 首轮通过零定向轮

- **WHEN** 某批首轮全量回归 `passed`
- **THEN** MUST NOT 派任何定向轮，主路径行为与现状逐字一致

#### Scenario: 预算内失败批下轮自动重试

- **WHEN** 上一轮因定向轮耗尽丢弃了第 1 批（条目在失败档案且 `fail_count < FAIL_RETRY_MAX`），其后新链启动
- **THEN** 检查点 MUST 自动释放该记录并重新组批该批条目（重组批从首轮全量回归起重新走本轮 SPEC 的门与定向轮语义），MUST NOT 要求人工调 `release_failed_batch` 解除
