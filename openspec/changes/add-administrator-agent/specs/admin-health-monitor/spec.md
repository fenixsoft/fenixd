# admin-health-monitor Spec

## ADDED Requirements

### Requirement: 周期性困境检测
Fenixd SHALL 在存在进行中 spec（`implementing`/`testing`）时，按 `admin.interval_minutes`（默认 5）周期运行轻量健康检查。检查 SHALL 仅基于本地数据（STATE.md、`.fenix/runs/` 转录、`fenixd.log`），不调用任何 LLM。检测项 MUST 包括：
- 同一 spec 短时间窗口内重复失败（失败 run 数超阈值）
- spec 状态抖动（`ready`↔`implementing` 快速切换）
- spec 卡死（`implementing`/`testing` 超过 `stuck_threshold_minutes` 无进展）
- 重复 merge-back 失败（`_merge_streak` 已达熔断阈值仍停留）
- daemon 日志中的连续 ERROR

#### Scenario: 检测到重复失败
- **WHEN** 某 spec 在 30 分钟内产生 ≥3 次失败 run
- **THEN** 监视器记录困境信号，触发 Administrator 唤起

#### Scenario: 检测到状态抖动
- **WHEN** STATE.md 显示某 spec 在 10 分钟内 `ready`↔`implementing` 切换 ≥3 次
- **THEN** 监视器标记该 spec 为抖动困境

#### Scenario: 检测到卡死
- **WHEN** 某 spec 处于 `implementing`/`testing` 超过 `stuck_threshold_minutes`（默认 60）且无 run 进度
- **THEN** 监视器标记该 spec 为卡死困境

#### Scenario: 无困境时不动作
- **WHEN** 所有进行中 spec 运行正常
- **THEN** 监视器仅更新最后检查时间戳，不唤起任何 Agent、不产生任何 LLM 成本

### Requirement: 监视器降噪与节流
Fenixd SHALL 对同一困境信号做节流：同一 spec 的同一类信号在 `admin.escalation_cooldown_minutes`（默认 15）内只唤起一次 Administrator，避免反复唤起烧钱。

#### Scenario: 节流避免重复唤起
- **WHEN** 监视器在 5 分钟内两次检测到同一 spec 的同一困境
- **THEN** 只唤起一次 Administrator，第二次仅记录、跳过唤起
