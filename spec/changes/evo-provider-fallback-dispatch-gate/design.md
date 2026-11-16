# Design: provider-fallback-dispatch-gate

## Context

已落地（harden-arbiter-lane-resilience）：lane_preflight.py probe② 凭据路由本地解析（显式链）、arbiter 前置闸 _preflight_gate（含版本白名单）、单发告警、infra 失效分级。残余缺口：probe② 对「未分配显式链」角色明文跳过；回落留痕在 harness/__init__.py:267-294（一次性 WARNING，D3 裁定仅留痕）；版本白名单拦截在 runner.py:3631 _execute_agent 前置段，直调车道（spec-review/dispute-judge）被连通预检白名单排除。事故：11-09 两波回落形态秒挂 ≥23 run。

## Goals / Non-Goals

- Goals：回落角色可判、首派发冻结、单条告警；版本拦截全车道一致。
- Non-Goals：不禁止回落本身（配置补齐后角色自动恢复）；不改显式链探针与 arbiter 前置闸（已落地）；不改 300s 冷却/秒挂计数/死人开关语义；不做自动凭据补齐。

## Design

1. **探针②扩展（lane_preflight.py）**：角色无显式链时，解析 harness 默认配置的 provider 路由并做与显式链相同的凭据可判定检查；结果带 fallback=true 标记输出；解析失败输出「不可判定」而非跳过。
2. **派发闸（runner.py）**：角色级回落冻结状态由探针结果驱动（进程内即可，无需持久化）；冻结期首派发拦截并维护单条告警（复用 harden 的单发告警通路），显式链角色旁路。配置热重载使默认链凭据变为可用时解除冻结。
3. **版本白名单车道扩大（runner.py）**：把 spec-review/dispute-judge 直调车道纳入既有白名单检查（检查逻辑复用，不新写）；连通预检白名单的 dispatch 族排除项同步移除。
4. **D3 裁定修订留痕**：回落拦截仅在「默认链凭据不可判定/缺失」时触发——回落到可用链仍合法（保留 D3 的合法回落语义），仅阻断「注定死亡的回落」。
5. **测试**：单测覆盖回落冻结与告警单条、显式链不误伤、热重载解冻、直调车道版本拦截。

## Risks / Trade-offs

- 「凭据可判定」判断依赖本地配置形态（env/config），极端形态可能误判不可用——误判后果是拦截+告警（人工可立即放行），优于静默秒挂；提供显式放行配置项兜底。
- 直调车道纳入版本拦截会改变其失败形态（从 spawn 死亡变为预检拒绝）——这正是目标行为，日志与告警面更早更便宜。

## Migration

无数据迁移；探针与闸门即时生效于新派发。