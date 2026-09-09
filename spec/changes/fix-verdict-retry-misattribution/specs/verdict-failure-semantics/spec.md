# verdict-failure-semantics — 裁决证据校验失败的语义化分类与分支处置

## ADDED Requirements

### Requirement: 裁决重试路径语义化返回
`core/pm_engine/verification.py` 的 `_verify_verdict_evidence` SHALL 返回结构化结果 `{"ok": bool, "cause": str, "violations": list, "dispatch_error": str}`，取代布尔。cause 枚举 SHALL 至少含：`pass`（首轮合规）、`violations`（重试 judge 成功返回且新产物仍违规）、`dispatch_frozen`、`dispatch_cancelled`、`dispatch_failed`、`dispatch_exception`、`report_missing`。「重试派发未成功执行」的三种情形（frozen/取消/异常）MUST NOT 归入 `violations`。

#### Scenario: frozen 拦截不判二次违规
- **WHEN** 第一轮校验失败后发起重试，`run_planner` 因 spec 处于人工冻结被 attempt 顶部 frozen 门拦截（不派发 attempt，`success=False, error` 以 frozen 文案开头）
- **THEN** 返回 `{"ok": False, "cause": "dispatch_frozen"}`；调用方不写 blocked、不发 `verdict_evidence_invalid` 告警、不改 spec 任何状态，仅 INFO 留痕（复放 2026-09-08T09:28:36 场景零告警）

#### Scenario: 取消旗标拦截同语义让位
- **WHEN** 重试派发被 run 取消旗标拦截（`AgentRunResult.cancelled` 为真）
- **THEN** 返回 `cause="dispatch_cancelled"`；不写任何状态、不发告警，INFO 留痕

#### Scenario: 异常早退不复读旧文件
- **WHEN** 重试派发 `run_planner` 抛出异常（`re_judge=None`）
- **THEN** 立即返回 `cause="dispatch_exception"`，MUST NOT 继续执行 `load_report` 对第一轮违规的旧 report.json 复检，MUST NOT 打出「重试后仍不合规」ERROR 日志

#### Scenario: 真二次违规保留 violations 判定
- **WHEN** 重试 judge 成功执行并写回新 report.json，`validate_report` 仍报违规
- **THEN** 返回 `cause="violations"` 且 violations 为 `validate_report` 原始明细（scenario_id + reason），调用方按既有语义处置（blocked + `verdict_evidence_invalid`）

#### Scenario: 其它派发失败与违规分离
- **WHEN** 重试派发因网关拒绝、预算闸门等非 frozen/取消原因失败
- **THEN** 返回 `cause="dispatch_failed"` 并携带原始 dispatch_error；MUST NOT 发 `verdict_evidence_invalid`（「二次违反证据契约」告警语义不得被派发故障冒用）

#### Scenario: 未知 cause 保守处置
- **WHEN** 调用方收到枚举之外的 cause 值（前向兼容防护）
- **THEN** 按 `violations` 同等保守处置（fail-closed）并 ERROR 留痕，不静默放行

### Requirement: frozen/cancelled 让位零写入
`dispatch_frozen` / `dispatch_cancelled` 路径 MUST NOT 调用 `update_spec`（不写 status、不写 error、不触 `_cancelled_hold`）， MUST NOT 发送任何人工升级告警。

#### Scenario: 让位路径状态机零副作用
- **WHEN** 重试派发被 frozen 或取消拦截
- **THEN** STATE.md 该 spec 条目 updated 时间戳外的任何字段（status/error/hold 标记）均不变

### Requirement: 首轮 judge run frozen 让位分支
阶段3 首轮 `judge_result.success` 判定处 SHALL 在既有 cancelled 分支与 provider-circuit-open 分支之后新增 frozen 分支：`judge_result` 因 frozen 门失败时 INFO 留痕并 return，MUST NOT 落入 `raise RuntimeError` 兜底。

#### Scenario: 在飞 run 完成时 spec 已冻结
- **WHEN** judge 首次派发于冻结前、run 在飞期间 spec 被冻结、run 完成返回 frozen 失败
- **THEN** 流程 INFO 留痕后静默退出，不 raise、不重派、不改状态

### Requirement: frozen 文案匹配常量同源
frozen 拦截的 error 匹配 SHALL 使用 `runner.py` 导出的共享常量，MUST NOT 在 verification.py 内硬编码字面量（防文案改动致匹配失效）；取消判定沿用 `cancelled` 结构化字段，不依赖字符串匹配。

#### Scenario: 常量双侧引用
- **WHEN** 审阅 `runner.py` frozen 门与 `verification.py` 匹配处
- **THEN** 两处引用同一常量定义，无重复字面量
