# 验证报告：add-verify-parallel-backoff

> ⚠️ 本报告由框架于 2026-09-11T04:51:11Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。

## 结论：✅ 通过（verified）

**状态：verified — 13/13 场景通过，0 失败，0 错误（全部场景通过）**

全绿快道: 13/13 场景通过、0 失败 0 警告——无分类对象，跳过 judge 机械 verified

| 指标 | 数量 |
| --- | --- |
| 通过 | 13 |
| 失败 | 0 |
| 错误 | 0 |
| 产品 Bug | 0 |
| 本链增量 Token（输入） | 3.65M |
| 本链增量 Token（输出） | 0.05M |


## 场景结果

| 场景 | 描述 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- | --- |
| cli-first-attempt-no-degrade | 首次 inconclusive 重验不降档（spec Scenario: 首次 inconclusive 重验不降档）：max_parallel=5 配置下第 1 轮全批 blocked-env，_handle_env_blocked_inconclusive 处理后 _inconclusive_attempts=1 且 spec attrs 不含 _verify_parallel_override，重验轮有效并行度保持配置值。出处：core/pm_engine/verification.py:181-202 | pass | 0/4 | - |
| cli-consecutive-attempts-degrade | 连续 blocked-env 逐轮递减（spec Scenario: 连续 blocked-env 逐轮递减）：max_parallel=5 下第 2 轮 _verify_parallel_override=2（5>>1），第 3 轮=1（5>>2），递减公式 max(1, base>>(attempts-1))。出处：core/pm_engine/verification.py:198-202 | pass | 0/3 | - |
| cli-low-config-bottoms-out | 低配置值直接触底（spec Scenario: 低配置值直接触底）：配置 max_parallel=2 且第 2 轮重验时 _verify_parallel_override=1（2>>1=1）。出处：core/pm_engine/verification.py:198-202 | pass | 0/3 | - |
| cli-healthy-round-reset | 环境恢复后并行度复位（spec Scenario: 环境恢复后并行度复位）：降档轮（override=2）后出现有效失败（failed>0）的轮次非 inconclusive，_verify_parallel_override 被清除，恢复配置并行度。出处：core/pm_engine/verification.py:137-139 | pass | 0/3 | - |
| cli-unfreeze-reset | 人工解冻后降档不残留（spec Scenario: 人工解冻后降档不残留）：SPEC 冻结后人工 unfreeze，_inconclusive_attempts 与 _verify_parallel_override 同轮清零，重验从配置并行度开始。出处：core/state_machine.py:585 | pass | 0/3 | - |
| cli-fasttrack-verified-reset | fast-track verified 清零点同步清降档（spec 健康轮复位 requirement 的既有清零点）：fast-track 硬校验通过推进 verified 时，_inconclusive_attempts 与 _verify_parallel_override 同 update 清零。出处：core/pm_engine/dispatch.py:2569 | pass | 0/4 | - |
| cli-fullchain-verified-reset | 全链 verified（非 fast-track）落点同步清降档：完整三阶段验证 verdict=verified 落点处 _inconclusive_attempts 清零时同步清 _verify_parallel_override。出处：core/pm_engine/verification.py:2749 | pass | 0/4 | - |
| cli-engine-override-read | 重验轮引擎读取 spec attrs 的 _verify_parallel_override 覆盖 max_parallel（spec Requirement: 下一轮验证 VerifyEngine MUST 以该值覆盖 max_parallel 配置值）：spec attrs 含 override=2 时构造 VerifyEngine 有效并行度=2 且降档来源标记生效。出处：core/pm_engine/verification.py:1608-1624 | pass | 0/3 | - |
| cli-normal-round-no-override-read | 无 override 的正常轮引擎保持配置并行度、不打降档标记：spec attrs 无 _verify_parallel_override 时有效并行度=配置值 5。出处：core/pm_engine/verification.py:1608-1624 | pass | 0/3 | - |
| cli-degraded-round-log-report | 降档轮日志与报告可见（spec Scenario: 降档轮日志与报告可见）：_parallel_override_active 生效时引擎启动日志含「并行度=2（inconclusive 降档）」标记，report.json 顶层 effective_parallel=2。出处：core/verify_engine/engine.py:173-181,434 | pass | 0/3 | - |
| cli-normal-round-no-marker | 正常轮无降档标记（spec Scenario: 正常轮无降档标记）：无 override 的常规验证轮日志并行度=配置值、无降档来源标记，report 顶层 effective_parallel=配置值（正常轮也写，值=配置值）。出处：core/verify_engine/engine.py:173-181,434 | pass | 0/3 | - |
| cli-stop-retry-keeps-override | 停验/升级分支保留降档现场（spec 健康轮复位的边界）：attempts 达 max 停验或达 escalate 升级时 _verify_parallel_override 保持原值不清除，冻结待人工时保留现场证据。出处：core/pm_engine/verification.py:204-230 | pass | 0/5 | - |
| cli-unit-test-suite-pass | 本 SPEC 单元测试全量通过（回归覆盖）：运行 tests/test_verify_parallel_backoff.py 全部测试用例验证写端/复位/清零点/读端/可观测全链路 PASS。出处：tests/test_verify_parallel_backoff.py | pass | 0/3 | - |

## 本轮场景集变更

当前稳定场景集共 13 个（第 1 轮）。

- 首轮写入 13 个场景

