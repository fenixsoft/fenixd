## ADDED Requirements

### Requirement: max_turns 默认值 300

系统 SHALL 将 `agents.max_turns`（单次 Agent 运行轮次上限）的默认值调整为 300。`.fenix/config.yaml` 未显式配置 `agents.max_turns` 时，配置加载 SHALL 使用默认值 300；代码内部的 fallback 默认值 SHALL 与之一致（均为 300，原为 150/50）。配置校验 SHALL 保持现有语义：`agents.max_turns` 必须为正整数，非法值（非正数、非整数或缺失时的非数字）SHALL 导致配置校验失败。

#### Scenario: config.yaml 显式配置 300 被正确加载
- **WHEN** `.fenix/config.yaml` 中 `agents.max_turns: 300`
- **THEN** `ConfigLoader.load` 成功，max_turns 值为 300

#### Scenario: 未配置时使用默认值 300
- **WHEN** `.fenix/config.yaml` 中不存在 `agents.max_turns`
- **THEN** max_turns 默认取 300，且加载不报错

#### Scenario: 非法 max_turns 校验失败
- **WHEN** `agents.max_turns` 为 0、负数或非整数
- **THEN** `ConfigLoader` 校验失败并抛出说明字段的配置错误

### Requirement: Dashboard 可视化编辑 max_turns

Dashboard 配置页 SHALL 在「并行度设置」区块提供 `agents.max_turns` 的数字输入与保存能力，与 `agents.max_concurrent` 并列。保存 SHALL 复用 `POST /api/config` 将新值写回 `.fenix/config.yaml` 的 `agents.max_turns`，且 SHALL 保留 `agents` 下其它子键（如 `subagent_model`、`max_concurrent`、`max_retries`、`run_timeout_seconds`、`models`）及 `llm`、`gates` 等其它受管键原值不变。提交非法 max_turns（非正整数）SHALL 返回 400 且不写盘。未显式输入时输入框 SHALL 预填当前配置值（无配置时预填 300）。

#### Scenario: 配置页读取当前 max_turns
- **WHEN** 用户打开配置页（`GET /api/config?project=<name>`）
- **THEN** 返回的配置中包含当前 `agents.max_turns` 值

#### Scenario: 修改 max_turns 并保存，其它 agents 子键保持不变
- **WHEN** 用户将 max_turns 改为 300 并保存，且 `agents` 下已有 `max_concurrent: 4`、`subagent_model: "claude-sonnet-5"`、`max_retries: 3`
- **THEN** `.fenix/config.yaml` 的 `agents.max_turns` 更新为 300，`agents.max_concurrent`、`agents.subagent_model`、`agents.max_retries` 等其它子键原值不变

#### Scenario: 提交非法 max_turns 被拒绝且不写盘
- **WHEN** 用户提交 `agents.max_turns: 0` 或非数字
- **THEN** POST 返回 400 与错误说明，配置文件内容不变

## ADDED Requirements

### Requirement: max_turns 运行时生效

Agent 运行器的单次运行轮次上限 SHALL 读取配置后的 `agents.max_turns` 值（含默认 300），此上限在 `_run_claude` 中强制：统计流中 assistant 事件数达到上限即终止运行并产生「Max turns reached」类错误。该行为 SHALL 对 implementer、verifier、planner 等所有 agent 类型生效。

#### Scenario: 运行时使用配置的 max_turns
- **WHEN** `.fenix/config.yaml` 配置 `agents.max_turns: 300` 且 verifier 运行
- **THEN** 该运行被允许执行至多 300 个 assistant 轮次，达到 300 轮即被终止