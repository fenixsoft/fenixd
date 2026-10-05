## Context

2026-10-06 核查锚点：core/verify_engine/engine.py `_execute_parallel`（369-480，Semaphore(5) 缺省、批调度）；core/verify_engine/scenarios.py TestScenario（1060-1090，from_dict 忽略未知键、字段扩展有 viewport 先例）；豁免原文在 spec/changes/pack2-official-encoder/verification-report.md 第 58/59 行；88.95s 重跑输出在 planner-judge-…-1791208179-a1.jsonl（裁决 agent 手工）。层级边界：single-flight（编排层派发单飞）与 parallel-override-type（车道类型）不与本条重叠。测试范本：tests/test_verify_parallel_backoff.py。frozen 场景集：test_scenarios.json 与 _scenarios_full.json 须同覆盖。

## Goals / Non-Goals

- [x] resource_group 字段 + 同组在飞互斥 + 豁免并行上下文要求
- [ ] 不做自适应调度；不做 flaky 自动重跑；不动编排层单飞

## Technical Design

1. scenarios.py：TestScenario 增加可选 `resource_group: str = ""`，from_dict/to_dict 透传（viewport 先例）；评估 SCHEMA_VERSION/CONTRACT_VERSION 是否随字段递增（向下兼容：未知键已忽略，老引擎读新文件安全）。
2. engine.py `_execute_parallel`：批内调度时按 resource_group 做在飞互斥（同组 defer 到下一批）；批日志与报告附互斥等待标记、effective_parallel 实测值。
3. core/agent_runner/prompt_builder.py：场景 schema 文档段注册 resource_group 词表（权威源 scenarios.py，防词表幻觉）；flaky 分类提示词要求豁免附同窗并行场景清单。
4. 防护：互斥仅在组内生效、空组零开销；defer 只挪批不改判失败归因（等待不计入场景超时）。

## Open Questions

- 全局重 IO 并行上限（todo 的「同时最多 1 个」）是否需要——首版仅组互斥，若 batch 内重 IO 组不止一个再评估全局闸。