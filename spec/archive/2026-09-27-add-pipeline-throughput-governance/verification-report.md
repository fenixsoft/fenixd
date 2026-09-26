# 验证报告：add-pipeline-throughput-governance

> ⚠️ 本报告由框架于 2026-09-22T15:51:15Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。
> 报告时效标记（判定本报告是否属上一轮）：合成源轮次指纹：report.json@2026-09-22T15:51:15.150453+00:00

## 结论：✅ 通过（verified）

**状态：verified — 30/30 场景通过，0 失败，0 错误（全部场景通过）**

全绿快道: 30/30 场景通过、0 失败 0 警告——无分类对象，跳过 judge 机械 verified

| 指标 | 数量 |
| --- | --- |
| 通过 | 30 |
| 失败 | 0 |
| 错误 | 0 |
| 产品 Bug | 0 |
| 本链增量 Token（输入） | 1.59M |
| 本链增量 Token（输出） | 0.03M |


## 场景结果

| 场景 | 描述 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- | --- |
| concurrency-default-5-without-explicit-config | 并发缺省值上调：无显式配置时代码缺省 5 生效（core/pm_engine/dispatch/queue.py:409 _get_config("agents.max_concurrent", 5)；tasks 1.1/1.3） | pass | 0/3 | - |
| concurrency-explicit-config-priority | 可回退性：显式配置任意值（如 3）优先于代码缺省 5 生效，配置回退不改代码缺省优先级（queue.py:406-409 注释与实现；tasks 1.1/1.3） | pass | 0/3 | - |
| concurrency-template-recommends-five-resource-notes | 模板推荐值同步上调：.fenix/config.template.yaml 推荐 max_concurrent: 5 并附资源前提注释（worktree 磁盘/网关并发/回归锁串行化）（.fenix/config.template.yaml:43-52；tasks 1.1） | pass | 0/5 | - |
| concurrency-full-suite-lock-mutex-unchanged | 回归互斥回归点：多 run 同时到达收尾回归检查点时 full-suite.lock 主机级互斥串行、600s 等待上限与超时 skip 语义不变（tests/test_pipeline_throughput_governance.py::TestDispatchConcurrencyTuning；tasks 1.3） | pass | 0/3 | - |
| concurrency-ops-doc-registered | 运维文档交付：docs/help/14-pipeline-throughput-ops.md 存在且含并发人工调整与回退步骤，docs/help/README.md 目录表登记 #14 一行（docs/help/README.md:25；tasks 1.2） | pass | 0/6 | - |
| merge-precheck-overlap-blocks-escalates | WIP 重叠拦截升级：主树 WIP 与分支触碰文件集交集非空时不发起 merge、发含交集清单的人工升级告警、spec 保持可重试、分支与产物完好（core/worktree_manager/mergeback.py 复用 _wip_overlap_gate/_detect_wip_overlap；tasks 2.2/2.4） | pass | 0/4 | - |
| merge-precheck-no-overlap-direct-merge | 无交集直通：主树 WIP 与分支触碰文件集无交集（或主树干净）时 merge-back 按既有路径正常执行，预检零额外拦截（core/worktree_manager/mergeback.py；tasks 2.2/2.4） | pass | 0/3 | - |
| merge-precheck-bypass-escape-hatch | 逃生门：worktree.merge_precheck_bypass=true 时跳过预检直接发起 merge，冲突走既有失败路径（mergeback.py:160-169、260-266；tasks 2.3/2.4） | pass | 0/3 | - |
| merge-precheck-policy-compat-block-auto | 策略读侧兼容：显式 block 并入升级出口（拦截语义与缺省 escalate 一致），显式 auto 保留旧 stash 收纳语义不变（core/worktree_manager/mergeback.py _wip_gate_policy；tasks 2.2） | pass | 0/4 | - |
| restart-drain-default-and-enlarged-window | 排水窗口配置化：缺省 60s（非 1800s 级空等）、显式调大（如 600s）生效且显式配置优先（core/config.py:1120 get_run_drain_max_seconds；tasks 3.1/3.3） | pass | 0/4 | - |
| restart-drain-validation-rejects-over-shutdown | 配置一致性校验异常路径：两者均显式且 run_drain_max_seconds > shutdown_drain_seconds 时校验拒绝（ValueError），保证 supervisor（SIGKILL 等待=shutdown+120s）不先于排水窗口强杀（core/config.py:416-442；tasks 3.1） | pass | 0/3 | - |
| restart-drain-clamped-by-shutdown-drain | 读取门面夹紧兜底：旁路脏配置（未过校验）时生效值按 min(raw, shutdown 生效值) 夹紧，缺省 60 遇较小显式 shutdown 不变地雷、shutdown=0 联动为 0（core/config.py:1120-1150；tasks 3.1） | pass | 0/3 | - |
| restart-drain-restart-flow-uses-config | restart 链路真实读取：daemon restart 排水等待取 agents.run_drain_max_seconds 而非 admin.shutdown_drain_seconds，常规停机语义不受影响（core/agent_runner/runner.py；tasks 3.1/3.3） | pass | 0/3 | - |
| restart-drain-broadcast-checkpoint-zero-side-effect | checkpoint 广播：restart 停新派发后向在飞 run 写控制文件信号即返回（不阻塞排水、无新增失败终态）；不识别信号的 run 被超窗强杀时处理与未广播一致、零副作用（core/signals.py + core/agent_runner/runner.py；tasks 3.2/3.3） | pass | 0/4 | - |
| restart-drain-in-window-finish-normal-merge | 窗口内收尾正常判定：短排水窗口下窗口内自行收尾的 run 正常完成并按正常路径合并判定，不被强杀（core/agent_runner/runner.py 排水等待；tasks 3.3） | pass | 0/3 | - |
| fastlane-three-conditions-eligible | 三条件全满足走 fastlane：失败场景数=1 + judge 归因影响面≤3 文件 + 无 dispute/adjudication 标记 → 生成 code-fix 轻量任务而非派生 fix SPEC（core/pm_engine/verification/fastlane.py evaluate_fastlane；tasks 4.1/4.3） | pass | 0/3 | - |
| fastlane-multi-failure-falls-back | 多场景失败回落整轮：验证轮 3 个场景失败时走既有 bug-found→fix SPEC 整轮路径，行为与引入前一致（core/pm_engine/verification/pipeline.py:905-922；tasks 4.1/4.3） | pass | 0/3 | - |
| fastlane-dispute-and-missing-attribution-fallback | 条件二/三不满足回落：findings 含 dispute/adjudication 条目时回落整轮；judge 影响面归因缺失时保守回落（不误入 fastlane）（core/pm_engine/verification/fastlane.py disputed_findings/judge_affected_files；tasks 4.1/4.3） | pass | 0/4 | - |
| fastlane-decision-record-traceable | 判定记录可追溯：fastlane 判定过程与所选路径落在判定产物（fastlane_decision.json）与日志中，可审计为何走/不走 fastlane（core/pm_engine/verification/fastlane.py record_decision/fastlane_decision_path；tasks 4.1/4.3） | pass | 0/3 | - |
| fastlane-subset-reverify-converges | 子集重验通过即收敛：修复后仅以子集场景集执行、不派生 fix SPEC，验证轮按通过收敛且子集重验独立可用（core/pm_engine/verification/fastlane.py subset_reverify；tasks 4.2/4.3） | pass | 0/3 | - |
| fastlane-subset-ids-chain-downstream | 子集构造含依赖链：子集 = 失败场景 ∪ depends_on 前置链（递归）∪ 以失败场景为前置的下游场景（递归，防修复波及依赖方漏验）（core/pm_engine/verification/fastlane.py subset_scenario_ids；tasks 4.2/4.3） | pass | 0/3 | - |
| fastlane-report-carries-over-passes | 重验报告全量判定：merge_subset_report 合并后报告含全部场景判定，未实跑场景沿用上一轮通过结论并标注来源（core/pm_engine/verification/fastlane.py merge_subset_report；tasks 4.2/4.3） | pass | 0/3 | - |
| fastlane-consecutive-two-failures-force-full-round | 连续两次失败强制回落：同一验证轮第 2 次 fastlane 修复后子集重验仍失败 → 不再第 3 次 fastlane、转整轮 fix SPEC，修复轮次计入验证轮预算（core/pm_engine/verification/fastlane.py 失败连击计数；tasks 4.2/4.3） | pass | 0/4 | - |
| rejection-format-substantive-classified | 打回结果带分类：格式打回（缺契约段等）写 rejection_class=format、实质打回（场景覆盖缺失等）写 substantive，打回理由正文照旧（core/pm_engine/spec_review.py:491-505；tasks 5.1/5.3） | pass | 0/3 | - |
| rejection-pass-result-no-field-legal | 通过结果不要求字段：reviewing→ready 的通过结果无 rejection_class 字段（或 null）合法，不被判非法（core/pm_engine/spec_review.py；tasks 5.1/5.3） | pass | 0/3 | - |
| rejection-legacy-missing-field-unknown-compat | 存量兼容异常路径：无 rejection_class 字段的历史结果与非法值均按 unknown 兼容（normalize_rejection_class），解析不失败、存量零迁移（core/pm_engine/spec_review.py:76-85；tasks 5.2/5.3） | pass | 0/3 | - |
| rejection-stats-buckets-fail-open | 统计分桶正确且 fail-open：rejection_class_stats 按 format/substantive/unknown 三桶计数，目录缺失返回空、损坏文件跳过不抛异常（core/pm_engine/spec_review.py:88-109；tasks 5.2/5.3） | pass | 0/3 | - |
| rejection-stats-live-query-introspection | 读侧统计真实驱动（端到端内省）：构造临时项目树的 .fenix/spec-review/*/.fenix-run-result.json（format/substantive/缺字段/非法值四份 + 空目录态），直调 rejection_class_stats 验证分桶计数与空值 fail-open（core/pm_engine/spec_review.py:88；tasks 5.2） | pass | 0/4 | - |
| rejection-prompt-injects-class-boundary | 评审 prompt 注入边界定义：评审 prompt 注入段逐条下发 format/substantive 判定边界（格式类=可机械修复、实质类=方案/覆盖/正确性）（core/pm_engine/spec_review.py 评审 prompt 组装；tasks 5.1/5.3） | pass | 0/3 | - |
| pipeline-throughput-full-suite-green | 全量回归哨：tests/test_pipeline_throughput_governance.py 33 个用例全部通过（并发/预检/排水/fastlane/rejection 五能力契约整体绿，实测 33 passed） | pass | 0/2 | - |

## 本轮场景集变更

场景集与持久化集一致，无变更。

