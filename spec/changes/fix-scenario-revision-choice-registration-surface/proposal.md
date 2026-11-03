# revise_scenario_reverify 裁决选项注册面扩展到场景争议信号类

## Why

spec 作用域动作 revise_scenario_reverify 仅注册于 inconclusive_loop 裁决桶；场景计划争议信号（verify_env_blocked 及其 manual-intervention 派生形态）未注册该选项且 fail-closed 拒绝跨信号全表反查，导致 admin 手握机械校验零错误的合规修复集却被通道拒收（本例第 1 轮处置未奏效的直接机制，10-30 已有同型先例）。建议：在该类信号上注册 revise_scenario_reverify 白名单（限定「冻结场景文件损坏/验收失败」类差异可执行，维持 fail-closed 不开全表反查），与 10-31 已归档的 fix-admin-choice-payload-and-scenario-pairing（payload 传输面）互补成完整通道。

## What Changes

- （arbiter 提案待人工成文：本文件为调查报告提案的最小诚实成文，补全 What Changes / Capabilities / Impact 后走既有晋升流程）

## Capabilities

### New Capabilities

- `<capability>`: （待成文）

### Modified Capabilities

（无）

## Impact

（待成文）

---

- 立项来源：Arbiter 调查（run_id=None，signature=add-knowledge-inbox-pipeline::verify_env_blocked，source=startup）
- 立项时间：2026-11-03T13:25:51.758600+00:00
