# 验证报告：evo-fix-verify-parallel-override-type

> ⚠️ 本报告由框架于 2026-10-03T20:47:53Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。
> 报告时效标记（判定本报告是否属上一轮）：合成源轮次指纹：report.json@2026-10-03T20:47:52.593531+00:00+run-result@mtime1791060472623479648

## 结论：✅ 通过（verified）

**状态：verified — 8/8 场景通过，0 失败，0 错误（全部场景通过）**

全绿快道: 8/8 场景通过、0 失败 0 警告——无分类对象，跳过 judge 机械 verified

| 指标 | 数量 |
| --- | --- |
| 通过 | 8 |
| 失败 | 0 |
| 错误 | 0 |
| 产品 Bug | 0 |
| 本链增量 Token（输入） | 1.43M |
| 本链增量 Token（输出） | 0.04M |


## 场景结果

| 场景 | 描述 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- | --- |
| vpo-dedicated-suite-green | 全量跑本 spec 交付新增的专项测试模块（14 用例：人工裁决复位 null×2、写侧守卫×5、parse 归一×6、读端告警×1）。-v 独立使用（不并列 -q，pytest 9 中 -q 覆盖 -v 会退化输出丢 PASSED 行）；output_match 逐用例照抄实测 PASSED 行（无 parametrize 后缀）。（出处：tests/test_verify_parallel_override_reset.py；tasks 3.1 覆盖面） | pass | 0/11 | - |
| vpo-write-side-shape-guard-probe | 进程内直驱生产 StateMachine 验证「非法形状拦截」：update_spec 写 _verify_parallel_override=False/True/'False'/'true'/2.5 均被写侧单字段守卫拒绝（读回无该字段、拒绝告警在场、STATE.md 无该字段落盘行）；合法 int 2 放行且往返读回 int、None 复位读回 None；守卫只剥该字段——同批 priority=7 照常应用、既有合法值 2 保留（拒绝不等于清空）。探针输出 JSON，json_output 逐键断言。（出处：core/state_machine.py:1428-1435 _apply_updates_entry 单字段形状守卫、_log_update_applied 拒绝留痕 warning；specs/verify-parallel-override/spec.md「非法形状拦截」） | pass | 0/12 | - |
| vpo-parse-side-normalization-probe | 手写存量坏值 STATE.md 验证 parse 侧 int\|None 归一：'False' 首读清洗为 None 且幂等（二读仍 None 不抖动）、带引号 'true' 与不带引号 true 字面量清洗为 None、int 字面量 2 往返读回 int 类型（可观察类型变化 "2"→2）、null/None 字面量读回 None（空态/复位语义）。探针输出 JSON，json_output 逐键断言。（出处：core/state_machine.py:572-589 _verify_parallel_override int\|None 归一分支；proposal 验收「注入 'False'/'true' 等字符串…归 None」「往返值 "2"→2」） | pass | 0/14 | - |
| vpo-adjudication-reset-e2e | 两段式端到端（跨进程 STATE.md 往返）：step1 进程内装配临时项目 STATE.md（frozen spec 且 _verify_parallel_override=2），调生产 reset_verification（judge_rerun_cap 信号）断言 ok=true；step2 全新 python 进程重读同一 STATE.md——字段读回 None、落盘字面量为 `- _verify_parallel_override: null`、无 False 字面量残留。跨进程重读证明的是落盘往返而非进程内存态，验证启动沿用配置并行度、不再触发解析降档告警。（出处：core/dashboard/data/admin_actions.py:1573 _RETRY_COUNTER_RESETS 该字段=None、reset_verification 消费点；specs/verify-parallel-override/spec.md「复位写 null」） | pass | 0/6 | - |
| vpo-continue-autofix-e2e | 同型验证 continue_auto_fix 写侧归位：step1 装配 frozen spec（_verify_parallel_override=1，verify_fail_escalation 冻结 reason 形态），调生产 _exec_continue_auto_fix 断言 ok=true；step2 全新进程重读——字段 None、落盘 null 字面量、无 False 残留。人工裁决每次重写是本案复发确定性来源，两个处置动词都必须归位。（出处：core/dashboard/data/admin_actions.py _exec_continue_auto_fix 消费 _RETRY_COUNTER_RESETS；specs/verify-parallel-override/spec.md「复位写 null」WHEN 分支） | pass | 0/6 | - |
| vpo-read-side-warning-repr-source | 定向跑提交的读端告警用例（三段式验证链 harness + 旁路坏值 'False' 注入 read_one，绕开写侧守卫模拟锁外内存写形态）：解析失败降档沿用配置并行度 5（不把布尔语义映射为特定并行度）、告警含 repr（_verify_parallel_override='False'）与字段来源「取自 spec attrs」。（出处：core/pm_engine/verification/pipeline.py:2110-2119 读端告警补来源；specs/verify-parallel-override/spec.md「非法值告警」；tests/test_verify_parallel_override_reset.py::TestReadSideWarningKeepsRepr::test_unparseable_value_warns_with_repr_and_source） | pass | 0/3 | - |
| vpo-backoff-regression-zero-drift | 回归：既有降档链路测试模块 17 用例零回退——int() 包裹断言对 str/int 双形态兼容，parse 归一不得改变降档写值与复位行为；output_match 照抄实测 PASSED 行（覆盖降档写、健康轮复位、unfreeze/fast-track/全链清零、读端覆盖与配置并行度保持）。（出处：tests/test_verify_parallel_backoff.py；proposal 验收「既有 tests/test_verify_parallel_backoff.py 零回退」） | pass | 0/7 | - |
| vpo-characterization-int-roundtrip-regression | 回归：定向跑表征测试降档计数与健康轮复位两用例——前者断言已同轮更新为 int 2（parse 归一带来的可观察类型变化 "2"→2 不静默留红，tests/test_characterization_verification.py:177），后者覆盖复位路径 _verify_parallel_override=None。（出处：tests/test_characterization_verification.py::TestHandleEnvBlockedInconclusive；proposal 验收第三条「同轮更新…不静默留红」） | pass | 0/4 | - |
