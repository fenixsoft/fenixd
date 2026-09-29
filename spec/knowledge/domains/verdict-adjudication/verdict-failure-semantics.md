<!-- knowledge: capability=verdict-failure-semantics rev=1 sources=spec/archive/2026-09-15-fix-verdict-retry-misattribution -->

# 裁决失败语义

裁决证据校验失败重试路径的语义化分类与分支处置：派发让位与真二次违规严格分离，让位路径零副作用。

## 现行规则

- `core/pm_engine/verification.py` 的 `_verify_verdict_evidence` 返回结构化结果 `{"ok", "cause", "violations", "dispatch_error"}`；cause 枚举至少含 `pass`（首轮合规）、`violations`（重试 judge 成功返回且新产物仍违规）、`dispatch_frozen`、`dispatch_cancelled`、`dispatch_failed`、`dispatch_exception`、`report_missing`；「重试派发未成功执行」的三种情形（frozen/取消/异常）不归入 `violations`。
- frozen/cancelled 让位零写入：`dispatch_frozen` / `dispatch_cancelled` 路径不调用 `update_spec`（不写 status、不写 error、不触 `_cancelled_hold`），不发送任何人工升级告警，仅 INFO 留痕。
- 异常早退：重试派发 `run_planner` 抛出异常（`re_judge=None`）时立即返回 `dispatch_exception`，不继续 `load_report` 对第一轮违规的旧 report.json 复检，不打「重试后仍不合规」ERROR 日志。
- 其它派发失败与违规分离：重试派发因网关拒绝、预算闸门等非 frozen/取消原因失败时返回 `dispatch_failed` 并携带原始 dispatch_error，不发 `verdict_evidence_invalid`（「二次违反证据契约」告警语义不得被派发故障冒用）。
- 真二次违规保留 violations 判定：重试 judge 成功执行并写回新 report.json 且 `validate_report` 仍报违规时，返回 `cause=violations`，violations 为 `validate_report` 原始明细（scenario_id + reason），调用方按既有语义处置（blocked + `verdict_evidence_invalid`）。
- 未知 cause 保守处置：收到枚举之外的 cause 值（前向兼容防护）按 `violations` 同等保守处置（fail-closed）并 ERROR 留痕，不静默放行。
- 首轮 judge run frozen 让位分支：阶段3 首轮 `judge_result.success` 判定处，在既有 cancelled 分支与 provider-circuit-open 分支之后设 frozen 分支——`judge_result` 因 frozen 门失败时 INFO 留痕并 return，不落入 `raise RuntimeError` 兜底（在飞 run 完成时 spec 已被冻结：不 raise、不重派、不改状态）。
- frozen 文案匹配使用 `runner.py` 导出的共享常量，不在 verification.py 内硬编码字面量；取消判定沿用 `cancelled` 结构化字段，不依赖字符串匹配。

## 溯源

- [2026-09-15 fix-verdict-retry-misattribution](spec/archive/2026-09-15-fix-verdict-retry-misattribution/) — 确立 `_verify_verdict_evidence` 六 cause 语义化返回、frozen/cancelled 让位零写入、首轮 frozen 对称分支、派发失败与真违规分离及 frozen 常量同源匹配
