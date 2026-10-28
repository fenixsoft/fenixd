# Design: add-codefix-parse-error-breaker

## Context

code-fix 批收尾定向重试循环（`core/code_fix.py` `CodeFixChain` 批 worker，首轮回归失败后的 `for attempt in range(1, retry_max + 1)` 块）对**任何**回归失败一视同仁：提取明细（映射失败回退全量）→ 派定向 run → 再回归 → 下一轮。当回归根本没跑出可用结果（`parse_error`：junit 产物不存在/不可解析；或 `failed` 但明细空）时，重试注入的「失败明细」是空的、fail-closed 回退的全量回归还会死于同一种死法——2026-10-07 实证全天 20+ run / 15 次回归耗在第 1 批、3 轮全部同死。

## Goals / Non-Goals

- **Goals**：同批内回归异常类失败连续达阈值即提前终止重试循环；收口语义（现场即弃、入档、告警）与轮数耗尽完全一致；不新增配置键、零前端改动。
- **Non-Goals**：不诊断/修复回归为什么 parse_error（那是运行环境/测试套件问题，另案）；不改动 `targeted_retry_max`、跨链 `FAIL_RETRY_MAX` 预算、告警文案既有形态；不给 parse_error 增加「跳过回归直接合回」的旁路。

## Decisions

### D1. 熔断判据 = 回归未产出可用失败明细

判据收在循环内每轮回归结果处：

```python
def _is_regression_anomaly(reg, fail_items) -> bool:
    if reg.get("status") == "parse_error":
        return True
    return reg.get("status") == "failed" and not fail_items
```

- `parse_error`：junit 缺失/不可解析，`fail_items` 恒空。
- `failed` 且 `fail_items` 空：junit 可解析但零失败明细（空套件/解析畸形），同样不可注入。
- 真实测试失败（`failed` 且明细非空）**不进熔断计数**，且将计数**清零**——「偶发一次环境抖动后恢复正常」不应累积误杀。

### D2. 阈值为模块常量，不进配置

`REGRESSION_ANOMALY_BREAKER_THRESHOLD = 2`（`core/code_fix.py` 模块级常量）。理由：熔断是防烧钱的保守兜底而非调优旋钮；新增配置键按项目约定必须连带 Dashboard 界面（先例约束），为一个兜底阈值增设受管配置面不划算。文档（`docs/help` 若有 code-fix 章节）随批补充说明即可。

### D3. 计数与短路位置：复用既有循环骨架，收口走 exhausted 同一路径

- 循环外初始化 `anomaly_streak = 0`、`breaker_triggered = False`。
- 首轮回归失败进入重试循环前（`_ingest_failure_round` 之后）计数一次；每个定向轮回归非 passed 时（既有 `if reg.status == "passed": break` 的对偶位置）再计数。
- 计数达阈值：置 `breaker_triggered = True`，记 WARNING（含两轮各自 status 与明细形态），**不再派发下一轮 run**，直接以 `exhausted` 等价状态进入既有现场即弃收口块——收口的入档、worktree 清理、锁释放、告警代码**零分叉复用**。
- 收口 reason：`record_failed_batch(..., reason="regression_parse_error_breaker" if breaker_triggered else "regression_failed_twice", ...)`；进度 `write_progress` 的 reason 同口径换字符串；告警仍走既有 `write_regression_failed_alert` 单一调用点（同批只此一处，天然不重复），`retry_rounds` 传实际执行轮数。

### D4. 计数窗口 = 同批内连续，跨批/跨链不累计

熔断状态是批 worker 局部变量，批收口即消失；下一批（或下一条链重组批）从零开始。跨链重试仍由既有 `fail_count/FAIL_RETRY_MAX` 预算兜底——两层机制正交。

## Risks / Trade-offs

- **误杀面**：环境抖动连续两次 parse_error 会把本可重试的批提前判死——但该批按 `fail_count` 预算仍会被下一条链自动重试（预算内零人工），损失仅为「本链少烧两轮全量」，方向正确。
- **判据漂移**：若未来回归执行层新增「有明细但整体不可信」的 status，须同步纳入判据——判据函数单点收口（D1），漂移面可控。
- **告警文案**：`regression_failed_twice` 历史兼容名继续沿用于轮数耗尽路径；熔断路径档案 reason 用新名 `regression_parse_error_breaker`，检索侧既有代码按 reason 前缀匹配的地方（若有）需 grep 确认——tasks 含专项检查项。

## Open Questions

（无——阈值/判据/收口语义均已定）
