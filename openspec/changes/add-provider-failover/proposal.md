# Proposal: add-provider-failover

## Why

2026-08-27 实证 inferaiapi 与 aliyun 两网关在相邻时间窗同时返回 `unrecognized_model`（deepseek-v4-flash / deepseek-v4-flash-0731），导致 implementer/planner/verifier 全角色整批秒败、Administrator 处置链自身也受累；现有 agents.models 为单 provider 静态绑定，provider-fault-fuse 只对可解析 HTTP 4xx 计数，5xx/网络错误/unrecognized_model 不触发任何切换或告警，恢复完全依赖网关自愈与人工观察。

## What Changes

- **多 provider 链配置**：`agents.models.<role>.provider` 支持 `str | list[str]`；列表表示按序候选链，单值与既有行为完全兼容；启动校验报告未知 provider 名。
- **attempt 级 failover**：每次 attempt 派发选择链上首个未熔断 provider；失败的 provider 按"切换类错误"（unrecognized_model / 5xx / 网络错误）计入短冷却并在同 run 的后续 attempt 自动前进到下一候选；4xx 配额类错误沿用既有熔断语义不纳入切换链推进。
- **跨 provider 会话续跑**：claude 会话历史存储于本地 CLI，`--resume` 跨 baseurl 可用；provider 切换后 attempt 继续 resume 原会话，避免上下文重掷。
- **切换可观测**：AgentRunResult 与 run jsonl 记录实际使用的 provider/model；每次切换打点日志；提供 per-provider 当日 attempt 计数（防备Provider悄悄烧贵）。

## Capabilities

### New Capabilities
- `provider-chain-config`: 多 provider 候选链的配置解析、校验与兼容语义
- `failover-dispatch`: attempt 级候选链选择、切换类错误分类与冷却、跨 provider 会话续跑、切换可观测

### Modified Capabilities

<!-- 无 -->

## Impact

- **代码**：`.fenix/core/agent_runner.py`（_get_agent_model_assignment 返回链、attempt 循环选点、parse_api_error_status 扩展、AgentRunResult 字段）、`.fenix/core/config.py`（models 解析与校验）、`.fenix/core/provider_circuits` 复用为链级冷却表
- **配置**：agents.models.*.provider 变为可列表；新增 `pm.failover.switch_errors` 错误分类开关与 per-provider 每日计数上限告警键
- **测试**：config 解析兼容用例、错误分类矩阵（含今日真实报错文本 fixture）、attempt 切换模拟、resume 跨 provider 标记
