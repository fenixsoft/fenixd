# Proposal: provider-fallback-dispatch-gate

## Why

2026-11-09 两波车道级秒挂暴露派发预检的残余缺口。已落地的 harden-arbiter-lane-resilience（lane_preflight.py probe② 凭据探针 + arbiter 前置闸）覆盖了显式 provider 链的角色，但其探针明文跳过「未分配显式链」的角色（「本地无可判凭据，跳过不报」）——而事故两波恰恰都是回落形态：11-09 01:01Z arbiter 角色回落 harness 默认（无 key 的 deepseek 路由）后 8 个 run 死亡、07:45Z repair 角色同形态三连秒挂、08:05Z p2p 再演，全天 ≥23 个 run 零产出死亡、7 次死人开关触发。回落路径当前只有一次性 WARNING 留痕（harness/__init__.py:267-294，进程×adapter 粒度），「仅留痕不拦派发」是 add-harness-default-key-fallback D3 的设计裁定——本 SPEC 修订该裁定：回落不再静默。

第二个残余缺口：dsh 版本白名单拦截只在 core/agent_runner/runner.py:3631 的 _execute_agent 前置段生效，spec-review/dispute-judge 直调车道被连通预检白名单明文排除（dispatch 族），01:03Z spec-review-gaming-uplink-1080p 三条 run 在已被拦截的车道旁边照样死于 bundle 插件不兼容——同一版本漂移对不同车道两种命运。

## What Changes

- **回落角色凭据可判定（core/agent_runner/lane_preflight.py）**：probe② 不再跳过「未分配显式链」的角色，对回落 harness-default 的角色按默认链做凭据可判定性检查，无法判定时输出明确探针结果而非静默跳过。
- **回落首派发冻结（core/agent_runner/runner.py）**：回落形态的角色首个派发前拦截并发出单条告警（含角色与回落链），替代「仅 WARNING 留痕」；显式链角色行为不变。
- **版本白名单全车道（core/agent_runner/runner.py）**：版本白名单拦截覆盖 spec-review/dispute-judge 直调车道（连通预检白名单不再排除），arbiter 前置闸已覆盖项保持。
- **单测**：覆盖回落冻结、显式链不误伤、直调车道版本拦截。

## Capabilities

### dispatch-preflight-coverage

见 specs/dispatch-preflight-coverage/spec.md。

## Impact

- core/agent_runner/lane_preflight.py 探针②扩展一个分支（回落角色）。
- core/agent_runner/runner.py 派发前置段增加角色级回落冻结检查；版本白名单的适用车道集合扩大。
- 与 harden-arbiter-lane-resilience 的已落地闸互补（它管显式链与 arbiter 车道，本 SPEC 管回落角色与直调车道）；不改变 300s 冷却与秒挂计数语义。