# Design: escalation-endpoint-loop-suppression

## Context

升级链（add-escalation-chain-admin-arbiter 落地）的链终点件经 core/pm_engine/family.py `_send_human_escalation_alert`（:1964）落告警；该函数的直派段（约 :2154-2180）在 store.append 成功后调用 yielded_to_arbiter（本模块 :64-99——原 adjudication_narrative.narrative_yielded_to_arbiter 随 consolidate-alerts-to-ops-page 1.1 模块退役迁入）判定并直派 Arbiter。yielded_to_arbiter 只判 chain_active 与黑名单，不感知「本件已是链终点」；ArbiterLane.submit_for_alert（core/pm_engine/arbiter.py:621-635）入口只查 enabled/黑名单/preflight/同签名在飞/复现配额。链终点注入点 escalation_chain.py `_endpoint_escalate`（:1898-1972）携 chain_context 调用咽喉，正好落入直派段形成自环。

## Goals / Non-Goals

- Goals：链终点件不产生新的 arbiter 触发；入口第二道防线；不误伤回落兜底件；保留台账与告警面行为。
- Non-Goals：不改升级告警生成条件与裁决包内容；不改 arbiter_rulings 配额语义；不改链头防自环（chain_context is None 分支）；不动存量回扫通道（arbiter.py:778-856 `_backlog_candidates`/`sweep_backlog`——其按 add-escalation-chain-admin-arbiter 3.3 配额制对 frozen+pending 告警跨重启重扫属既定重试语义，且经 submit_trigger 直调不经过 submit_for_alert，两条守卫均不触碰）。

## Design

1. **咽喉守卫（core/pm_engine/family.py 直派段，约 :2154-2180）**：直派 if 块增加条件——chain_context 非空（链终点件）时跳过 submit_for_alert；零后台补叙（叙事生成链已随 consolidate-alerts-to-ops-page 1.2 退役，现状无 narrative 派发面可保留）。变量已在作用域内，改动为单分支。
2. **入口守卫（core/pm_engine/arbiter.py:621-635）**：submit_for_alert 开头检测 entry.get("chain") 存在即记录跳过日志并短路，返回既有否定哨兵字符串 `"excluded"`（函数签名为 `-> str`；调用方 family.py:2181-2188 的日志词表 `(None, "disabled", "excluded")` 对其静默后缀，避免告警日志渲染出 `arbiter: False` 误导排障）。作为防未来调用点绕过咽喉的第二道防线。
3. **日志可观测**：两处守卫各打一条 INFO（含签名与 alert id），便于统计「被抑制的自环」。
4. **测试**：单测模拟链终点件走完 _send_human_escalation_alert 全流程断言无 submit_for_alert 调用；模拟回落兜底件（chain_context=None）断言直派不受影响；模拟入口直调含 chain 字段 entry 断言短路。

## Risks / Trade-offs

- 链终点件本应由人工消费，跳过直派后若无人工消费面会滞留——现状告警面（admin_alerts）即人工消费入口，行为不变。
- 入口守卫按 entry['chain'] 判定，若未来合法需要「带链上下文直派」场景（目前不存在）需显式白名单参数。

## Migration

无数据迁移；行为变更仅影响「升级后回派」这一路径，即时生效。