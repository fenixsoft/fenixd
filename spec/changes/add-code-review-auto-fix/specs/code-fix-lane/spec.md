## ADDED Requirements

### Requirement: 两路自动激活

系统 SHALL 在两条路径上自动激活自动修复编排，MUST NOT 依赖用户手工触发。

- **路径一（审查收尾）**：`run_code_review` 成功收尾且本轮落账产生了 `open` 条目时，MUST 立即触发一次编排检查点。
- **路径二（周期兜底）**：daemon 的 full scan（`event_bus._run_full_scan_body`，默认 30 分钟周期）每轮 MUST 调用一次编排检查点，用于覆盖 daemon 重启、异常中断后的续做。
- 两条路径 MUST 汇入**同一个**检查点入口（单一实现），MUST NOT 各写一套激活逻辑。
- 编排器未装配（测试/禁用态）时，调用点 MUST 静默跳过，MUST NOT 抛穿调用方（评审车道异常不得影响审查 run 与 full scan 的既有判定）。

#### Scenario: 审查结束立即激活

- **WHEN** 一次 code-review run 收尾并落账产生 40 条 `open` 条目，`admin.code_review_fix.enabled` 为 true
- **THEN** 编排检查点 MUST 在审查 run 收尾路径上被触发，MUST 投递第 1 批 `code-fix` run

#### Scenario: 审查零产出不激活

- **WHEN** 一次 code-review run 收尾但本轮未产生任何新的 `open` 条目
- **THEN** 编排检查点 MUST NOT 因该次审查而投递 `code-fix` run

#### Scenario: 周期兜底续做

- **WHEN** daemon 重启后台账仍存在未处理的 `open` 条目，且无 `code-fix` run 在跑
- **THEN** 下一轮 full scan MUST 触发编排检查点并投递 `code-fix` run

### Requirement: 批次编排循环

编排器 SHALL 按 `batch_size` 把台账 `open` 条目切成批，一批一次 `code-fix` run，通过全量回归的批合回主树后推进下一批。

- 选批 MUST 取当前台账 `open` 条目中最早者优先（按 `first_seen_at` 升序，缺省按 `item_id` 稳定排序），每批条目数 MUST 为 `admin.code_review_fix.batch_size`（末批可少于该值）。
- 每批 MUST 新建一个从当前 HEAD 起的 worktree，MUST NOT 复用上一批合回后的 worktree。
- run_id MUST 采用 `code-fix-<epoch>` 形式，MUST NOT 经 `_execute_agent`（不占 spec 维度预算、不计入每日 agent 计数）。
- 批 worker 收尾后 MUST 经 executor 再次投递检查点以推进下一批；MUST NOT 在批 worker 内递归直调形成阻塞或嵌套。
- 台账无 `open` 条目时，编排 MUST 收尾（进度 `running=false`），MUST NOT 空转派发。

#### Scenario: 按批大小切批

- **WHEN** 台账有 45 条 `open` 条目，`admin.code_review_fix.batch_size` 为 20
- **THEN** 编排 MUST 依次处理 20 条、20 条、5 条三批，逐批在通过回归后合回

#### Scenario: 批间推进

- **WHEN** 第 1 批（20 条）修复完成、全量回归通过、已合回主树
- **THEN** 编排 MUST 自动投递第 2 批 `code-fix` run，MUST NOT 等待下一轮 full scan

#### Scenario: 无 open 条目收尾

- **WHEN** 台账当前无 `open` 条目
- **THEN** 编排检查点 MUST 返回 `no_open_items` 且 MUST NOT 投递任何 `code-fix` run

### Requirement: 幂等与单飞

系统 SHALL 保证同一时刻至多一个自动修复激活在跑，MUST NOT 重复激活。

- 守卫链（任一命中即不投递）：`admin.code_review_fix.enabled` 为 false → `disabled`；已有 `code-fix` run 在跑（编排器 `_in_flight` 标记，或 `_running_agents` 中存在 `code-fix-` 前缀 run）→ `already_running`；无 `open` 条目 → `no_open_items`；回归契约不可用 → `regression_contract_missing`（见 fail-closed 需求）。
- 单飞标记 MUST 在投递时置位、批 worker 收尾时复位（形态对齐既有 `_code_review_in_flight` / `_regression_in_flight`）。
- 两条激活路径并发到达时，MUST 由同一把锁保证至多一次投递。

#### Scenario: 已有 run 在跑不重复激活

- **WHEN** 已存在 run_id 为 `code-fix-1758211200` 的在飞 run，30 分钟 full scan 到达
- **THEN** 编排检查点 MUST 返回 `already_running` 且 MUST NOT 投递第二个 `code-fix` run

#### Scenario: 开关关闭零动作

- **WHEN** `admin.code_review_fix.enabled` 为 false
- **THEN** 无论审查是否产出 `open` 条目、无论 full scan 是否到达，编排 MUST NOT 选批、MUST NOT 派 run、MUST NOT 写进度文件

### Requirement: 全量回归门与合回

每批修复 SHALL 经全量回归通过后才合回主树，MUST NOT 在回归未通过时合回。

- 回归 MUST 复用 `core.regression.run_regression` 执行原语与项目 `verify.yaml` 的 `regression` 段契约。
- 回归 MUST 在**该批的 worktree 内**执行（针对该批修复后的代码）。
- 回归执行 MUST 与主树共用同一把主机级套件锁（`run_regression` 的锁根锚定主树），保证同一主机同一时刻只跑一套全量测试。
- 回归 `status == "passed"` 时 MUST 经 `worktree_manager.merge_back(wt_path)` 合回主树，MUST NOT 绕过既有 merge-back 闸门（merge-tree 预演 / WIP 重叠 / spec 目录在飞）。
- 合回成功后 MUST 把该批条目按 `item_id` 精确置 `resolved`，MUST NOT 置未参与该批的条目。

#### Scenario: 回归通过则合回并核销

- **WHEN** 第 1 批修复完成，worktree 内全量回归 `status=passed`
- **THEN** 框架 MUST 把该批分支 merge-back 主树，并把该批 20 条条目置 `resolved`，进度 `done` MUST 增加 20

#### Scenario: 回归未通过绝不合回

- **WHEN** 回归 `status=failed`
- **THEN** 框架 MUST NOT 合回该批分支，MUST NOT 把该批任何条目置 `resolved`

#### Scenario: 回归与主树共用主机级锁

- **WHEN** 主树正在执行一次周期全量回归（持有 `.fenix/full-suite.lock`），code-fix 批 worker 需要跑回归
- **THEN** code-fix 的回归 MUST 与主树争抢同一把锁（`run_regression` 的锁根为主树），MUST NOT 在 worktree 上另立一把锁并行执行

### Requirement: 回归契约缺失时 fail-closed 并复用 AI 起草

项目 `verify.yaml` 无有效 `regression` 段时，系统 SHALL fail-closed（不合回）并复用既有 AI 契约起草通道补齐，MUST NOT 回退任何框架专用脚本。

- 检测 MUST 经 `load_verify_contract(project_root)` 的 `regression` 字段是否为 None。
- 缺失/无效时 MUST 经既有 `AdminStore` 写入 `verify_contract_missing` 信号（payload 形态对齐既有 `_write_verify_contract_missing`），由既有 administrator agent 起草流程生成 `regression` 段并自证落位。
- 本次激活 MUST NOT 派批、MUST NOT 合回，进度 MUST 记 `phase=blocked`、`reason=regression_contract_missing`。
- 起草完成后的下一轮 full scan MUST 能正常进入批次处理（MUST NOT 需要人工额外操作）。
- MUST NOT 回退到框架专用脚本（如 `bin/run_full_suite.py`）作为通用项目的回归命令（那属项目级特殊处理）。

#### Scenario: 无 regression 段则阻塞并呼叫起草

- **WHEN** 台账有 `open` 条目、开关开启，但项目 `verify.yaml` 无 `regression` 段
- **THEN** 编排 MUST NOT 投递 `code-fix` run，MUST 写 `verify_contract_missing` 信号，进度 `phase` MUST 为 `blocked` 且 `reason` 为 `regression_contract_missing`

#### Scenario: 起草完成后自动续做

- **WHEN** 上一条场景中的起草已完成，`verify.yaml` 已含有效 `regression` 段，且无 `code-fix` 在跑
- **THEN** 下一轮 full scan MUST 正常投递第 1 批 `code-fix` run，MUST NOT 要求人工再次激活

### Requirement: 回归失败的自动重试与丢弃

单批全量回归未通过时，系统 SHALL 自动重试一次，仍失败则丢弃该批并保留证据供人工处置。

- 首次回归非 `passed` 时 MUST 在**同一 worktree** 内再派一次 `code-fix` run，prompt MUST 注入上一轮回归的失败用例摘要。
- 第二次回归 `passed` 时 MUST 按正常路径合回并核销该批条目。
- 第二次回归仍未 `passed` 时 MUST 丢弃该批：MUST NOT 合回、MUST NOT 置 `resolved`，条目 MUST 保持 `open`，进度 MUST 记 `phase=failed` 与失败原因。
- 丢弃时 MUST 保留失败 worktree（不自动删除）并写入告警信号（含 worktree 路径与失败用例摘要），供人工排查。
- 在存在未清理的失败 worktree 且对应条目集合尚未被人工处理时，后续检查点 MUST 跳过该批条目集合，MUST NOT 重复派发同一批。

#### Scenario: 首次失败重试一次后成功

- **WHEN** 第 1 批首次回归 `status=failed`，重试后回归 `status=passed`
- **THEN** 框架 MUST 合回该批并核销条目，进度 `done` MUST 增加该批条数

#### Scenario: 重试仍失败则丢弃并告警

- **WHEN** 第 1 批两次回归均非 `passed`
- **THEN** 框架 MUST NOT 合回、MUST NOT 置 `resolved`，MUST 保留 worktree 并写失败告警，条目 MUST 保持 `open`，进度 `phase` MUST 为 `failed`

#### Scenario: 失败批不被重复派发

- **WHEN** 上一轮因回归失败丢弃了第 1 批（worktree 保留，条目仍 `open`）
- **THEN** 下一轮检查点 MUST 跳过该批条目集合，MUST NOT 立即重新派发同一批，除非人工清理失败 worktree 后解除

### Requirement: 回归执行锁根可锚定主树

`core.regression.run_regression` SHALL 支持把主机级套件锁锚定到主树根，供 worktree 内调用者与主树共用同一把锁。

- 函数 MUST 新增可选参数 `lock_root`（缺省 `None` → 回落 `project_root`），既有调用点语义 MUST 逐字不变（零迁移）。
- `lock_root` 非 None 时，锁文件路径 MUST 取 `lock_root/.fenix/full-suite.lock`，而回归命令的工作目录 MUST 仍为传入的 `project_root`（worktree 根）。

#### Scenario: 缺省零迁移

- **WHEN** 既有调用点（周期回归检查点 / 手动信号消费 / `maintenance_runs.run_regression`）不传 `lock_root`
- **THEN** 锁路径 MUST 与改动前一致（`project_root/.fenix/full-suite.lock`），行为 MUST 逐字不变

#### Scenario: 锚定主树后与主树互斥

- **WHEN** code-fix 调用 `run_regression(worktree_root, spec, lock_root=<main_root>)`
- **THEN** 锁文件 MUST 为 `<main_root>/.fenix/full-suite.lock`，回归命令 cwd MUST 为 `worktree_root`
