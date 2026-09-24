# Requirement: spec 并发 run 状态守卫

> 全文「在飞评审 run」的判定口径见 `design.md` D0（`reviewer_run` 非空 + 进程表/流文件
> 分层判定；陈旧锚点判为无在飞评审）。

## Requirement 1: 审核收尾回退守卫

spec-review run 收口时（status 为 approved/repaired，即既有 `implementing→ready` /
`reviewing→ready` 回退路径），系统 MUST 在结果硬门与写入边界校验之后、执行回退之前重读
spec 当前 status：若已为 `implementing`、`implemented` 或 `testing`（存在在飞实现 run 或
已在实现后段），则 MUST NOT 回退到 ready，仅记录 in-flight 日志，并 MUST 清除
`reviewer_run` 锚点（残留锚点会阻塞后续派发）。跳过回退 = 该轮评审结论未被状态机消费，
MUST 以 `_` 前缀侧车字段留审计痕迹；MUST NOT 调用实现派发入口（无待派发实现 run）。

### Scenario: 评审收尾不再回退在飞实现

- **GIVEN** spec 当前 status=implementing（implementer 已派发）
- **WHEN** 在飞 spec-review run 收尾（repaired）
- **THEN** status 保持 implementing，不触发 implementing→ready；记录「评审收尾遇在飞实现 run，跳过回退」INFO 日志；`reviewer_run` 被清空、`_review_skipped_result` 落盘；MUST NOT 调用 `_on_spec_ready`

### Scenario: 非在飞状态回退行为不变（幂等）

- **GIVEN** spec 当前 status=reviewing（无在飞实现 run）
- **WHEN** in-flight spec-review run 收尾（approved/repaired）
- **THEN** 系统按既有路径执行 reviewing→ready 并触发实现派发，行为与本 SPEC 之前逐字一致

## Requirement 2: 派发前在飞评审校验

派发 implementer（含 fast-track）前，系统 MUST 校验同 spec 无在飞评审 run：存在时 MUST
顺延本次派发（不创建实现 run、不写 `error` 字段、不消耗实现尝试预算），待评审收尾事件
经既有 `_on_spec_ready` 重触发通道重判。该校验 MUST 同时覆盖**两处**派发入口——
`PMEngine._on_spec_ready` 与 dispatch 队列候选筛选（后者覆盖绕过前者的直入队列路径）——
MUST NOT 只覆盖其中一处。

### Scenario: 在飞评审时派发顺延

- **GIVEN** spec 处于 ready 且存在在飞 spec-review run
- **WHEN** 调度器尝试派发 implementer
- **THEN** 派发被顺延（不创建实现 run、不写 error 字段），待 review 收尾后经 `_on_spec_ready` 重判

### Scenario: 陈旧锚点不误拦（防自造死锁）

- **GIVEN** spec 处于 ready，`STATE.reviewer_run` 非空但其 run 已终态（无存活进程、流文件无新鲜写入或末行已终态）
- **WHEN** 调度器尝试派发 implementer
- **THEN** 系统 MUST 判为「无在飞评审」放行派发，并记 WARNING 留痕；MUST NOT 永久顺延

## Requirement 3: 合并收尾 ready 态兜底

实现 run 合并完成后推进状态时，若 spec 当前 status=ready（因评审收尾竞态被回退过），
系统 MUST 先补记合法转移 `ready→implementing`、再执行既有的 `implementing→implemented`；
严禁以 `ready→implemented` 非法转移报错。补记 MUST 留审计痕迹（WARNING 日志 + 项目日志），
MUST NOT 静默吞掉异常。

### Scenario: 兜底补记合法链

- **GIVEN** 实现 run 合并完成、spec 当前 status=ready（因竞态被回退过）
- **WHEN** 合并收尾推进 implemented
- **THEN** 系统自动执行 ready→implementing→implemented，不产生 Invalid transition ERROR，且留有补记审计痕迹

## Requirement 4: 非实现合并不触发兜底

ready 态兜底 MUST 仅由实现 run 的合并收尾路径调用（implementer / repair / fast-track 三条
落点），MUST NOT 由文档或管理操作合并触发。

### Scenario: 文档合并停留原状

- **GIVEN** spec 当前 status=ready，触发方为文档或管理操作合并（非实现 run 收尾）
- **WHEN** 合并完成
- **THEN** 系统 MUST NOT 补记 implementing，维持既有转移路径（非法转移仍被拒，暴露真实异常）
