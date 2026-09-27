<!-- knowledge: capability=fail-counter-budget rev=2 sources=spec/archive/2026-09-06-add-fail-counter-budget,spec/archive/2026-09-07-fix-budget-counting-semantics -->

# 验证失败计数与实现尝试预算

以验证失败计数与实现 run 启动次数双重口径约束单 SPEC 的自动重试规模：预算只被真实失败消耗，不被伪失败与异常死亡烧尽。

## 现行规则

- 验证失败计数 `_verify_fail_rounds` 仅在验证裁决 PASS（推进 verified/done 路径）时归零并持久化；原地打回重派、修复轮完成、实现收工等任何中间转换均不归零。
- 实现尝试总预算：统计每 spec 跨修复周期的实现 run 启动次数（`_impl_run_budget_used`），达到有效预算（全局 `agents.impl_run_budget`，缺省 4，范围 1-10；可被 per-spec 覆盖）时状态置 blocked，并发 human-escalation-alerts 告警（含 spec、已耗次数、最近一次失败摘要），不再自动重派。该配置键在 Dashboard 配置页可编辑，保存走既有配置热更新链路。
- 计数语义：run 正常收工时计数生效（成功走收工 merge 路径、失败走失败收工路径均计数，验证打回不回退）；run 异常死亡（进程消失、零输出、网关链路耗尽，无收工结果产出）时回退本次启动的计数增量（`used -= 1`，下限 0），并递增 `_budget_exempt_runs` 侧车留审计日志；侧车达到阈值（6）时发一次提醒级告警（含 spec 与死亡次数，不冻结 spec）。
- 计数持久化原子性：`_impl_run_budget_used` 的读改写经 state_machine 单点原子更新（复用既有文件锁），写入后回读校验，不匹配时重试一次并记审计日志；恢复扫描与派发并发更新不丢计数。

## 溯源

- 史前复原 — 迁移期基线：验证失败计数驱动实现尝试预算，防预算被伪失败烧尽
- 2026-09-06 add-fail-counter-budget — 确立 PASS 才归零的失败计数、跨修复周期累计的实现尝试总预算与配置页编辑界面
- 2026-09-07 fix-budget-counting-semantics — 计数语义修正：死亡 run 豁免计数并回退增量、`_budget_exempt_runs` 侧车阈值告警、计数经文件锁原子化持久化
