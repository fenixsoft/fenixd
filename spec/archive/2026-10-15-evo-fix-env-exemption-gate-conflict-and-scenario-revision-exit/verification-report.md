# 验证报告：evo-fix-env-exemption-gate-conflict-and-scenario-revision-exit

> ⚠️ 本报告由框架于 2026-10-05T23:39:46Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。
> 报告时效标记（判定本报告是否属上一轮）：合成源轮次指纹：report.json@2026-10-05T23:39:46.308370+00:00+run-result@mtime1791243586338989901

## 结论：✅ 通过（verified）

**状态：verified — 6/6 场景通过，0 失败，0 错误（全部场景通过）**

全绿快道: 6/6 场景通过、0 失败 0 警告——无分类对象，跳过 judge 机械 verified

| 指标 | 数量 |
| --- | --- |
| 通过 | 6 |
| 失败 | 0 |
| 错误 | 0 |
| 产品 Bug | 0 |
| 本链增量 Token（输入） | 1.41M |
| 本链增量 Token（输出） | 0.03M |


## 场景结果

| 场景 | 描述 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- | --- |
| revise-choice-registered | 「场景修订重验出口」注册面探针：裁决注册表须出现 spec 钉死的 revise_scenario_reverify choice，且为 spec 作用域动作（与同族 grant_env_exemption 一致），未注册 id 对照不泄漏。出处：spec/changes/evo-fix-env-exemption-gate-conflict-and-scenario-revision-exit/specs/env-exemption-gate-unification-and-scenario-revision-exit/spec.md「场景修订重验出口」；core/dashboard/data/adjudication_choices.py:255（ADJUDICATION_CHOICES 注册表）、adjudication_choices.py:304-336（resolve_choice 对 spec_scoped 动作的全表反查返回 scoped-no-reverse，故探针直查注册表） | pass | 0/4 | - |
| revision-exit-full-chain-tests | 修订出口全链测试套（tasks 3.3 新建交付物 tests/test_env_scenario_revision_exit.py）：场景不可行→修订→重验→解冻、产品代码路径修订被拒、修订超限转人工、env 归因缺证据降级 inconclusive；pytest 全绿且测试文件引用 choice id 与 inconclusive 结论类。出处：tasks.md 3.3；core/dashboard/data/admin_actions.py:2271（_exec_grant_env_exemption 既有锚点） | pass | 0/5 | - |
| env-exemption-handshake-dual-gate | 跨轮 env 豁免双门一致性套（tasks 3.1 修改交付物 tests/test_verify_env_handshake.py）：有效豁免下升级握手与白化门禁同判放行；场景定义变更/时效过期后同判拒绝；0-pass 场景不可白化不回退。出处：spec.md「跨轮 env 豁免的统一数据源」；core/pm_engine/verification/escalation.py:455（_env_whitewash_gate）、core/verdict_check.py:525（whitewash_violations） | pass | 0/2 | - |
| env-exemption-reachability-regression | 豁免出口既有闭环用例不回退 + 豁免 STATE 字段写入/读取镜像一致（tasks 3.2 修改交付物 tests/test_env_exemption_exit_reachability.py）。出处：tasks.md 3.2；core/dashboard/data/admin_actions.py:2271（_exec_grant_env_exemption：豁免落点自 AdminStore disposition 切换为 spec 级 STATE 字段，disposition 降为审计镜像） | pass | 0/2 | - |
| exemption-core-regression-suite | 核心回归面：注册表契约快照（新增 choice 必须同步 _EXPECTED_CHOICE_IDS，防「加 choice 忘更契约测试」漏改）、env 阻塞冻结闸、verdict 可信度门三套既有测试全绿。出处：tests/test_adjudication_choices.py:41-53（_EXPECTED_CHOICE_IDS 快照，inconclusive_loop 桶现值 grant_env_exemption/manual_fixed_reverify/abandon）、tests/test_blocked_reverify_gate.py、tests/test_verdict_credibility_gate.py | pass | 0/2 | - |
| freeze-threshold-invariant-probe | 非目标不变量探针：ENV_BLOCK_FREEZE_THRESHOLD 冻结阈值保持 2、_env_block_rounds 字段常量在位——本 SPEC 明示不动冻结阈值与 verified 唯一自动清除路径，豁免认可不得以放宽冻结阈值实现。出处：proposal.md「非目标」；core/state_machine.py:287（ENV_BLOCK_FREEZE_THRESHOLD = 2 既有锚点）、core/state_machine.py:280（ENV_BLOCK_ROUNDS_FIELD） | pass | 0/3 | - |
