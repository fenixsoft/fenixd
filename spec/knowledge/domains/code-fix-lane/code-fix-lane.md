# 自动修复车道编排

<!-- knowledge: capability=code-fix-lane rev=9
     sources=spec/archive/2026-09-26-add-code-review-auto-fix,spec/archive/2026-09-28-add-code-fix-batch-failure-selfheal,spec/archive/2026-10-03-add-codefix-targeted-retry,spec/archive/2026-10-03-add-codefix-commit-first-contract,spec/archive/2026-10-03-decouple-codefix-review-lanes,spec/archive/2026-10-04-add-codefix-affinity-batching,spec/archive/2026-10-09-evo-add-codefix-mergeback-conflict-salvage,spec/archive/2026-10-28-add-codefix-parse-error-breaker -->

把代码审查落账的 `open` 缺陷条目按批自动修复、经回归门后合回主树的编排车道，由 daemon 内的编排检查点驱动。

## 规则

### 激活
- 两路自动激活，MUST 汇入同一检查点入口（单一实现）：审查收尾路——`run_code_review` 成功收尾且本轮落账产生 `open` 条目时立即触发；周期兜底路——daemon full scan（默认 30 分钟周期）每轮触发一次，覆盖 daemon 重启、异常中断后的续做。
- 编排器未装配（测试/禁用态）时调用点静默跳过，不得抛穿调用方（评审车道异常不得影响审查 run 与 full scan 的既有判定）。
- 审查收尾零新 `open` 条目时不因该次审查激活。

### 守卫链与单飞
- 检查点按序守卫，任一命中即不投递：`admin.code_review_fix.enabled` 为 false → `disabled`；已有 code-fix run 在跑（编排器 `_in_flight` 标记，或 `_running_agents` 存在 `code-fix-` 前缀 run）→ `already_running`；无 `open` 条目 → `no_open_items`；回归契约不可用 → `regression_contract_missing`。
- 单飞标记投递时置位、批 worker 收尾时复位；两条激活路径并发到达由同一把锁保证至多一次投递。

### 与审查车道的调度解耦
- 批派发与链推进的判据集合不含「周期审查 run 在飞」：守卫链没有审查在飞否决或等待条件，审查 run 长时间在飞（含无产出停滞形态）期间车道照常建树、派批、推进，MUST NOT 出现因审查在飞导致的派批空窗。
- 与审查的真实资源冲突点只有回归主机级套件锁（见「回归门与合回」），由既有锁自然串行；逻辑调度层 MUST NOT 为审查在飞再加互斥或等待。
- 链自驱动推进对所有批收尾路径成立，含延迟批（defer）合回路径：批收尾 `wip_gate_blocked` 走延迟合回按 `consumed` 收尾照常推进下一批（语义见 [code-fix-wipgate-defer](code-fix-wipgate-defer.md)）；延迟台账合回成功核销后在同一检查点内联继续选批投递（与 `success` 收尾推进等价），MUST NOT 等待审查收尾事件或周期扫描才恢复。
- 审查 run 被停滞看门狗自动取消（见 [review-run-stall-watchdog](../code-review-lane/review-run-stall-watchdog.md)）时产物走急救落账、条目照常落 `open`，但取消收场 MUST NOT 激活修复链——激活仅由「成功收尾且本轮落账产生 `open` 条目」驱动（见「激活」）。

### 批次编排
- 选批按文件亲和性贪心装箱：以文件组为最小不可拆单元，`admin.code_review_fix.batch_size` 为目标规模 T、硬上限 2T（装箱规则详见 [codefix-affinity-batching](codefix-affinity-batching.md)）；排除集 = 失败档案条目并集 ∪ `chain_skipped`（跳过语义见 [code-fix-batch-selfheal](code-fix-batch-selfheal.md)）。
- 每批新建从当前 HEAD 起的独立 worktree（`worktree_manager.create(spec_name="code-review-fix", agent_type="code-fix")`），不复用上一批合回后的 worktree。
- `create()` 返回 `None`（同名锁占用 / git 建树失败）时中止本次激活：不派 run、不合回，进度 `phase=failed`、`reason=worktree_create_failed`，条目保持 `open` 待下一轮 full scan 重试。
- 批收尾为三态：`success`（合回并核销）/ `consumed`（该批条目已全部离开可选池）/ `halt`（环境性失败）；`success` 与 `consumed` 均自驱动推进下一批，仅 `halt` 终止链，完整路径映射与收敛保证见 [code-fix-batch-selfheal](code-fix-batch-selfheal.md)。
- 凡已建树的批（成功或失败）收尾 MUST 清理 worktree 并释放 `code-review-fix:code-fix` 进程内 spec 锁，MUST NOT 保留现场等待人工——`_spec_locks` 残留使后续 `create()` 恒返回 `None`，车道在首批之后即死；成功批调 `cleanup(wt_path, success=True)`。
- run_id 采用 `code-fix-<epoch>` 形式，不经 `_execute_agent`（不占 spec 维度预算、不计入每日 agent 计数）；定向重试轮 run_id 预生成并排除本批此前各轮（同秒撞名会复用 out 文件）。
- 批 worker 收尾后经 executor 再次投递检查点推进下一批（`success`/`consumed`），仅 `halt` 终止链、不投递，不得批内递归直调；台账无 `open` 条目时编排收尾（`running=false`），不空转派发。

### 回归门与合回
- 回归门范围按批位置分两段（分流规则详见 [codefix-affinity-batching](codefix-affinity-batching.md)）：链内非末批按批触碰面定向回归（配置关闭、cmd 无占位符或映射空集时回退全量），链末批恒全量兜底（末批在核销前按链选批同口径排除后判定）。在此基础上再分轮：某轮回归非 `passed` 时进入定向重试轮（见「回归失败定向重试与丢弃」），其回归范围为上一轮失败用例集，定向轮回归通过即视为该批回归门通过，MUST NOT 再强制补跑一次全量。
- 回归复用 `core.regression.run_regression` 执行原语与项目 `verify.yaml` 的 `regression` 段契约，在该批 worktree 内执行（执行根 = worktree，`project_root` 取 worktree 路径）。
- 回归与主树共用主机级套件锁：调用显式传 `lock_root=<主树根>`，锁文件为 `<主树根>/.fenix/full-suite.lock`；锁根锚定后回归命令工作目录仍为 worktree 根。`lock_root` 缺省回落 `project_root`；门面 `core/agent_runner/maintenance_runs.run_regression` 同步透传 `project_root` 与 `lock_root`，锁根与执行根语义对子集执行逐字不变。
- 定向子集执行由门面承载：`run_regression` 接受可选失败用例集参数（`subset_nodeids`），项目命令为 pytest 形态且子集非空时，以该子集 nodeids **取代命令中的既有收集位置参数**（首个收集目标位放全部 nodeids、其余收集目标删除，`-q`/`--junit-xml` 等非收集旗标逐字保留）。MUST NOT 在命令尾部追加 nodeid——pytest 多位置参数为收集目标并集，追加会静默退化全量。命令非 pytest 形态、子集为空、无既有收集目标、含 shell 控制操作符或命令替换记号时忽略子集回退全量（fail-closed）。
- 回归 `passed` 时经 `worktree_manager.merge_back(wt_path)` 合回，不得绕过既有 merge-back 闸门（merge-tree 预演 / WIP 重叠 / spec 目录在飞）。
- 合回后仅把该批中产物行 `status == "fixed"` 的条目按 `item_id` 精确置 `resolved`，不置未参与该批的条目，不置 agent 判 `skipped` 的条目；带 `fix_scope=test` 标注的产物行照常核销，标注仅供审计。
- 零有效修复拒合回：批内产物行无一条 `fixed`，或 worktree 分支相对建树点无任何提交**且 salvage 检测无可提交的未提交改动**（见「先 commit 再验证与收尾 salvage」）时，不合回、不置任何条目 `resolved`（防止全 `skipped` 的批被白洗成 `resolved`）；收尾清理 worktree，该批条目写入 `chain_skipped`，进度以非终态文案记原因 `no_effective_fix`，链继续推进下一批——零产物批按 `halt` 终止链会使最早队列头永久堵塞车道。
- worktree 内回归快照随执行根落盘于 worktree，不作为主树「测试回归」分面的数据源。

### 合回冲突定向救回
- 合回预演出真冲突时先救回再即弃：检出真冲突后、清理现场前执行一次定向救回——解析当前基线分支（`resolve_base_branch`）→ 批分支 rebase 到基线 → 重跑批回归（与既有批回归同执行根同锁语义）→ 通过则重走 merge_back；救回至多尝试 1 次，任一步失败不重试、降级走组粒度回收。
- rebase 仍冲突时组粒度回收：先 abort 还原批分支，从当前基线新建承载分支，以「提交是否触碰冲突文件集」逐组 cherry-pick 回收非冲突提交，回收集重跑批回归，通过后重走 merge_back 出账；二次回归仍不过则放弃回收、整批兜底入失败档案（与无救回时同口径）。
- 条目归属以提交 body 的 `items:` 清单解析为准（commit 契约的 body 结构化标注，仅新批生效）；旧契约提交解析不出清单时，无法归属到非冲突组的剩余未出账条目保守整体随兜底入失败档案，MUST NOT 做无据归属。仍冲突提交对应条目入失败档案计 fail_count，保持 open 走既有重试预算。
- 冲突文件集单源来自合回预演的 `MergeConflictInfo`（merge-tree 预演产出），不重造第二套冲突面判定。
- 救回时序与保真：救回发生在 `_safe_cleanup` 之前、单轮闭环，MUST NOT 依赖分支/worktree/tip_sha 跨轮存活（即弃后分支被删、worktree 被回收，tip_sha 仅 GC 前可用）；rebase/cherry-pick 改写批分支历史安全的前提是分支独立且尚未合回。
- 留痕：救回各阶段（rebase/二次回归/cherry-pick/终局）按成败记 INFO/WARNING 日志，终局单行汇总（整批救回/部分回收/兜底全弃）。
- defer 路径不触发救回：`wip_gate_blocked`（主树未提交 WIP 预检阻断）继续走 defer 零预算路径，不消耗救回次数与 fail_count 预算；救回重走合回若命中 `wip_gate_blocked`，同样按 defer 零预算处理，不计救回失败、不触发组粒度回收。

### 先 commit 再验证与收尾 salvage
- 提示词契约（`agents/code-fix.md` 契约段，软约束）：每修复一条立即 `git commit`（分支上 commit 廉价且可回退）；后台/定向验证 MUST NOT 作为 commit 的前置条件；回合结束前 worktree 工作区必须干净（全部改动已 commit）。机械保障由收尾 salvage 承担。
- 收尾 salvage 三元组检测：批收尾判定「分支相对建树点无提交」时，编排 MUST 先检测三元组——产物行存在 `status == "fixed"` ∧ 分支无提交 ∧ worktree 存在未提交改动（`git status --porcelain` 非空）。三元组同时满足 → 自动以 `orchestrator-salvage: batch <批号> run <run_id>` message 把未提交改动提交到批分支，随后按正常路径继续回归/合回裁决，MUST NOT 直接按 `no_effective_fix` 拒合回。
- salvage 留痕与保真：salvage 事件写进度 current 与 warning 日志双留痕；提交内容与工作区源码改动一致，gitignored 噪音（运行时产物等）不被卷入。
- 真零改动维持拒合回：三元组任一不满足（尤其产物声明 `fixed` 但工作区干净，即声明与事实不符）时 MUST 维持 `no_effective_fix` 拒合回语义，MUST NOT 空提交凑数（空提交会把声明与事实不符的批白洗成 `resolved`）。

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
- **回归异常熔断**：回归异常类失败——回归结局 `parse_error`（junit 产物缺失/不可解析），或回归 `failed` 但失败明细为空（无可注入的失败明细，含映射失败回退全量且明细 items 为空的形态）——在同批内**连续**达到熔断阈值（模块常量 `REGRESSION_ANOMALY_BREAKER_THRESHOLD`，缺省 2，不进配置、无 Dashboard 配置义务）时，重试循环 MUST 提前终止：不再派发下一轮定向 run 与全量回归，直接按现场即弃语义进入既有收口块（入档、worktree 清理、锁释放、告警与轮数耗尽路径零分叉复用）。
- 熔断计数为批 worker 局部状态，同批内连续累计、跨批跨链不累计；真实测试失败（`failed` 且明细非空）MUST NOT 进熔断计数且将计数清零（偶发环境抖动后恢复正常不应累积误杀），回归 `passed` 天然离开循环。既有 `targeted_retry_max` 轮数上限行为在熔断未触发时逐位不变。
- 熔断收口与轮数耗尽共用同一收口点：`branch`/`tip_sha`/`reason`/`failed_at`/最后一轮失败明细引用先入档再清理（语义见下条），批收口 `reason` 按收口形态分流——熔断为 `regression_parse_error_breaker`、轮数耗尽保持 `regression_failed_twice`；收口告警 MUST 复用 `write_regression_failed_alert` 单一调用点（告警名 `regression_failed_twice` 历史兼容名不变），`retry_rounds` 按实际执行轮数如实传入，同批 MUST NOT 重复告警。熔断触发 MUST 记 WARNING 日志并包含触发判据（各轮回归 status 与明细形态），供事后区分「测试失败耗尽」与「回归没跑出结果被熔断」。
- 重试 run 本身失败（run 层面，非回归失败）不入失败档案、不烧跨轮预算：条目入 `chain_skipped`，清理 worktree 并释放 spec 锁，链继续（与首轮 run 失败同语义）。
- 耗尽 `targeted_retry_max` 轮仍未 `passed` 时现场即弃：MUST NOT 合回、MUST NOT 置 `resolved`，条目保持 `open`；清理前把 `branch`、`tip_sha`、`reason`、`failed_at` 与最后一轮失败明细引用写入失败档案记录，随后清理 worktree 并释放 spec 锁（`branch`/`tip_sha` 留作 git reflog 追溯线索，不承担恢复职责）；warning 告警含条目集与失败用例摘要，措辞为「已跳过，下轮自动重试」，不得表述为「待人工处置」。
- 失败档案条目后续检查点跳过（同链内不重复派发同一批）；新链启动按 `fail_count` 预算自动释放（`fail_count < FAIL_RETRY_MAX`），预算内条目不要求人工解除即可重试，重组批从首轮全量回归起重走门与定向轮语义。
- 达预算上限（`fail_count ≥ FAIL_RETRY_MAX`）的条目集永久跳过；预算用尽那次入档发一次性 warning 点名录告警，并在 `.fenix/todo.md` 追加待人工清理项（指引按 `branch`/`tip_sha` 追溯，不得引用已清理的 worktree 路径）。重试预算语义见 [code-fix-batch-selfheal](code-fix-batch-selfheal.md)。

## 溯源

- 2026-09-26 2026-09-26-add-code-review-auto-fix（spec/archive/2026-09-26-add-code-review-auto-fix） — 新建本页：两路自动激活、批次编排循环、幂等与单飞、全量回归门与合回、回归契约缺失 fail-closed、失败重试与丢弃、回归执行锁根锚定主树。
- 2026-09-28 2026-09-28-add-code-fix-batch-failure-selfheal（spec/archive/2026-09-28-add-code-fix-batch-failure-selfheal） — 批收尾改三态（success/consumed/halt，consumed 自驱动）；失败路径由「保留现场待人工」改写为「现场即弃 + 锁即释 + 档案留痕」；零有效修复拒合回由链终止改为链内跳过；回归失败丢弃接入失败档案重试预算，废除「每次丢弃追加 todo 人工项」与「失败集合须人工 release」语义。
- 2026-10-03 2026-10-03-add-codefix-targeted-retry（spec/archive/2026-10-03-add-codefix-targeted-retry） — 回归门通过语义分轮（首轮全量、定向轮失败子集且通过即门通过）；回归失败重试由「整批 items 重做 + 全量回归重跑」改写为定向重试轮：上限 targeted_retry_max（缺省 3）、失败明细结构化落盘（classname 主导 nodeid 映射、映射失败回退全量）、轮间累计注入、修测试授权（fix_scope=test 标注）、门面 subset_nodeids 子集执行（取代收集位置参数）、耗尽现场即弃沿用并追加明细引用入档。
- 2026-10-03 2026-10-03-add-codefix-commit-first-contract（spec/archive/2026-10-03-add-codefix-commit-first-contract） — 零有效修复拒合回新增 salvage 前置分支：批收尾「分支无提交」判定先过 salvage 三元组检测（fixed 行 ∧ 无提交 ∧ porcelain 非空），命中即 `orchestrator-salvage:` 自动提交后继续回归/合回裁决，真零改动维持拒合回、禁空提交；新增 `agents/code-fix.md`「先 commit 再验证」软契约（逐条即 commit、验证不阻塞 commit、收尾工作区干净），机械保障由 salvage 承担。
- 2026-10-03 2026-10-03-decouple-codefix-review-lanes（spec/archive/2026-10-03-decouple-codefix-review-lanes） — 新增「与审查车道的调度解耦」：守卫链无审查在飞条件、物理冲突只剩回归主机级套件锁自然串行；延迟批合回自驱动推进语义固化（defer 按 consumed 收尾照常推进、延迟台账合回核销同检查点继续选批）；同归档另建审查 run 停滞看门狗能力页（code-review-lane/review-run-stall-watchdog），其取消收场急救落账不激活修复链。
- 2026-10-04 2026-10-04-add-codefix-affinity-batching（spec/archive/2026-10-04-add-codefix-affinity-batching） — 选批由「最早优先截前 batch_size 条」改写为文件亲和性贪心装箱（batch_size 放宽为目标规模 T、硬上限 2T）；回归门范围由「首轮恒全量」改写为两段式（非末批定向、末批恒全量兜底），定向失败与全量失败同走既有定向重试轮；算法与分流细则独立成页 codefix-affinity-batching。
- 2026-10-09 evo-add-codefix-mergeback-conflict-salvage（spec/archive/2026-10-09-evo-add-codefix-mergeback-conflict-salvage） — 新增「合回冲突定向救回」：真冲突整批即弃前先 rebase 基线+重跑批回归救回（至多 1 次）、失败降级组粒度 cherry-pick 回收（items: 清单归属、无据保守兜底入档）、救回挂 cleanup 前单轮闭环；defer 路径零预算语义不变。
- 2026-10-28 2026-10-28-add-codefix-parse-error-breaker（spec/archive/2026-10-28-add-codefix-parse-error-breaker） — 「回归失败定向重试与丢弃」新增回归异常熔断：parse_error/空明细类失败同批连续达阈值（缺省 2）即提前终止重试循环，收口 reason 新增 `regression_parse_error_breaker`，入档/清理/告警零分叉复用轮数耗尽收口点，真实测试失败不进计数且清零。
