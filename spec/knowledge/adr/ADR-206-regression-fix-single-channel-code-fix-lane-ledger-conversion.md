# ADR-206：回归问题修复复用 code-fix 车道单通道——快照到台账条目的转换在消费端，禁独立修复车道与前端台账写路径

date: 2026-10-03
status: accepted

## Context

测试回归车道产出异常用例快照但无修复入口，而 code-fix 车道已有成熟的「台账→批派 worktree→批验证回归→失败自愈」机制。接入有两个备选：前端读快照直接转换并上传台账条目；或为回归建一条独立修复车道（重做批派/验证/自愈）。同时台账 `upsert_findings` 的 upsert 语义（不覆盖 status/first_seen_at）与 `checkpoint` 全部守卫是跨来源共享契约，任何接入方式都不得为单一来源改动它们；整体超时异常无逐用例 file 定位，而台账 upsert 硬性拒绝无 file 的发现。

## Decision

- 回归问题接入修复链走单通道：daemon 消费端读快照 → 转换为 code-fix 台账 findings → `upsert_findings` 入账 → `checkpoint(override_enabled=True)`。快照读取与转换属服务端职责，前端不持台账写路径；MUST NOT 为回归建独立修复车道或重做批派/验证/自愈。
- 台账共享契约对回归来源零改动；回归条目以 `regression-` category 前缀隔离标识，复发重开语义仅限此前缀条目，MUST NOT 自动重开 code-review 来源条目。
- 消费端读快照以当下为准、不与信号锁定：读不到/损坏即落 `snapshot_missing` 结果，不重试不排队，信号不内联快照副本（单快照语义下重按成本≈0，复制大 JSON 无收益）。
- 转换入账与派发解耦：`checkpoint` 拒绝（如 `already_running`）不回滚已入账条目，由在飞链下一批 `select_batch` 按 first_seen_at 自然吸收；回滚反而制造「条目消失、触发失败」假象。
- 整体超时条目的 file 锚点取 `.fenix/verify.yaml`（回归硬超时声明的真实落点，处置入口恰是查套件性能或超时配置），以真实存在文件为锚点，MUST NOT 伪造用例路径。

## Consequences

- 修复机制单份维护：批派/验证/自愈/进度展示零重复实现，回归条目自然获得既有批失败语义与自愈兜底；代价是回归条目混入共享台账，靠 `regression-` 前缀隔离标识与台账 UI category 标签消化，统计口径不得按 category 硬编码断言。
- 消费时点与触发时点的快照可能不一致（被新一轮回归覆盖或清理），以「当下为准 + snapshot_missing 如实回链」接受该漂移，不引入快照版本化。
- 后续任何「新问题来源接入自动修复」SPEC 的实现空间被约束为同一形态：消费端转换入账 + override 授权派发，不再评估独立车道方案。
