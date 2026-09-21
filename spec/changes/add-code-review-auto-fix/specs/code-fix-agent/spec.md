## ADDED Requirements

### Requirement: code-fix agent 类型注册

系统 SHALL 新增一等公民 agent 类型 `code-fix`，在全部四处注册点保持一致，缺任一注册点均视为实现不完整。

- `core/agent_runner/prompt_builder.py` 的 `AGENT_PROMPT_FILES` MUST 含 `"code-fix": "code-fix.md"`。
- `core/agent_runner/run_files.py` 的 `RUN_ID_AGENT_PREFIXES` MUST 含 `("code-fix-", "code-fix")`。
- `core/config.py` 的 `KNOWN_AGENT_TYPES` MUST 含 `"code-fix"`。
- `.fenix/config.template.yaml` 的 `agents.models` MUST 含 `code-fix` 模型分配示例（用户级/项目级 `.fenix/config.yaml` 为 gitignored 运行时文件，由用户按模板自行配置，不进交付声明）。
- 框架根 `agents/code-fix.md` 提示词文件 MUST 存在。

#### Scenario: run_id 前缀被正确归属

- **WHEN** 存在 run_id 为 `code-fix-1758211200` 的 run
- **THEN** `infer_run_agent_type("code-fix-1758211200")` MUST 返回 `("code-fix", "1758211200")`，Dashboard 时间线 MUST 显示 `code-fix` agent 类型而非泛型 `agent`

#### Scenario: 前缀无子串冲突

- **WHEN** `RUN_ID_AGENT_PREFIXES` 含 `("code-review-", "code-review")` 与 `("code-fix-", "code-fix")` 两项
- **THEN** run_id `code-review-100` MUST 归属 `code-review`，run_id `code-fix-100` MUST 归属 `code-fix`，MUST NOT 互相错配

### Requirement: 模型链复用 code-review 的 LLM 配置

`code-fix` run 的模型分配 SHALL 以「与 `code-review` 相同配置」为缺省行为，MUST NOT 静默走默认网关而无回退。

- 解析链 MUST 依次为：`agents.models.code-fix` → `agents.models.code-review` → `agents.models.self-review` → `agents.models.administrator` → 默认网关。
- 链上首个命中项 MUST 决定 provider（baseurl/apikey/env）与 model，且 MUST 按既有 `_get_agent_model_assignment` + `_ensure_agent_config_dir` 形态注入子进程环境。
- 未登记 `agents.models.code-fix` 时 MUST 回退 `agents.models.code-review`（即「使用 code-review 相同的 llm 配置」），MUST NOT 直接跳到默认网关。

#### Scenario: 未配置 code-fix 时落到 code-review 级

- **WHEN** `.fenix/config.yaml` 配置了 `agents.models.code-review`，未配置 `agents.models.code-fix`
- **THEN** 派发 `code-fix` run MUST 使用与 `code-review` 完全相同的 provider（baseurl/apikey）与 model

#### Scenario: 显式配置 code-fix 可独立覆盖

- **WHEN** `.fenix/config.yaml` 同时配置了 `agents.models.code-fix` 与 `agents.models.code-review`，且二者不同
- **THEN** 派发 `code-fix` run MUST 使用 `agents.models.code-fix` 分配的模型，MUST NOT 被 `code-review` 的配置覆盖

### Requirement: code-fix agent 的写权限与产物契约

`code-fix` agent SHALL 在隔离 worktree 内修改源码并提交，逐条落盘处置结果，MUST NOT 直接写主树。

- 派发 MUST 经 `worktree_manager.create(spec_name="code-review-fix", agent_type="code-fix")` 创建独立 worktree；agent 的工作目录 MUST 为该 worktree，MUST NOT 为主树。
- agent MUST 每处置完一条问题向框架注入的 out 文件（绝对路径，形如 `<worktree>/.fenix/code-review/fix-out-<run_id>.jsonl`）追加一行，字段至少含 `item_id`、`status`（`fixed` | `skipped`）、`file`。
- agent MUST 把修复提交到当前 worktree 的分支；MUST NOT 执行 merge-back（合回由框架完成）。
- agent MUST NOT 修改 `.fenix/` 下的框架运行时文件或台账 `items.jsonl`（条目状态由框架在合回成功后更新）。
- `agents/code-fix.md` MUST 明确：仅处理注入清单中的条目，不得顺手重构清单外代码。

#### Scenario: 逐条增量落盘

- **WHEN** agent 处置完清单中第 5 条（共 20 条）
- **THEN** out 文件 MUST 已含 5 行结果，框架侧批内 `done` MUST 为 5，MUST NOT 等到 20 条全处置完才落盘

#### Scenario: agent 不写主树

- **WHEN** 一次 `code-fix` run 运行中
- **THEN** 主树工作区 MUST 保持不变（无该 run 产生的未提交改动）；全部改动 MUST 落在 worktree 与其分支上

#### Scenario: 产物缺失判失败

- **WHEN** `code-fix` run 退出码为 0，但 out 文件不存在或零有效行
- **THEN** 框架 MUST 判该批失败（不合回、不置条目 `resolved`），MUST NOT 把空跑当成功
