# 自动修复车道编排

<!-- knowledge: capability=code-fix-lane rev=2
     sources=spec/archive/2026-09-26-add-code-review-auto-fix,spec/archive/2026-09-28-add-code-fix-batch-failure-selfheal -->

把代码审查落账的 `open` 缺陷条目按批自动修复、经全量回归后合回主树的编排车道，由 daemon 内的编排检查点驱动。

## 规则

### 激活
- 两路自动激活，MUST 汇入同一检查点入口（单一实现）：审查收尾路——`run_code_review` 成功收尾且本轮落账产生 `open` 条目时立即触发；周期兜底路——daemon full scan（默认 30 分钟周期）每轮触发一次，覆盖 daemon 重启、异常中断后的续做。
- 编排器未装配（测试/禁用态）时调用点静默跳过，不得抛穿调用方（评审车道异常不得影响审查 run 与 full scan 的既有判定）。
- 审查收尾零新 `open` 条目时不因该次审查激活。

### 守卫链与单飞
- 检查点按序守卫，任一命中即不投递：`admin.code_review_fix.enabled` 为 false → `disabled`；已有 code-fix run 在跑（编排器 `_in_flight` 标记，或 `_running_agents` 存在 `code-fix-` 前缀 run）→ `already_running`；无 `open` 条目 → `no_open_items`；回归契约不可用 → `regression_contract_missing`。
- 单飞标记投递时置位、批 worker 收尾时复位；两条激活路径并发到达由同一把锁保证至多一次投递。

### 批次编排
- 选批取台账 `open` 条目最早优先（按 `first_seen_at` 升序，缺省按 `item_id` 稳定排序），每批条目数 = `admin.code_review_fix.batch_size`（末批可少）；排除集 = 失败档案条目并集 ∪ `chain_skipped`（跳过语义见 [code-fix-batch-selfheal](code-fix-batch-selfheal.md)）。
- 每批新建从当前 HEAD 起的独立 worktree（`worktree_manager.create(spec_name="code-review-fix", agent_type="code-fix")`），不复用上一批合回后的 worktree。
- `create()` 返回 `None`（同名锁占用 / git 建树失败）时中止本次激活：不派 run、不合回，进度 `phase=failed`、`reason=worktree_create_failed`，条目保持 `open` 待下一轮 full scan 重试。
- 批收尾为三态：`success`（合回并核销）/ `consumed`（该批条目已全部离开可选池）/ `halt`（环境性失败）；`success` 与 `consumed` 均自驱动推进下一批，仅 `halt` 终止链，完整路径映射与收敛保证见 [code-fix-batch-selfheal](code-fix-batch-selfheal.md)。
- 凡已建树的批（成功或失败）收尾 MUST 清理 worktree 并释放 `code-review-fix:code-fix` 进程内 spec 锁，MUST NOT 保留现场等待人工——`_spec_locks` 残留使后续 `create()` 恒返回 `None`，车道在首批之后即死；成功批调 `cleanup(wt_path, success=True)`。
- run_id 采用 `code-fix-<epoch>` 形式，不经 `_execute_agent`（不占 spec 维度预算、不计入每日 agent 计数）。
- 批 worker 收尾后经 executor 再次投递检查点推进下一批（`success`/`consumed`），仅 `halt` 终止链、不投递，不得批内递归直调；台账无 `open` 条目时编排收尾（`running=false`），不空转派发。

### 全量回归门与合回
- 回归复用 `core.regression.run_regression` 执行原语与项目 `verify.yaml` 的 `regression` 段契约，在该批 worktree 内执行（执行根 = worktree）。
- 回归与主树共用主机级套件锁：调用显式传 `lock_root=<主树根>`，锁文件为 `<主树根>/.fenix/full-suite.lock`；锁根锚定后回归命令工作目录仍为 worktree 根。`lock_root` 缺省回落 `project_root`，既有调用点零迁移；门面 `core/agent_runner/maintenance_runs.run_regression` 同步透传 `project_root` 与 `lock_root`。
- 回归 `passed` 时经 `worktree_manager.merge_back(wt_path)` 合回，不得绕过既有 merge-back 闸门（merge-tree 预演 / WIP 重叠 / spec 目录在飞）。
- 合回后仅把该批中产物行 `status == "fixed"` 的条目按 `item_id` 精确置 `resolved`，不置未参与该批的条目，不置 agent 判 `skipped` 的条目。
- 零有效修复拒合回：批内产物行无一条 `fixed`，或 worktree 分支相对建树点无任何提交时，不合回、不置任何条目 `resolved`（防止全 `skipped` 的批被白洗成 `resolved`）；收尾清理 worktree，该批条目写入 `chain_skipped`，进度以非终态文案记原因 `no_effective_fix`，链继续推进下一批——零产物批按 `halt` 终止链会使最早队列头永久堵塞车道。
- worktree 内回归快照随执行根落盘于 worktree，不作为主树「测试回归」分面的数据源。

### 回归契约缺失 fail-closed
- 项目 `verify.yaml` 无有效 `regression` 段时不派批、不合回，按契约状态分流写信号（经 AdminStore，severity=major）：契约整体缺失（`contract is None`）→ `verify_contract_missing`（administrator 起草完整契约）；契约有效但缺 regression 段 → `verify_regression_missing`（administrator 仅补段，不得动 prepare/serve/ready）。
- 两种缺失下进度均记 `phase=blocked`，`reason` 分别为 `regression_contract_missing` / `regression_section_missing`。
- 起草完成后的下一轮 full scan 自动进入批次处理，不需人工再激活；不得回退框架专用脚本（如 `bin/run_full_suite.py`）作为通用项目的回归命令。

### 回归失败重试与丢弃
- 首次回归非 `passed` 时在同一 worktree 内再派一次 code-fix run，prompt 注入上一轮失败用例摘要；第二次 `passed` 按正常路径合回核销。
- 第二次仍未 `passed` 时现场即弃：不合回、不核销，条目保持 `open`；清理前把 `branch`、`tip_sha`、`reason`、`failed_at` 写入失败档案记录，随后清理 worktree 并释放 spec 锁（`branch`/`tip_sha` 留作 git reflog 追溯线索，不承担恢复职责）；warning 告警含条目集与失败用例摘要，措辞为「已跳过，下轮自动重试」，不得表述为「待人工处置」。
- 失败档案条目后续检查点跳过（同链内不重复派发同一批）；新链启动按 `fail_count` 预算自动释放（`fail_count < FAIL_RETRY_MAX`），预算内条目不要求人工解除即可重试。
- 达预算上限（`fail_count ≥ FAIL_RETRY_MAX`）的条目集永久跳过；预算用尽那次入档发一次性 warning 点名录告警，并在 `.fenix/todo.md` 追加待人工清理项（指引按 `branch`/`tip_sha` 追溯，不得引用已清理的 worktree 路径）。重试预算语义见 [code-fix-batch-selfheal](code-fix-batch-selfheal.md)。

## 溯源

- 2026-09-26 2026-09-26-add-code-review-auto-fix — 新建本页：两路自动激活、批次编排循环、幂等与单飞、全量回归门与合回、回归契约缺失 fail-closed、失败重试与丢弃、回归执行锁根锚定主树。
- 2026-09-28 2026-09-28-add-code-fix-batch-failure-selfheal — 批收尾改三态（success/consumed/halt，consumed 自驱动）；失败路径由「保留现场待人工」改写为「现场即弃 + 锁即释 + 档案留痕」；零有效修复拒合回由链终止改为链内跳过；回归失败丢弃接入失败档案重试预算，废除「每次丢弃追加 todo 人工项」与「失败集合须人工 release」语义。
