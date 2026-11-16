# ADR-358：确定性 spawn 缺件失败一跳终态——不重试不升级，预算走既有 infra 退款通道

date: 2026-11-16
status: accepted

## Context

环境缺件（claude 不在 PATH）类 spawn 失败被按瞬时故障处置：确定性失败走完整 fast-track 3 轮重试 → 冻结 → arbiter 升级，而 arbiter 车道同根因秒挂——三连烧且 STATE error 不带根因。部署态环境缺件不会秒级自愈，重试每一轮都是纯烧钱；失败分类机制里缺「确定性失败」这一型（ADR-127 的三态记账管 run 启动后的 infra/product/env，不覆盖「run 未启动即死」形态）。

## Decision

- spawn 阶段 `FileNotFoundError`（errno ∈ {2,3}）归类 infra-deterministic：第一跳终态——不进重试队列、不重派、不触发同因熔断冻结与 arbiter 升级。
- 预算净效果零消耗：run 启动照常记账，分类可知后退款走既有 `_exempt_infra_run_budget` infra 补偿通道（按 run_id 幂等退款），不新增记账时点——与 ADR-127「记账在启动、补偿在收尾」范式对齐。
- 终态 error MUST 带根因与修复指引：错误文案以 `[infra-deterministic]` 前缀单源标记，dispatch 读侧按标记路由终态分支；run 失败归因三型分立 spawn_failed / nonzero_exit / result_missing，result_missing 附 run 转录 stderr 尾窗（截尾 2KB）取证，防归因断链。
- 判定集单点扩展：后续新的确定性失败类型在统一失败建模（failure_model）扩判定与文案，车道侧只消费标记做终态路由，禁止在车道内散落特判。

## Consequences

- 缺件环境下一跳产出可执行的修复指引，不再烧重试链与升级链；误判代价可控——进程表缺件不会自愈，人工补齐环境后重派即恢复。
- fast-track 与常规实现车道为双消费点，新增车道接入时 infra-deterministic 终态分支是必接面。
- 与 ADR-183 分工：同因重派治理管「归因之后禁重派」，本裁定在 spawn 层第一跳即终态、无重派入口；与 ADR-127 分工：本裁定管确定性缺件的前缀标记路由，ADR-127 管 run 启动后失败的三态记账分层。
