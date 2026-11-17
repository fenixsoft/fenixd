# ADR-376：链终点回派抑制双防线——判据单源链上下文在场

date: 2026-11-17
status: accepted

## Context

升级链的终点件（Arbiter 产出的裁决包升级告警）经升级咽喉 `_send_human_escalation_alert`（core/pm_engine/family.py）落告警后，咽喉的直派段在 store.append 成功后经 `yielded_to_arbiter`（同模块）判定为真即无条件 `submit_for_alert` 回派 Arbiter 车道。`yielded_to_arbiter` 只判链可用与黑名单，不感知「本件已是链终点」；而链终点注入点 `EscalationChain._endpoint_escalate`（core/pm_engine/escalation_chain.py）携 chain_context 调用咽喉，恰好落入直派段形成自环。后果已量化：Arbiter 每次升级多派一轮同证据调查（实测单轮约 200–450s、10–15 万 tokens），唯一停止机制是 arbiter_rulings 复现配额耗尽（缺省 3）；车道入口 `ArbiterLane.submit_for_alert`（core/pm_engine/arbiter.py）只查 enabled/黑名单/preflight/同签名在飞/复现配额，无链终点去重，日志面已见 9 个不同签名被回派。

## Decision

链终点件消费归属人工裁决面（admin_alerts），升级件语义=「给人类的裁决包」，自动化车道对其实施双防线抑制，判据单源为**链上下文在场**（chain_context 非空 / entry 含 `chain` 字段）：

1. **咽喉守卫**：升级咽喉直派段对链上下文在场的链终点件跳过 `submit_for_alert`，零后台补叙（告警以机械文案落盘）；
2. **入口短路**：`ArbiterLane.submit_for_alert` 入口检测 entry 含 `chain` 字段即记录跳过日志并短路，返回既有否定哨兵字符串 `"excluded"`——调用方日志词表 `(None, "disabled", "excluded")` 对其静默，告警日志不渲染 `arbiter: False` 误导排障；作为防未来新调用点绕过咽喉的第二道防线。

豁免面固定两类：链队列满回落兜底件（chain_context=None、entry 无 chain 字段）按既有直派逻辑正常处理；存量回扫通道（frozen+pending 告警跨重启重扫，`submit_trigger` 直调不经 `submit_for_alert`）不受守卫触碰。未来若出现合法的「带链上下文直派」场景（当前不存在），必须以显式白名单参数声明，不得删除守卫或另造判据。

## Consequences

- 自环回派不再消耗复现配额：arbiter_rulings 配额回归「真实多次升级裁决深度」语义，不再被设计外自环兜底为唯一停止机制；同签名新证据的真实升级件在配额内照常获得裁决。
- 双守卫点成为升级面契约：任何新增 `submit_for_alert` 调用点若携带 chain 字段将被短路（两处守卫各打含签名与 alert id 的 INFO 日志，「被抑制的自环」可统计）；排障时「升级件未入 Arbiter」优先查抑制日志而非车道故障。
- 判据若变更须两处同改（咽喉直派段条件与入口 entry['chain'] 检测）；两处判据不一致时入口短路兜底生效，行为仍 fail-safe（宁不派发不回派）。
