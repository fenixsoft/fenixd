# Proposal: env-attribution-evidence-gate

## Why

2026-11-08 cloud-phone 项目 `client-ux-and-input-latency` 的 regression-matrix-12-combos 争议中，judge（评审 agent）仅凭两轮同窗自测 fps（37.4/38.6）就把失败归因为 env「swiftshader 软渲染确定性天花板」并 accept 入档 judge_attribution.json（2026-11-08T20:47:56Z）。而同一晚 20:17（git 07a7ee6）同宿主 1080p 刚以 51.8~59.1 fps 重跑 12/12 PASS，负载采样显示 load1 5.07~17.60 波动期间该组合 fps 恒定 36.2~37.5——judge 的 env 结论没有任何窗口外对照样本支撑。该归因随后驱动豁免握手，触发 warning_stale_triage 两波升级与 judge_rerun_cap（6/5）二次冻结，链上烧掉 judge/admin/arbiter 至少 5 段 run，最终仍需人工收口，且该场景以 env-accept 进终态（env 误判把真问题以环境豁免放行的风险实际兑现）。

框架侧根因（已回源核实）：

1. env 归因的接受条件仅为「evidence 非空」——core/agent_runner/prompt_builder.py:3247 `_scenario_classified`（词表 :3242），对 evidence 内容无任何校验。
2. judge 提示词模板 agents/planner-judge.md:65-66 对 env 的定义纯定性，未要求引用可复核的环境量测（负载/CPU/温度/驱动版本）或验证窗口外的对照样本。
3. 既有 inconclusive 降级机制（core/alert_lifecycle.py:89,164、core/event_bus.py:433 `_handle_env_blocked_inconclusive`）只由 env-blocked 握手驱动，不校验 env 归因的证据质量——「无对照的 env 结论」不会降级，直接进豁免握手。

## What Changes

- **judge 提示词（agents/planner-judge.md）**：env 定义改为「必须引用可复核的环境量测（负载/CPU/温度/驱动版本等具体数值与来源）+ 验证窗口外的对照样本」，明确无对照不得判 env。
- **归因接受门（core/agent_runner/prompt_builder.py `_scenario_classified`）**：env 归因的 accept 分支加证据校验——evidence 须含环境量测数值与对照样本引用，缺失时不落 accept，改产 inconclusive 归因。
- **归因产物 schema（core/verify_engine/judge_files.py）**：judge_attribution.json 增补量测引用与对照样本字段；accept 条目缺字段时标记 inconclusive。
- **降级接线**：inconclusive 归因接入既有 inconclusive_loop/recheck 通道（core/alert_lifecycle.py、core/event_bus.py 已有路径），不进豁免握手。

## Capabilities

### judge-env-attribution

见 specs/judge-env-attribution/spec.md。

## Impact

- 影响 core/agent_runner/prompt_builder.py 的场景归因分类逻辑（env accept 分支）与 judge 产物消费方。
- 影响 agents/planner-judge.md 提示词模板（所有使用 judge 归因的验证链）。
- judge_attribution.json schema 变更向后兼容：新增字段可选读取，旧文件不受影响。
- 不改变 env-blocked 握手语义本身，只在其上游加证据门。