# judge 裁决原地修复写场景文件后强制 validate_scenario_dicts 同门校验 + _scenarios_full.json 成对同步

## Why

本次直接根因：planner-judge 原地修复协议直改 test_scenarios.json 绕过写端门，一词表违规步骤（run 入 api 场景）+ 成对撕裂 + 端口漂移潜伏 2 轮才被验收拦住，连带烧掉 impl 修复轮与 admin 处置轮。成对写回与结构校验基建均已存在（_exec_revise_scenario_reverify 内置同款），只需让 judge 原地修复写回路径复用同一门（写后校验失败即拒收本轮修复+按既有打回语义处理），即可在落盘瞬间拦截而非两轮后验收期发现。

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
- 立项时间：2026-11-03T11:31:05.781961+00:00
