# 验证报告：add-verify-lane-throughput

> ⚠️ 本报告由框架于 2026-09-22T16:06:48Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。
> 报告时效标记（判定本报告是否属上一轮）：合成源轮次指纹：report.json@2026-09-22T16:06:48.456492+00:00

## 结论：✅ 通过（verified）

**状态：verified — 23/23 场景通过，0 失败，0 错误（全部场景通过）**

全绿快道: 23/23 场景通过、0 失败 0 警告——无分类对象，跳过 judge 机械 verified

| 指标 | 数量 |
| --- | --- |
| 通过 | 23 |
| 失败 | 0 |
| 错误 | 0 |
| 产品 Bug | 0 |
| 本链增量 Token（输入） | 2.63M |
| 本链增量 Token（输出） | 0.05M |


## 场景结果

| 场景 | 描述 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- | --- |
| ready-triggers-parallel-plan-dispatch | 出题并行派发正向路径——spec 进入 ready 态即注册并派发 planner-plan 并行出题条目：无既有场景集才触发、已有场景集/标记已消费或在飞/车道已激活均跳过、触发异常被吞噬且不影响实现车道（出处 core/pm_engine/engine.py:913，tests/test_verify_lane_throughput.py:79） | pass | 0/6 | - |
| parallel-plan-config-off-legacy-behavior | 并行出题配置开关异常路径——verify.parallel_planning 关闭或快速通道模式时不派发并行出题，testing 行为与未引入本能力前一致（出处 core/pm_engine/engine.py:931，tests/test_verify_lane_throughput.py:92） | pass | 0/3 | - |
| parallel-plan-regression-stops-inflight | 状态回退治理——spec 打回 drafted 或删除时在飞并行出题收尾不采信半成品；停止接口摘除在队条目并取消在飞 run；冻结标记不重触发但可重试状态可重触发（出处 core/pm_engine/engine.py:1035，core/pm_engine/engine.py:451，tests/test_verify_lane_throughput.py:167） | pass | 0/5 | - |
| parallel-plan-lane-terminal-markers | 并行出题车道收尾标记——成功写 completed 标记供 testing 短路消费，失败隔离产物走既有串行出题通道（出处 core/pm_engine/engine.py:960，tests/test_verify_lane_throughput.py:135） | pass | 0/3 | - |
| testing-ready-shortcircuit-zero-replan | testing 进入就绪短路——completed 并行产物经既有校验即消费、阶段 1 零重复出题直接进场景执行；无标记时行为与现状一致；状态已迁移时不再消费（出处 core/pm_engine/verification/pipeline.py:2143，core/pm_engine/verification/pipeline.py:1986，tests/test_verify_lane_throughput.py:334） | pass | 0/4 | - |
| testing-corrupt-dead-product-falls-back-serial | 并行产物异常回落串行——产物 JSON 损坏或失败标记时隔离坏产物并串行重出；在飞 run 已死时按有界超时取消转串行，任意时刻至多一个出题 run 可写 test_scenarios.json 不双写（出处 core/pm_engine/verification/pipeline.py:1981，tests/test_verify_lane_throughput.py:348） | pass | 0/4 | - |
| parallel-plan-entry-held-stateless-queue | 并行出题条目队列语义异常路径——spec 已回退 drafted 时条目持有不派发；planner-plan 派发不迁移 spec 状态机；worker 释放即清理在飞登记（出处 core/pm_engine/dispatch/queue.py:445，tests/test_verify_lane_throughput.py:295） | pass | 0/4 | - |
| slot-exemption-dispatch-when-impl-slots-full | 槽位豁免正向路径——实现类 run 占满 max_concurrent 全部槽位时并行 planner-plan 条目仍立即派发不滞留队列，在飞期间不计入实现槽位计数（出处 core/pm_engine/dispatch/queue.py:92，tests/test_verify_lane_throughput.py:249） | pass | 0/2 | - |
| slot-exemption-cap-one-queues-second | 豁免上限内排队——已有 1 个并行 planner-plan 在飞时第二个出题条目按既有队列语义等待，实现槽位空闲也不放行（出处 core/pm_engine/dispatch/queue.py:96，tests/test_verify_lane_throughput.py:263） | pass | 0/2 | - |
| slot-exemption-cap-uncoupled-from-max-concurrent | 豁免上限与实现并发解耦——agents.max_concurrent 调大不放大并行 planner-plan 在飞上限（恒为常量 1）（出处 core/pm_engine/dispatch/queue.py:96，tests/test_verify_lane_throughput.py:275） | pass | 0/2 | - |
| judge-round-third-dispatch-stopped-escalation | judge 重裁决停派升级——同 spec 同验证轮真实派发计数达 2 后第 3 次派发被阻止，转人工升级告警且每轮只发一次、spec 保持可重试状态（出处 core/pm_engine/verification/judge_gate.py:255，core/pm_engine/verification/judge_gate.py:210，tests/test_verify_lane_throughput.py:406） | pass | 0/3 | - |
| judge-round-counters-reset-on-new-verify-round | 轮内计数随验证轮重置——bug-found 修复进入新验证轮或重验执行后 judge 真实派发计数从 0 重计、首轮派发正常执行（出处 core/pm_engine/verification/judge_gate.py:116，tests/test_verify_lane_throughput.py:429） | pass | 0/3 | - |
| judge-low-confidence-expansion-not-counted-as-dispatch | 低置信治理——可补类型（缺 evidence/截断）优先证据扩充且每轮至多 1 次、扩充不计真实派发；不可补类型按重裁决计次；fast-track 复用命中不计真实派发（出处 core/pm_engine/verification/judge_gate.py:163，core/verdict_check.py:1444，tests/test_verify_lane_throughput.py:486） | pass | 0/5 | - |
| judge-summary-fasttrack-fields-fail-open | fast-track 命中率可观测——读侧 summary 暴露 judge_fasttrack_hits/judge_real_dispatches 统计字段，历史 spec 无记录时空值 fail-open 不抛异常（出处 core/dashboard/data/summary.py:415，tests/test_verify_lane_throughput.py:519） | pass | 0/2 | - |
| verdict-cache-definition-fingerprint-whitelist | 缓存键指纹口径——场景定义指纹按白名单键投影、易变键不参与、定义变化改指纹、非 dict 载荷返回空串；被测构建指纹对依赖清单文件集稳定且敏感；验证配置指纹随 verify.yaml 内容变化（出处 core/verdict_check.py:1338，core/verdict_check.py:1371，core/verdict_check.py:1397，tests/test_verify_lane_throughput.py:538） | pass | 0/6 | - |
| verdict-cache-quad-e2e-probe | 缓存四元组端到端直驱探针——四元组全等才采信、任一分量变化或缺失即失效、空指纹 fail-closed 照跑、出处标注提取、PASS 条目落盘回读含四元组分量与 _meta 注入、损坏缓存 fail-open 返回空、可补类型判别器（出处 core/verdict_check.py:1444，core/verdict_check.py:1261，core/verdict_check.py:1249，core/verdict_check.py:1425） | pass | 0/3 | - |
| verdict-cache-pass-entries-persisted-quad | 缓存写侧扩展——judge 判定采纳后 PASS 条目与四元组分量（被测构建/验证配置指纹）一并持久化；_meta 特殊键写侧注入、读侧按 scenario_id 取条目不误命中（出处 core/verdict_check.py:1261，tests/test_verify_lane_throughput.py:613，tests/test_verify_lane_throughput.py:636） | pass | 0/3 | - |
| reverify-prune-failed-union-source-touched-closure | 修复轮重验裁剪——实际执行集=本轮失败场景 ∪ 修复 diff 触碰出处关联文件的场景 ∪ depends_on 前置依赖链（递归）；缓存有效的通过场景采信缓存不重复执行（出处 core/pm_engine/verification/pipeline.py:1386，tests/test_verify_lane_throughput.py:743） | pass | 0/4 | - |
| reverify-fail-closed-missing-annotation-unavailable-diff | 存疑 fail-closed 照跑——场景 description 无出处标注或本轮修复 diff 不可得时不采信缓存、场景照常执行，系统不报错不中断验证轮（出处 core/verdict_check.py:1425，tests/test_verify_lane_throughput.py:761） | pass | 0/3 | - |
| reverify-first-round-full-and-report-merge | 首轮全量与报告合成——首轮验证与冻结复用轮不受裁剪影响全量执行；裁剪轮报告合成覆盖写且含全部场景判定（实跑+缓存来源）、blocked 环境计数入 warnings；裁剪后零执行集信任全部缓存并跳过场景引擎直接出报告（出处 core/pm_engine/verification/pipeline.py:1526，tests/test_verify_lane_throughput.py:737） | pass | 0/6 | - |
| reverify-corrupt-cache-falls-open-full | 缓存消费零新增打回——verdict_cache.json 损坏不可解析时记 WARNING 后本轮回落全量执行，验证轮正常收敛不产生失败终态（出处 core/verdict_check.py:1249，tests/test_verify_lane_throughput.py:814） | pass | 0/2 | - |
| deliverable-suite-full-green | 交付物测试套件整体收敛回归——tests/test_verify_lane_throughput.py 全部 54 用例通过（并行出题/槽位豁免/judge 治理/缓存重验四能力单测）（出处 tests/test_verify_lane_throughput.py:1，core/pm_engine/dispatch/queue.py:92） | pass | 0/5 | - |
| existing-verify-lane-regression | 既有验证链回归点——本 SPEC 触碰 pipeline/judge_gate/queue/engine/verdict_check/summary，既有验证管线、verdict 稳定复用、fast-track、派发队列、证据分类测试全绿无回归（出处 core/pm_engine/verification/pipeline.py:1386，core/pm_engine/verification/judge_gate.py:255，tests/test_pm_verification.py:1） | pass | 0/3 | - |

## 本轮场景集变更

场景集与持久化集一致，无变更。

