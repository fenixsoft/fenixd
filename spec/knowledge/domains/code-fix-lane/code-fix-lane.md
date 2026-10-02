# 自动修复车道编排

<!-- knowledge: capability=code-fix-lane rev=3
     sources=spec/archive/2026-09-26-add-code-review-auto-fix,spec/archive/2026-09-28-add-code-fix-batch-failure-selfheal,spec/archive/2026-10-03-add-codefix-targeted-retry -->

把代码审查落账的 `open` 缺陷条目按批自动修复、经回归门后合回主树的编排车道，由 daemon 内的编排检查点驱动。

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
- run_id 采用 `code-fix-<epoch>` 形式，不经 `_execute_agent`（不占 spec 维度预算、不计入每日 agent 计数）；定向重试轮 run_id 预生成并排除本批此前各轮（同秒撞名会复用 out 文件）。
- 批 worker 收尾后经 executor 再次投递检查点推进下一批（`success`/`consumed`），仅 `halt` 终止链、不投递，不得批内递归直调；台账无 `open` 条目时编排收尾（`running=false`），不空转派发。

### 回归门与合回
- 回归门范围分轮：首轮为全量回归；定向重试轮（见「回归失败定向重试与丢弃」）的回归范围为上一轮失败用例集，定向轮回归通过即视为该批回归门通过，MUST NOT 再强制补跑一次全量。
- 回归复用 `core.regression.run_regression` 执行原语与项目 `verify.yaml` 的 `regression` 段契约，在该批 worktree 内执行（执行根 = worktree，`project_root` 取 worktree 路径）。
- 回归与主树共用主机级套件锁：调用显式传 `lock_root=<主树根>`，锁文件为 `<主树根>/.fenix/full-suite.lock`；锁根锚定后回归命令工作目录仍为 worktree 根。`lock_root` 缺省回落 `project_root`；门面 `core/agent_runner/maintenance_runs.run_regression` 同步透传 `project_root` 与 `lock_root`，锁根与执行根语义对子集执行逐字不变。
- 定向子集执行由门面承载：`run_regression` 接受可选失败用例集参数（`subset_nodeids`），项目命令为 pytest 形态且子集非空时，以该子集 nodeids **取代命令中的既有收集位置参数**（首个收集目标位放全部 nodeids、其余收集目标删除，`-q`/`--junit-xml` 等非收集旗标逐字保留）。MUST NOT 在命令尾部追加 nodeid——pytest 多位置参数为收集目标并集，追加会静默退化全量。命令非 pytest 形态、子集为空、无既有收集目标、含 shell 控制操作符或命令替换记号时忽略子集回退全量（fail-closed）。
- 回归 `passed` 时经 `worktree_manager.merge_back(wt_path)` 合回，不得绕过既有 merge-back 闸门（merge-tree 预演 / WIP 重叠 / spec 目录在飞）。
- 合回后仅把该批中产物行 `status == "fixed"` 的条目按 `item_id` 精确置 `resolved`，不置未参与该批的条目，不置 agent 判 `skipped` 的条目；带 `fix_scope=test` 标注的产物行照常核销，标注仅供审计。
- 零有效修复拒合回：批内产物行无一条 `fixed`，或 worktree 分支相对建树点无任何提交时，不合回、不置任何条目 `resolved`（防止全 `skipped` 的批被白洗成 `resolved`）；收尾清理 worktree，该批条目写入 `chain_skipped`，进度以非终态文案记原因 `no_effective_fix`，链继续推进下一批——零产物批按 `halt` 终止链会使最早队列头永久堵塞车道。
- worktree 内回归快照随执行根落盘于 worktree，不作为主树「测试回归」分面的数据源。

### 回归契约缺失 fail-closed
- 项目 `verify.yaml` 无有效 `regression` 段时不派批、不合回，按契约状态分流写信号（经 AdminStore，severity=major）：契约整体缺失（`contract is None`）→ `verify_contract_missing`（administrator 起草完整契约）；契约有效但缺 regression 段 → `verify_regression_missing`（administrator 仅补段，不得动 prepare/serve/ready）。
- 两种缺失下进度均记 `phase=blocked`，`reason` 分别为 `regression_contract_missing` / `regression_section_missing`。
- 起草完成后的下一轮 full scan 自动进入批次处理，不需人工再激活；不得回退框架专用脚本（如 `bin/run_full_suite.py`）作为通用项目的回归命令。

### 回归失败定向重试与丢弃
- 首轮全量回归非 `passed` 时进入定向重试轮，上限 `admin.code_review_fix.targeted_retry_max`（缺省 3）：每轮在**同一 worktree** 内派一次 code-fix run，prompt MUST 注入上一轮失败用例的结构化明细（nodeid + 失败摘要），并硬性指令只修与失败用例相关的问题、MUST NOT 扩面重做全批；修复对象由 agent 依据用例信息判定，可以是产品代码缺陷，也可以是测试本身缺陷（断言过时、替身失真、超时替身自旋类）。进度 phase 为 `retrying`，轮次号入文案。
- 修复对象是测试本身时，该条目产物行 `status` 照常写 `fixed` 并 MUST 额外带 `fix_scope=test` 字段标注；编排读取透传保留该标注，供审计区分修产品与修测试。
- 失败用例明细每轮结构化落盘 `.fenix/code-review/fix-reg-failures-<回归 run_id>.json`：首轮与每个定向轮回归非 `passed` 时各落一份、文件名含该轮回归 run_id，结构含 `items`（nodeid + 失败摘要）、`source_run_id`、`created_at`、`fallback_full`；供重试注入与事后审计。历史明细按 mtime 只保留最近 20 份，全链路只写不清。
- nodeid 映射以 junit `classname` 主导重构：点分模块路径转文件路径（`tests.test_x` → `tests/test_x.py`）、余下段作 `::` 类链、末接 `::name`；`file` 属性仅当存在时参与一致性校验。pytest junitxml 不产 `file` 属性属预期形态，MUST NOT 因此判映射失败。映射失败（classname 缺失或非 Python 模块形态、同一重构结果歧义、不足以唯一重构 nodeid）时回退为全量重试并留日志（fail-closed），落盘 `fallback_full=true`。
- 轮间注入累计失败明细：按 nodeid 去重合并（此前修过但再次失败的用例仍在集内），后轮摘要覆盖前轮；映射失败时回退注入纯文本失败摘要。定向轮回归范围为**本轮失败集**（非累计集），上一轮已通过的用例不重跑。
- 定向轮回归 `passed` 时 MUST 按正常路径合回并核销该批条目，MUST NOT 再补跑全量回归（子集回归的实际执行用例数等于该轮失败集大小）。
- 重试 run 本身失败（run 层面，非回归失败）不入失败档案、不烧跨轮预算：条目入 `chain_skipped`，清理 worktree 并释放 spec 锁，链继续（与首轮 run 失败同语义）。
- 耗尽 `targeted_retry_max` 轮仍未 `passed` 时现场即弃：MUST NOT 合回、MUST NOT 置 `resolved`，条目保持 `open`；清理前把 `branch`、`tip_sha`、`reason`、`failed_at` 与最后一轮失败明细引用写入失败档案记录，随后清理 worktree 并释放 spec 锁（`branch`/`tip_sha` 留作 git reflog 追溯线索，不承担恢复职责）；warning 告警含条目集与失败用例摘要，措辞为「已跳过，下轮自动重试」，不得表述为「待人工处置」。
- 失败档案条目后续检查点跳过（同链内不重复派发同一批）；新链启动按 `fail_count` 预算自动释放（`fail_count < FAIL_RETRY_MAX`），预算内条目不要求人工解除即可重试，重组批从首轮全量回归起重走门与定向轮语义。
- 达预算上限（`fail_count ≥ FAIL_RETRY_MAX`）的条目集永久跳过；预算用尽那次入档发一次性 warning 点名录告警，并在 `.fenix/todo.md` 追加待人工清理项（指引按 `branch`/`tip_sha` 追溯，不得引用已清理的 worktree 路径）。重试预算语义见 [code-fix-batch-selfheal](code-fix-batch-selfheal.md)。

## 溯源

- 2026-09-26 2026-09-26-add-code-review-auto-fix（spec/archive/2026-09-26-add-code-review-auto-fix） — 新建本页：两路自动激活、批次编排循环、幂等与单飞、全量回归门与合回、回归契约缺失 fail-closed、失败重试与丢弃、回归执行锁根锚定主树。
- 2026-09-28 2026-09-28-add-code-fix-batch-failure-selfheal（spec/archive/2026-09-28-add-code-fix-batch-failure-selfheal） — 批收尾改三态（success/consumed/halt，consumed 自驱动）；失败路径由「保留现场待人工」改写为「现场即弃 + 锁即释 + 档案留痕」；零有效修复拒合回由链终止改为链内跳过；回归失败丢弃接入失败档案重试预算，废除「每次丢弃追加 todo 人工项」与「失败集合须人工 release」语义。
- 2026-10-03 2026-10-03-add-codefix-targeted-retry（spec/archive/2026-10-03-add-codefix-targeted-retry） — 回归门通过语义分轮（首轮全量、定向轮失败子集且通过即门通过）；回归失败重试由「整批 items 重做 + 全量回归重跑」改写为定向重试轮：上限 targeted_retry_max（缺省 3）、失败明细结构化落盘（classname 主导 nodeid 映射、映射失败回退全量）、轮间累计注入、修测试授权（fix_scope=test 标注）、门面 subset_nodeids 子集执行（取代收集位置参数）、耗尽现场即弃沿用并追加明细引用入档。
