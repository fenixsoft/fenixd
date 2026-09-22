# 验证报告：evo-sigterm-source-tracking-cooldown

> ⚠️ 本报告由框架于 2026-09-17T20:35:09Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。
> 报告时效标记（判定本报告是否属上一轮）：合成源轮次指纹：report.json@2026-09-17T20:35:09.510156+00:00

## 结论：✅ 通过（verified）

**状态：verified — 9/9 场景通过，0 失败，0 错误（全部场景通过）**

全绿快道: 9/9 场景通过、0 失败 0 警告——无分类对象，跳过 judge 机械 verified

| 指标 | 数量 |
| --- | --- |
| 通过 | 9 |
| 失败 | 0 |
| 错误 | 0 |
| 产品 Bug | 0 |
| 本链增量 Token（输入） | 1.41M |
| 本链增量 Token（输出） | 0.01M |


## 场景结果

| 场景 | 描述 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- | --- |
| sigterm-external-kill-labeled | 2.1 外部信号致死（143/-9/负信号，无 shutdown 标记）归因带 [signal-kill: …] 标签、不归 [provider-transient]、不记全局瞬断指纹；信号发出者不可考时 unknown 形态带 returncode。验证依据：tests/test_sigterm_source_tracking.py 的 TestExternalSignalKillLabel（4 个参数化用例）。 | pass | 0/5 | - |
| sigterm-shutdown-guard-unchanged | 2.2 shutting_down 置位 / 产物 interrupted 标记存在时维持既有 [shutdown-interrupted] 守卫（不回归），信号计数不计入。验证依据：tests/test_sigterm_source_tracking.py 的 TestShutdownGuardUnchanged（2 个用例）。 | pass | 0/3 | - |
| sigterm-cooldown-circuit-recovery | 2.3 143/-9 信号死法连续达阈值（3）触发该 spec 维度冷却：冷却期不重试、到期自动恢复计数清零、全局瞬断熔断从未被触发；成功收工重置连续计数。验证依据：tests/test_sigterm_source_tracking.py 的 TestSignalKillCooldown（3 个用例）。 | pass | 0/4 | - |
| sigterm-network-transient-unchanged | 2.4 provider 网络抖动类瞬态（非信号死法）既有退避不变：错误仍带 [provider-transient] 标签、原地重试照旧、信号通道零计数零标签。验证依据：tests/test_sigterm_source_tracking.py 的 TestNetworkTransientUnchanged。 | pass | 0/2 | - |
| sigterm-artifact-gate-channel-isolation | 2.5 产物硬门失败通道隔离：结构类（结果文件缺失）保留 [provider-transient] 标签与原地退避重试（transient_retry 事件，reason=artifact_gate）但不记全局瞬断指纹；任务完成度类（[task-gate]）不带 [provider-transient] 标签、不进原地瞬态退避预算，重试由 attempt 层承担。验证依据：tests/test_sigterm_source_tracking.py 的 TestArtifactGateChannelIsolation（2 个用例）。 | pass | 0/3 | - |
| sigterm-framework-self-kill-excluded | 2.6 框架自身强杀（supervision 超时/轮次上限：returncode=-9 且错误文本 Timeout after …/Max turns …）不打信号标签、不计信号冷却、亦不归 [provider-transient]（框架自己强杀不得冷却链路）。验证依据：tests/test_sigterm_source_tracking.py 的 TestFrameworkSelfKillExcluded（2 个参数化用例）。 | pass | 0/3 | - |
| sigterm-label-function-unit | 标签纯函数映射正确性：_signal_kill_label 对 143/130/-9/-15/-7/-1 返回对应 [signal-kill: …] 标签，对 1/0/None 返回 None。验证依据：tests/test_sigterm_source_tracking.py 的 TestSignalKillLabelFunction（2 个用例）。 | pass | 0/3 | - |
| sigterm-regression-circuit-transient | 设计文档回归点 1：既有 tests/test_provider_circuit.py 与 tests/test_transient_backoff.py 回归，信号冷却通道不得回归 4xx/切换类熔断与正常瞬态退避语义（79 个用例全过）。 | pass | 0/2 | - |
| sigterm-regression-runner-gate | 设计文档回归点 2：既有 tests/test_agent_runner.py 与 tests/test_agent_runner_gate.py 回归，agent_runner 既有执行路径与产物硬门契约（add-judge-artifact-gate D1）不回归（44 个用例全过）。 | pass | 0/2 | - |

## 本轮场景集变更

当前稳定场景集共 9 个（第 1 轮）。

- 首轮写入 9 个场景

