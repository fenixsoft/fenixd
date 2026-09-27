# ADR-017：假成功防御——晋级关 fail-closed、推送关 fail-open

date: 2026-09-02
status: accepted

## Context

Claude CLI 可能把 API 错误包装成正常终止的 result 事件且 exit code 为 0：仅凭 rc==0 判成功会把失败 run 当成功晋级。同时「验证不完整却晋级/推送」与「verified 状态无回退出口导致死锁」暴露出：状态推进各关口的重试成本不同，失败处理语义不能一刀切。

## Decision

- exit code 0 不构成成功：run 结束时须解析末个 result 事件的 `is_error` 与 `subtype`（如 `error_during_execution`），非成功即按失败处理（记录错误并抛出）；该检查对字段缺失时维持原行为，向后兼容。
- 晋级关 fail-closed：verifier 判定成功后、执行 `testing→verified` 前，核对验证进度文件（`done >= total`）；不完整、文件缺失或损坏一律按 verifier 失败处理（走既有 attempt 重试），绝不晋级，并把进度摘要写入 error 字段。此关口拥有最新现场、重试成本低，故宁可拦截。
- 推送关 fail-open：`verified→done` 的放行门禁对「无证据可查」的情形放行，不因缺证据卡死流程——此关口重试成本高，交由人工在审批入口裁决。两处语义不同是设计边界而非疏漏：验证报告快照不回流，推送侧不做二次机械校验。
- 终态必须有回退出口：状态机为门禁触发的自动回退保留 `VERIFIED→TESTING` 转换，回退时保留 run 历史字段与验证进度断点；该出口仅限门禁自动回退路径使用，人工操作不得绕过常规转换约束。

## Consequences

- 假成功（rc==0 包装失败、验证未完即晋级）在各自关口被识破，晋级与推送的可信度由机制而非 agent 自述保证。
- fail-closed 关口的代价是可能多跑重试轮次；fail-open 关口的代价是漏检依赖人工——两者不可互换，新增状态推进关口时必须显式声明其语义归属。
- 回退出口被限定在自动路径，防止其沦为随意回退通道；无出口的终态即无自愈，新增终态时须同步裁定是否存在回退转换。
