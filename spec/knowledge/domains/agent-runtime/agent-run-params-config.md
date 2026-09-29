<!-- knowledge: capability=agent-run-params-config rev=1 sources=spec/archive/2026-09-02-improve-agent-config-and-verify-resume -->

# Agent 运行参数配置

`agents.max_turns` 的取值、校验与运行时强制：单次 agent 运行的轮次上限口径单源于配置。

## 现行规则

- 默认值：`agents.max_turns` 默认 300；`.fenix/config.yaml` 未显式配置时配置加载取 300，代码内部 fallback 默认与之一致。校验要求正整数，非法值（非正数、非整数）导致配置校验失败。
- 运行时强制：`_run_claude` 统计流中 assistant 事件数，达到配置后的 `agents.max_turns` 上限即终止运行并产生「Max turns reached」类错误；对所有 agent 类型（implementer、verifier、planner 等）生效。
- Dashboard 编辑：配置页「并行度设置」区块提供 `agents.max_turns` 数字输入与保存（与 `agents.max_concurrent` 并列），复用 `POST /api/config` 写回 `.fenix/config.yaml`；保存保留 `agents` 下其它子键（`subagent_model`、`max_concurrent`、`max_retries`、`run_timeout_seconds`、`models`）及 `llm`、`gates` 等其它受管键原值不变；非法值返回 400 且不写盘；输入框预填当前配置值（无配置预填 300）。

## 溯源

- [2026-09-02 improve-agent-config-and-verify-resume](spec/archive/2026-09-02-improve-agent-config-and-verify-resume/) — 固化 max_turns 默认 300（配置与代码 fallback 单源）、运行时按 assistant 事件数强制、配置页可视化编辑与保存保留其它受管键
