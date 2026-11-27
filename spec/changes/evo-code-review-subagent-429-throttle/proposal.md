# 提案：审查子代理 429 节流与退避

## 背景

fenix-desktop 项目全仓审查车道连续两晚（2026-11-24、11-25 凌晨）发生同签名故障：首波并发派发的审查子代理 2 个秒死于账户级 429 限流（bigmodel 错误码 1302），约 5-7 分钟后重派再死 1 个，两晚各死 3 个子代理（code-review-1795539765 subagent_stats spawned=5/failed=3；code-review-1795453496 spawned=6/failed=3），单 run 成本被推高到 19.42/20.48 美元。死亡分片迫使 run 主体降速等待、重派甚至亲自接管补审（11-25 run 自述从并发派发一路降级到全自行逐文件审查）。另核实 fenixd 项目自身的全仓审查 run 两晚窗口与 fenix-desktop 审查全程重叠、共享同一 bigmodel 账户——账户级 1302 是跨项目共享容量。

## 问题

1. 派发契约对 429 无处置规则：agents/code-review.md 仅 :39 在飞上限条款（缺省 4），全文无 429 记忆、退避、止损条款。子代理死亡只产生 task_notification failed，交由 run 主体自由裁量——11-25 run 中 b2 死后仍继续派发 b3/b4，重派 b1 再死才被迫切自审。
2. 框架既有 429 防线全在 run 终态/provider 级（provider_circuit 冷却与重置解析、RATELIMIT_REDISPATCH_MAX、终态 ratelimit_redispatch 意图消费、error 收场抢救），无一作用于 run 内子代理扇出。
3. 在飞上限缺省 4 超过账户实际承受力：两晚死亡时在飞峰值仅 3，叠加跨项目审查窗口重叠，单 run 降并发仍可能不够。
4. 连续秒死零告警：两晚 run 均 terminal_reason=completed 正常收场，admin_alerts.json 零条 429 相关告警，故障只在事后自省才被发现。

## 目标

- 派发契约内建 429 记忆与止损：收到 429 后降并发不恢复、指数退避重派、连续秒死即停派转自审并留终态标记。
- 在飞上限缺省降为 2（配置键 verify.repo_code_review_concurrency 保持可覆盖，已显式配置的项目不受影响）。
- 429 风暴可见：终态标记被框架消费产生 admin 告警，提示检查同账户并发（含跨项目审查窗口重叠错峰）。

## 非目标

- 跨项目审查排程协调机制（本次仅以告警提示错峰，不做排程系统）。
- provider 级冷却与限额重置时间解析（已由 provider_circuit 与 evo-quota-reset-dispatch-freeze 覆盖）。