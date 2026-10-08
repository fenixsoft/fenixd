# code-fix-lane 变更

## ADDED Requirements

### Requirement: 零失败面回归的异常判据与证据留存

回归门禁产不出可用失败用例明细（timeout、total=0）时，必须被异常判据识别并快速收口，且明细档须保留可用于定位毒化源的进度证据。

#### Scenario: timeout 零失败面计入异常

- **When** 某轮回归以 timeout 结束且失败明细映射不出任何用例（items 为空、fallback_full=true）
- **Then** `_is_regression_anomaly` 判定为异常，该记录按 anomaly 分档（跨链重派预算 1）并触发一次性降档告警

#### Scenario: timeout 零失败面首记即收口

- **When** 同一批定向重试中出现首记 timeout 零失败面
- **Then** 不再等待连续 2 次计数，当轮即提前终止本批定向重试并按 anomaly 预算停止自动重派；parse_error/failed 形态的既有熔断阈值维持 2 不变

#### Scenario: 明细档留存慢测试进度

- **When** 回归异常（timeout/total=0）写 fix-reg-failures-regression-*.json 明细档且快照中存在 long_tests（或 junit.xml.log 尾段）
- **Then** 明细档并入该进度证据（用例名+耗时），worktree 清理后证据仍可回收；旧快照无该字段时明细档保持现形态不报错，既有消费方（items/fallback_full）不受影响