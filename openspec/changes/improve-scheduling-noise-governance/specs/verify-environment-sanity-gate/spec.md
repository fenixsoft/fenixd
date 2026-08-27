# spec-verify-environment-sanity-gate

## ADDED Requirements

### Requirement: mock 环境下等待类断言的健全性探针
当某场景的步骤序列包含 `mock_api` 类步骤、且其失败断言属于纯 DOM/SSE 等待超时（Locator.wait_for Timeout 等无业务信息错误）时，verify_engine SHALL 在判 fail 前对被测 dashboard 实例执行环境健全性探针（连通 + 推流检查）；探针证实实例失联/推流中断时，该场景 MUST 记为 `blocked-env` 并计入 warning 统计而非 fail。

#### Scenario: mock 断链下的 UI 超时被降级
- **WHEN** 场景含 mock_api 步骤，UI 断言因 Locator 等待超时失败，且探针检测到 SSE 推流未到达
- **THEN** 场景 status=blocked-env，report.summary.blocked_env 加一，failed 计数不含它

#### Scenario: 探针健康时维持真失败
- **WHEN** 同样超时但探针确认实例在线且推流正常
- **THEN** 场景保持 fail 判定不变

### Requirement: blocked-env 的报告与门禁换算
report.summary SHALL 新增 `blocked_env` 字段；验证放行门禁与 done 判定使用 `有效失败 = failed - blocked_env`；当全部原始失败均为 blocked-env 时整体结果 MUST 判为 `inconclusive`，对应处理为保持 testing 并重新派发新 attempt。

#### Scenario: 全批环境性失联触发重验
- **WHEN** 一轮 17 个场景中 raw_failed 全部为 blocked-env
- **THEN** 整体 verdict=inconclusive，spec 回到 testing 排队重验，不产生 bug-found

### Requirement: 重验通道不烧信号预算
inconclusive 重派 SHALL 不计入 repeated_failures 困境信号的失败次数；同一场景在重验轮次中若探针转为健康并再次失败，则按真实 bug-found 流转。

#### Scenario: 连续 inconclusive 不唤醒 Administrator
- **WHEN** 某 SPEC 连续两轮验证均 inconclusive
- **THEN** admin_alerts 中无该 spec 的 repeated_failures 新增记录

#### Scenario: 环境恢复后的真失败照常晋级
- **WHEN** 首轮 inconclusive 后环境恢复正常，第二轮同场景仍超时且探针通过
- **THEN** 该场景计为真 fail，按既有 bug-found 流程处理
