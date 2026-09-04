## ADDED Requirements

### Requirement: 并行度配置项

系统 SHALL 将 `agents.max_concurrent` 作为「并行度」配置：即同一时刻允许运行的 Agent 进程数上限，默认值为 2。该配置 SHALL 继续由 `ConfigLoader` 加载并校验（须为正整数，非正数或非整数 SHALL 导致配置校验失败）。未显式配置时 SHALL 使用默认值 2。`config.template.yaml` SHALL 为 `agents.max_concurrent` 提供注释，说明其并行度语义（同优先级任务可并行至该值）。

#### Scenario: 配置并行度为 4 被正确加载
- **WHEN** `.fenix/config.yaml` 中 `agents.max_concurrent: 4`
- **THEN** `ConfigLoader.load` 成功，并行度值为 4

#### Scenario: 非法并行度校验失败
- **WHEN** `agents.max_concurrent` 为 0、负数或非整数
- **THEN** `ConfigLoader` 校验 SHALL 失败并抛出说明字段的配置错误

#### Scenario: 未配置时使用默认值 2
- **WHEN** `.fenix/config.yaml` 中不存在 `agents.max_concurrent`
- **THEN** 并行度默认取 2

### Requirement: Dashboard 可视化编辑并行度

Dashboard 配置页 SHALL 提供并行度（`agents.max_concurrent`）的数字输入与保存能力。保存 SHALL 复用 `POST /api/config` 将新值写回 `.fenix/config.yaml` 的 `agents.max_concurrent`，且 SHALL 保留 `agents` 下其它子键（如 `subagent_model`、`max_retries`、`max_turns`）及 `llm`、`gates` 等其它受管键原值不变。提交非法并行度（非正整数）SHALL 返回 400 且不写盘。保存成功 SHALL 提示「配置已保存，重启 daemon 后生效」。

#### Scenario: 配置页读取当前并行度
- **WHEN** 用户打开配置页（`GET /api/config?project=<name>`）
- **THEN** 返回的配置中包含当前 `agents.max_concurrent` 值

#### Scenario: 修改并行度并保存，其它 agents 子键保持不变
- **WHEN** 用户将并行度改为 4 并保存，且 `agents` 下已有 `subagent_model: "claude-sonnet-5"`、`max_retries: 3`
- **THEN** `.fenix/config.yaml` 的 `agents.max_concurrent` 更新为 4，`agents.subagent_model` 与 `agents.max_retries` 等其它子键原值不变

#### Scenario: 提交非法并行度被拒绝且不写盘
- **WHEN** 用户提交 `agents.max_concurrent: 0` 或非数字
- **THEN** POST 返回 400 与错误说明，配置文件内容不变
