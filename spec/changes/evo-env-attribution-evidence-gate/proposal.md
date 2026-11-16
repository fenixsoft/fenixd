# Proposal: env-attribution-evidence-gate

## Why

2026-11-08 cloud-phone 项目 `client-ux-and-input-latency` 的 regression-matrix-12-combos 争议中，judge（评审 agent）仅凭两轮同窗自测 fps（37.4/38.6）就把失败归因为 env「swiftshader 软渲染确定性天花板」并 accept 入档 judge_attribution.json（2026-11-08T20:47:56Z）。而同一晚 20:17（git 07a7ee6）同宿主 1080p 刚以 51.8~59.1 fps 重跑 12/12 PASS，负载采样显示 load1 5.07~17.60 波动期间该组合 fps 恒定 36.2~37.5——judge 的 env 结论没有任何窗口外对照样本支撑。该归因随后驱动豁免握手，触发 warning_stale_triage 两波升级与 judge_rerun_cap（6/5）二次冻结，链上烧掉 judge/admin/arbiter 至少 5 段 run，最终仍需人工收口，且该场景以 env-accept 进终态（env 误判把真问题以环境豁免放行的风险实际兑现）。

框架侧根因（已回源核实）：

1. env 归因的接受条件仅为「evidence 非空」——core/agent_runner/prompt_builder.py:3303 `_scenario_classified`（词表 :3300）只校验 classification 词表与 evidence 非空；归因条目 accept/requeue 的实际落盘决策在 core/pm_engine/verification/verdict_evidence.py `_handle_scenario_requeue`（:1213，条目构造约 :1287-1303，按查重结果置位），同样不校验证据质量。
2. judge 提示词模板 agents/planner-judge.md:65-66 对 env 的定义纯定性，未要求引用可复核的环境量测（负载/CPU/温度/驱动版本）或验证窗口外的对照样本。
3. 既有 inconclusive 降级机制（core/alert_lifecycle.py:89,164、core/pm_engine/verification/escalation.py:402 `_handle_env_blocked_inconclusive`，event_bus.py:679 `_inconclusive_paused` 为其暂停守卫）只由 env-blocked 握手（summary.blocked_env 全批判定）驱动，不校验 env 归因的证据质量——「无对照的 env 结论」不会降级，直接进豁免握手。

## What Changes

- **judge 提示词（agents/planner-judge.md）**：env 定义改为「必须引用可复核的环境量测（负载/CPU/温度/驱动版本等具体数值与来源）+ 验证窗口外的对照样本」，明确无对照不得判 env。
- **归因接受门（主门 core/pm_engine/verification/verdict_evidence.py `_handle_scenario_requeue` 条目构造；辅门 core/agent_runner/prompt_builder.py `_scenario_classified` 截断恢复判据收紧）**：将被置 accept 的 env 归因条目做证据校验——evidence 须含环境量测数值与对照样本引用，缺失时不落 accept，按既有 requeue 状态降级（judge_attribution.json status 词表仅 accept/requeue，不新增第三状态），缺失项写入条目注记。
- **归因产物 schema（core/verify_engine/judge_files.py）**：judge_attribution.json 增补量测引用与对照样本字段；accept 条目缺字段时标记 inconclusive。
- **降级接线**：降级条目按 requeue 状态落盘即自然进入既有回炉重检闭环（verdict_evidence `_handle_scenario_requeue` → 轻量重合成 judge run → 回灌校验链）；blocked-env 全批 inconclusive 通道（escalation.py:402）语义不变，不进豁免握手。

## Capabilities

### judge-env-attribution

见 specs/judge-env-attribution/spec.md。

## Impact

- 影响 core/pm_engine/verification/verdict_evidence.py 的归因条目构造（env accept 门）与 core/agent_runner/prompt_builder.py 的截断恢复判据；judge 产物消费方（fastlane 等）零改动（仅新增可选字段）。
- 影响 agents/planner-judge.md 提示词模板（所有使用 judge 归因的验证链）。
- judge_attribution.json schema 变更向后兼容：新增字段可选读取，旧文件不受影响。
- 不改变 env-blocked 握手语义本身，只在其上游加证据门。