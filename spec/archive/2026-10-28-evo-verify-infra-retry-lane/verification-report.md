# 验证报告：evo-verify-infra-retry-lane

> ⚠️ 本报告由框架于 2026-10-06T19:59:52Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。
> 报告时效标记（判定本报告是否属上一轮）：合成源轮次指纹：report.json@2026-10-06T19:59:51.543971+00:00+run-result@mtime1791316791577846994

## 结论：✅ 通过（verified）

**状态：verified — 11/11 场景通过，0 失败，0 错误（全部场景通过）**

全绿快道: 11/11 场景通过、0 失败 0 警告——无分类对象，跳过 judge 机械 verified

| 指标 | 数量 |
| --- | --- |
| 通过 | 11 |
| 失败 | 0 |
| 错误 | 0 |
| 产品 Bug | 0 |
| 本链增量 Token（输入） | 1.93M |
| 本链增量 Token（输出） | 0.04M |


## 场景结果

| 场景 | 描述 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- | --- |
| infra-retry-lane-unit-tests | 交付测试套件全量执行：tests/test_verify_infra_retry_lane.py（tasks 3.1 新建文件）在验证树上以 -v 运行且全部通过。覆盖点：prepare/可达性失败→infra-retry 廉价重派、连败达阈值恢复全价、两本账互不污染、D5 通道不增减同因重派记账、D2 历史观测账不吃重试预算、unfreeze 后专用计数从零起算（出题依据：spec/changes/evo-verify-infra-retry-lane/tasks.md 3.1；命令形态遵循 pytest 输出断言硬约束：只 -v 不 -q）。 | pass | 0/4 | - |
| infra-retry-cheap-lane-first-failure | 行为探针（tasks 1.2/1.3 正向路径）：prepare 失败首次命中 infra-retry 车道——真实 StateMachine + PMEngine harness 上带车道标记调用升级决议点 _escalate_env_blocked（core/pm_engine/verification/escalation.py，D6 决策单点），断言：不写 blocked/error、_env_block_rounds 不递增、不产生 .fenix/admin_invoke_request.json admin 呼叫、出现专用 infra-retry 计数新字段（非 _verify_infra_rounds 观测账）；另验 D2：预置 _verify_infra_rounds=3 历史全价轮后首次 prepare 失败仍获完整重试预算（不 blocked）。车道标记参数名以签名内省自适应（含 infra 或 lane 的参数），值先试 True 再试 "infra-retry"。 | pass | 0/10 | - |
| infra-retry-threshold-restores-full-price | 行为探针（tasks 1.2 连败升级 + D2 清零点）：连续 prepare 失败——前几次走廉价重派（首次必不 blocked），达专用计数阈值（缺省 2 次重试）后恢复既有全价升级：写 blocked、产生 admin 呼叫文件、_env_block_rounds 开始递增；再一轮全价后按 ENV_BLOCK_FREEZE_THRESHOLD=2 冻结转人工（既有语义不回归）；随后 unfreeze_spec 解冻：_env_block_rounds 与专用 infra-retry 计数同轮清零（D2 清零清单），解冻后再次单次 prepare 失败仍走廉价车道（重试预算从零起算、不再立即升级）。阈值边界以区间断言容差（首次 blocked 出现在第 2~4 次失败之间），兼容「2 次重试后第 3 败升级」与「第 2 败即升级」两种实现读法。 | pass | 0/14 | - |
| env-blocked-semantics-no-regression | 行为探针（SPEC「env 阻塞语义不回归」红线，tasks 3.2 同源语义）：不带 infra-retry 车道标记调用同一升级决议点，既有全价路径必须原样：写 blocked、产生 .fenix/admin_invoke_request.json admin 呼叫、_env_block_rounds=1、首轮未冻结（阈值 2 不变）、_verify_infra_rounds 观测账照常递增（两本账在 env 车道行为与改动前一致）。 | pass | 0/7 | - |
| infra-retry-wiring-structure | 结构探针（design D5/D6 落点审计）：读四个交付核心文件源码断言——① D6 单点传标记：pipeline.py 内 _escalate_env_blocked 调用点恰一处携带 infra 车道标记，且该处保留 user_blocked 守卫与应用不可达 fail-fast 语境；② D6 决议收敛：escalation.py/infra_classify.py 含 infra-retry 决议逻辑（旁路判定在升级函数入口）；③ D5：infra-retry 通道不增减 _redispatch_same_cause_streak/_redispatch_cause_fp（三交付文件引用数保持基线 0，基线实测于改动前工作树 2026-10-07）；④ D2：unfreeze_spec 清零清单含专用 infra-retry 计数（区分常量名/字面量两种写法解析），且非观测账 _verify_infra_rounds；⑤ D2：专用字段/阈值落 state_machine.py（_bump_counter 机制）。 | pass | 0/10 | - |
| template-precheck-sample-content | 模板样板内容探针（tasks 2.1）：core/verify_contract_template.yaml prepare 段补齐宿主预检示例（注释形态）——逐要素断言：无主 qemu/emulator 进程扫描清理指引、ppid=1 且可归属已完成 run 的归属判定、被杀 pid 留痕指引、残留 AVD 锁清理、KVM 水位、内存水位检查、场景特异冒烟探针（OpenCV init）添加指引、「预检失败走 infra-retry 廉价重试」语义说明；并断言模板安全基线不回归：全注释形态保持（非注释行数=0，test_verify_contract_template_preflight 同源语义），样板位于 prepare 段文档区。 | pass | 0/12 | - |
| inconclusive-loop-escalation-regression | 红线回归（tasks 3.2）：tests/test_inconclusive_loop_escalation.py 交付改动后在验证树全量通过——场景执行期 env 阻塞仍走既有 blocked→升级路径、inconclusive 循环计数/unfreeze 清零语义不受 infra-retry 车道影响。 | pass | 0/2 | - |
| infra-budget-exempt-regression | 红线回归：tests/test_infra_budget_exempt.py 全量通过——_record_infra_failure 既有语义保持（预算退款幂等、_verify_infra_rounds 观测记账、env 阻塞保持 blocked 语义），infra-retry 车道扩展不得改变既有 infra 归因与记账行为（design：两本账并存、互不污染）。 | pass | 0/2 | - |
| verify-preflight-gate-regression | 红线回归：tests/test_verify_preflight_gate.py 全量通过——可达性 fail-fast 分支（core/pm_engine/verification/pipeline.py _execute_stage2 应用不可达短路，infra-retry 车道的唯一改造点）既有行为不回归（boot.log 尾部 evidence、短路语义、user_blocked 守卫）。 | pass | 0/2 | - |
| state-machine-counter-regression | 红线回归：tests/test_state_machine.py 全量通过——_bump_counter 计数机制、ENV_BLOCK_ROUNDS_FIELD、unfreeze_spec 清零清单（新专用计数加入后既有清零项不受影响）等状态机行为不回归。 | pass | 0/2 | - |
| verify-contract-template-preflight-regression | 红线回归：tests/test_verify_contract_template_preflight.py 全量通过——模板态前置预检测试（全注释模板=合法无契约回退、非注释行数=0 基线）在 prepare 段新增注释样板后不回归。 | pass | 0/2 | - |
