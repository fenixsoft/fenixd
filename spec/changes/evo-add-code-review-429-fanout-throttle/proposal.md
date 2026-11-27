# Proposal: code-review-429-fanout-throttle

## Why

审查/修复 run 的子代理并发上限是纯文本契约（agents/code-review.md:39「同时在飞 ≤4」，缺省值出自 core/config.py get_repo_code_review_concurrency=4，经 core/agent_runner/maintenance_runs.py 注入段进提示词），框架代码既不校验在飞数，也无任何 429 感知：全部既有 429 防线（provider 300 秒冷却、终态重派登记、error 收场抢救、分片续跑）都要等 run 死掉才生效。账户级 429 事故已三次在案：

- 2026-09-24：子代理 6+5 两波并发打死 provider 账号，43 分钟致整 run 429（契约文本自载）。
- code-review-1790574672：218 轮全仓审查死于账户级 429，重派全量重烧约 14 美元（core/code_review.py:268-272 注释自载）。
- 2026-11-24 code-review-1795453496：按缺省 4 并发派发，2 分钟内 b2/b3 死于 429（错误码 1302 账户级限流），重派 b2 时契约无记忆再死一次；run 成本 $20.48 对前日同型 $16.00（1.28×），缓存读 27.4M 对 13.05M（2.10×），6 子代理 3 死 1 杀。

已归档的 add-code-review-concurrency-and-429-resilience（2026-09-30 批次）落的是静态上限与死后冷却/重派，阈值静态且无记忆，问题在其归档后仍复发。本 SPEC 补它明确不覆盖的「事前/事中」面。

## What Changes

- **缺省在飞上限 4 → 2**：core/config.py 读器缺省值与 .fenix/config.template.yaml 模板值同步下调（模板注释约束：示例值必须等于缺省值）；已显式配置的项目不受影响。
- **429 记忆降档**：run 启动注入 repo_concurrency 时，若上一轮同车道 run 的归档 jsonl 存在 429 终态子代理死亡，则本次契约上限折减至 1；审查与修复两个契约模板追加 run 内记忆条款——本 run 内一旦出现 429 子代理死亡，后续波次在飞上限不得回升、重派前间隔 ≥60 秒（同 run 第二次 429 后 ≥180 秒），违反沿既有「违反 = run 判失败」语义。
- **连续 429 死亡升级告警**：run 收尾段扫描本 run jsonl 统计 429 终态子代理死亡数，≥3 时经 AdminStore.append_if_absent 直写单条告警（新 signal_type，dedup_key 含 run id），替代静默重试。

## 不做什么（Non-Goals）

- 不触 provider_circuit / run 级派发冷却——该层由在途 evo-quota-reset-dispatch-freeze 负责（「该不该派这个 run」）；本 SPEC 只管扇出层（「run 内派多少子代理」），不做 per-provider 429 时点持久化记忆，避免两层重复建设。
- 不改动既有死后抢救路径（分片续跑、error 收场抢救、重派上限 1）。

## Capabilities

### code-review-dispatch

见 specs/code-review-dispatch/spec.md。

## Impact

- core/config.py、.fenix/config.template.yaml：缺省与模板值同步降为 2。
- agents/code-review.md、agents/code-fix.md：契约文本追加 429 记忆条款。
- core/agent_runner/maintenance_runs.py：注入段（:3049-3063 附近）叠加跨 run 记忆折减；收尾/终态归因段（:3611-3648 或 :3512 分支附近）新增 429 死亡计数与告警直写。
- tests/test_code_review.py：覆盖降档、记忆折减、告警阈值。
