## ADDED Requirements

### Requirement: 帮助文档反偏差断言口径

docs/help 各章中每一处「描述框架行为」的断言 MUST 与当前代码实现一致。本 SPEC 交付后，下列 P0 反偏差点 MUST 全部达成（逐点给出权威代码锚点，作为文档改写的核对基准）：

1. verdict blocked-env / inconclusive 流向（docs/help/05-verification.md）：blocked-env 描述 MUST 为「级一判据（judge 前全批 blocked-env）判 inconclusive；级二判据（judge 后断言归因全 env）在 judge 采纳前拦截不落 verified；豁免落 verified 须 admin DISPOSITION 放行（`inconclusive_loop` 信号）」，锚点 `core/pm_engine/verification/escalation.py:46,70,1316,1564`、`core/pm_engine/verification/pipeline.py:1009`；inconclusive 描述 MUST 为「自动回 implemented 重派新 attempt，最多 `verify_engine.inconclusive_max_attempts`（缺省 3）轮，第 4 轮写 inconclusive_loop SIGNAL 呼 admin 后停等人工」，锚点 `escalation.py:88-101,1410-1422`。
2. 验证流水线出题时机（05-verification.md 三步流水线段）：MUST 写明出题（planner-plan）已前置到 spec 进 ready 时与实现并行（并行出题标记 `parallel_plan.json`），非 implemented 之后串行，锚点 `core/pm_engine/engine.py:853,864,877`、`core/pm_engine/dispatch/queue.py:107`。
3. 冻结场景集变更通道（05-verification.md）：MUST 由「两条通道」改为三条——admin 裁决、人工删除、契约版本迁移自动通道（`contract_version`，v2=web 必含 navigate，旧集自动合成 navigate 或回落出题），锚点 `spec/archive/2026-09-24-evo-frozen-scenario-contract-versioning`。
4. 调度模型（06-governance.md 优先级与并发节）：MUST 删除「不同优先级之间不并行，低优先级必须等所有高优先级 SPEC 完成后才会启动」，改写为宽松优先级并行——「任务 X 可派发当且仅当没有比 X 更重要的活动任务；同档并行至 max_concurrent；不抢占；队列老化仅内存态」，锚点 `core/pm_engine/dispatch/queue.py:496-520,226-275`。
5. `agents.max_concurrent` 缺省值（06-governance.md 与 09-config.md）：MUST 为代码缺省 5（非 2），锚点 `core/pm_engine/dispatch/queue.py:562`。
6. autostash 回收冲突处置（07-safeguards.md）：MUST 删除「冲突时自动解决（UU → add）」，改写为三分诊——态 1 UU 文件 `git merge-file` 三方重试 → 态 2 逐文件 `checkout --theirs` + `commit --only` 只入库冲突路径留审计 → 态 3 兜底落工作区 + 登记 disposition；stash 条目一律保留记账，锚点 `core/worktree_manager/stash_guard.py:134-165,274-360`。
7. 状态机状态数（07-safeguards.md「十状态生命周期」、README.md 03 行「10 状态全景」）：MUST 统一为 11 状态（含 reviewing），锚点 `core/state_machine.py:26-37`。
8. impl 收尾代码审查形态（08-dashboard.md 质量页签段、09-config.md verify 段）：MUST 写明框架侧异步并行车道——merge-back 成功 + tester 派发时点由框架启动（不占 agent turn、实现者不等待、产物硬门已摘除）；`impl_code_review_concurrency` 缺省 MUST 为 4 且经车道命令注入硬生效（非「提示词命令示例承载的软约束」），锚点 `core/pm_engine/dispatch/queue.py:2648`、`core/config.py:2389,2459,2487`。
9. 架构图生成超时（08-dashboard.md 项目架构分面段）：MUST 由「1800 秒硬超时，超时整组击杀」改写为两段式——探索段 ≤720s、出图段 ≤1080s 分段击杀（总预算 1800s 不变），HEAD 指纹一致时重试跳过探索段，status 增 `stage` 键，锚点 `core/dashboard/routes/architecture_routes.py:45-49,195-262`。
10. code_review_fix 回归失败处置（09-config.md admin.code_review_fix 节）：MUST 删除「首次不通过在同一 worktree 内自动重试一次；仍不通过则丢弃该批、worktree 保留待人工、人工调 release_failed_batch 解除」，改写为——定向重试 ≤`admin.code_review_fix.targeted_retry_max`（缺省 3）轮、只重跑失败子集（映射失败 fail-closed 回全量）；耗尽后现场即弃（cleanup + 放锁）入失败档案；`FAIL_RETRY_MAX=3` 预算内新链自动重试，达上限才一次性告警 + todo 登记，锚点 `core/code_fix.py:2860-2945,690-722,79`、`core/config.py:1800-1806`。
11. code-fix 回归范围与兜底周期（09-config.md 同节）：「跑全量回归」MUST 改为「首轮全量、定向轮只重跑失败子集」；「30 分钟 full scan 周期兜底」MUST 标注为 `schedule.poll_interval_minutes`（缺省 30，非 code-fix 专属），锚点 `core/code_fix.py:2879-2889`、`core/event_bus.py:76-77`。
12. 规划性重启排水豁免（09-config.md admin.shutdown_drain_seconds 说明）：MUST 补充——`.fenix/restart_request` 在场的规划性重启豁免 `shutdown_drain_seconds=0` 的快速停机夹紧，仍按 `agents.run_drain_max_seconds`（缺省 60）排水；快速停机语义仅保留于非规划性关停，锚点 `core/config.py:1317-1342`。
13. agents.models 角色集（09-config.md agents.models 节）：MUST 为 11 角色（原 10 + code-fix），锚点 `core/config.py:131-151`。
14. Agent 类别数（02-concepts.md Agent Pool 图与表格）：MUST 为 12 类（原 11 + code-fix 行，含职责与触发时机），锚点 `core/config.py:144-150`、`core/code_fix.py`。
15. 审查产物形态（09-config.md admin.code_review 节）：「再由 agent 逐文件落 out-<run_id>.jsonl」MUST 改为分片直写——子代理各写 `out-<run_id>-b<N>.jsonl`，读侧一律聚合（主产物仅兜底），锚点 `core/code_review.py:56-129`。
16. hook 事件枚举（03-lifecycle.md 状态变化事件节、12-faq.md 第 11 条）：「十状态枚举」MUST 改为「11 状态枚举 + `all-done` 伪事件」，锚点 `core/hook_engine.py:79-80`。

#### Scenario: 反偏差点逐条可机检
- **WHEN** 对 docs/help 上述 9 份文档逐点执行文本核对（grep 断言旧表述已不存在、新表述关键值在场）
- **THEN** 16 个反偏差点全部命中新口径：grep 不到「不同优先级之间不并行」「UU → add」「1800 秒硬超时」「保留待人工」「release_failed_batch」「十个角色」「10 状态全景」「十状态」等旧表述；grep 到「缺省 5」「11 状态」「12 类」「720」「1080」「targeted_retry_max」「分片」「all-done」等新口径关键值

#### Scenario: 文档与代码权威锚点一致
- **WHEN** 抽查任一反偏差点的文档记载值与其代码锚点实际值比对（如 max_concurrent 缺省、inconclusive_max_attempts 缺省、探索/出图超时秒数、targeted_retry_max 缺省）
- **THEN** 文档数值与代码常量/缺省值逐一相等，无凭记忆书写的漂移
