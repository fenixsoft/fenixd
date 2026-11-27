# Proposal: code-review-429-fanout-throttle

## Why

审查/修复 run 的子代理并发上限是纯文本契约（agents/code-review.md:39「同时在飞 ≤4」，缺省值出自 core/config.py get_repo_code_review_concurrency=4，经 core/agent_runner/maintenance_runs.py 注入段进提示词），框架代码既不校验在飞数，也无任何 429 感知：全部既有 429 防线（provider 300 秒冷却、终态重派登记、error 收场抢救、分片续跑）都要等 run 死掉才生效。账户级 429 事故已三次在案：

- 2026-09-24：子代理 6+5 两波并发打死 provider 账号，43 分钟致整 run 429（契约文本自载）。
- code-review-1790574672：218 轮全仓审查死于账户级 429，重派全量重烧约 14 美元（core/code_review.py:268-272 注释自载）。
- 2026-11-24 code-review-1795453496：按缺省 4 并发派发，2 分钟内 b2/b3 死于 429（错误码 1302 账户级限流），重派 b2 时契约无记忆再死一次；run 成本 $20.48 对前日同型 $16.00（1.28×），缓存读 27.4M 对 13.05M（2.10×），6 子代理 3 死 1 杀。

已归档的 add-code-review-concurrency-and-429-resilience（2026-09-30 批次）落的是静态上限与死后冷却/重派，阈值静态且无记忆，问题在其归档后仍复发。本 SPEC 补它明确不覆盖的「事前/事中」面。

## What Changes

- **缺省在飞上限 4 → 2**：core/config.py 读器缺省值与 .fenix/config.template.yaml 模板值同步下调（模板注释约束：示例值必须等于缺省值）；已显式配置的项目不受影响。缺省同源面共三处，MUST 一致降为 2 才不留绕过/漂移：读器缺省、core/agent_runner/prompt_builder.py 注入段 fail-open 回退值（ConfigLoader 导入失败分支硬编码 4）、core/dashboard/static/src/pages/settings/components/QualityPanel.tsx REPO_REVIEW_DEFAULT_CONCURRENCY（注释明示与 ConfigLoader 缺省同源，空值回显与描述文案均消费）。
- **429 记忆降档**：run 启动注入 repo_concurrency 时，若上一轮同车道 run 的归档 jsonl 存在 429 终态子代理死亡，则本次契约上限折减至 1；审查与修复两个契约模板追加 run 内记忆条款——本 run 内一旦出现 429 子代理死亡，后续波次在飞上限不得回升、重派前间隔 ≥60 秒（同 run 第二次 429 后 ≥180 秒），违反沿既有「违反 = run 判失败」语义。
- **连续 429 死亡升级告警**：run 收尾段扫描本 run jsonl 统计 429 终态子代理死亡数，≥3 时经 AdminStore.append_if_absent 直写单条告警（新 signal_type，dedup_key 含 run id），替代静默重试。

## 不做什么（Non-Goals）

- 不触 provider_circuit / run 级派发冷却——该层由在途 evo-quota-reset-dispatch-freeze 负责（「该不该派这个 run」）；本 SPEC 只管扇出层（「run 内派多少子代理」），不做 per-provider 429 时点持久化记忆，避免两层重复建设。
- 不改动既有死后抢救路径（分片续跑、error 收场抢救、重派上限 1）。
- **一键两用副作用声明（接受面）**：repo_code_review_concurrency 同时是 `ocr scan --concurrency` 的缺省并行度（config.py 读器 docstring 与 config.template.yaml 注释均明示），缺省降为 2 对两通道同时生效；审查车道自身已不调用 ocr scan，其他车道可显式配置覆盖，接受此波及。
- **code-fix 车道静态降档不做**：code-fix 的在飞上限是独立分档链（core/code_fix.py wave_cap_for_groups，按文件组数分档 4/6/8），不在本 SPEC 缺省降档范围，仅追加 run 内 429 记忆条款。

## 与同题在途 SPEC 的边界

evo-code-review-subagent-429-throttle 是对本问题（11-24/11-25 两晚 429 事故）的第二次立项，与本 SPEC 同日并行评审。重叠面：config.py 读器缺省 4→2、agents/code-review.md 并行扇出上限条款处的 429 处置追加。互补面：本 SPEC 独有跨 run 记忆折减与 code-fix 车道记忆条款；该 SPEC 独有指数退避、连续秒死停派转自审、统计行标记解析告警。实现协调规则见 design.md「与同题 SPEC 的边界」——核心约束：退避规则 MUST 单段存在（MUST NOT 两套并存）、告警通道 MUST 二选一、缺省降档三处同源面先落地者为准后落地者幂等跳过。

## Capabilities

### code-review-dispatch

见 specs/code-review-dispatch/spec.md。

## Impact

- core/config.py、.fenix/config.template.yaml：缺省与模板值同步降为 2（docstring/注释内缺省值文案同步）。
- core/agent_runner/prompt_builder.py：注入段 fail-open 回退值 4 → 2（含 ConfigLoader 导入失败分支硬编码）。
- core/dashboard/static/src/pages/settings/components/QualityPanel.tsx：REPO_REVIEW_DEFAULT_CONCURRENCY 4 → 2（缺省同源）。
- agents/code-review.md、agents/code-fix.md：契约文本追加 429 记忆条款。
- core/agent_runner/maintenance_runs.py：注入段（:3049-3063 附近）叠加跨 run 记忆折减；收尾/终态归因段（:3611-3648 或 :3512 分支附近）新增 429 死亡计数与告警直写。
- tests/test_code_review.py：覆盖降档、记忆折减、告警阈值。
