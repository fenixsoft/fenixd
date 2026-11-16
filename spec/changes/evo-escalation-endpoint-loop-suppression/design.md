# Design: escalation-endpoint-loop-suppression

## Context

升级链（add-escalation-chain-admin-arbiter 落地）的链终点件经 core/pm_engine/family.py `_send_human_escalation_alert` 落告警；该函数的直派段在 store.append 成功后调用 narrative_yielded_to_arbiter 决定是否补叙并直派 Arbiter。narrative_yielded_to_arbiter（core/adjudication_narrative.py:82-117）只判 chain_active 与黑名单，不感知「本件已是链终点」；ArbiterLane.submit_for_alert（core/pm_engine/arbiter.py:550）入口只查 enabled/黑名单/preflight/同签名在飞/复现配额。链终点注入点 escalation_chain.py:1668-1677 携 chain_context 调用咽喉，正好落入直派段形成自环。

## Goals / Non-Goals

- Goals：链终点件不产生新的 arbiter 触发；入口第二道防线；不误伤回落兜底件；保留台账与告警面行为。
- Non-Goals：不改升级告警生成条件与裁决包内容；不改 arbiter_rulings 配额语义；不改链头防自环（chain_context is None 分支）。

## Design

1. **咽喉守卫（core/pm_engine/family.py 直派段，约 :1788-1832）**：直派 if 块增加条件——chain_context 非空（链终点件）时跳过 submit_for_alert；narrative 补叙按现有逻辑保留（链终点件降级为零补叙或仅 narrative）。变量已在作用域内，改动为单分支。
2. **入口守卫（core/pm_engine/arbiter.py:550-565）**：submit_for_alert 开头检测 entry.get("chain") 存在即记录跳过日志并返回 False；作为防未来调用点绕过咽喉的第二道防线。
3. **日志可观测**：两处守卫各打一条 INFO（含签名与 alert id），便于统计「被抑制的自环」。
4. **测试**：单测模拟链终点件走完 _send_human_escalation_alert 全流程断言无 submit_for_alert 调用；模拟回落兜底件（chain_context=None）断言直派不受影响；模拟入口直调含 chain 字段 entry 断言短路。

## Risks / Trade-offs

- 链终点件本应由人工消费，跳过直派后若无人工消费面会滞留——现状告警面（admin_alerts）即人工消费入口，行为不变。
- 入口守卫按 entry['chain'] 判定，若未来合法需要「带链上下文直派」场景（目前不存在）需显式白名单参数。

## Migration

无数据迁移；行为变更仅影响「升级后回派」这一路径，即时生效。