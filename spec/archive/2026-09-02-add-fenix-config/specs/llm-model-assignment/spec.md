## ADDED Requirements

### Requirement: LLM Provider 注册表配置

系统 SHALL 支持在 `.fenix/config.yaml` 的 `llm.providers` 下定义多个命名 LLM Provider。每个 Provider SHALL 包含 `name`（唯一标识）、`baseurl`（Anthropic 兼容端点地址）、`apikey`（访问密钥）字段，并 MAY 包含 `model`（该 Provider 的默认模型名）与 `sdk_model`（用于通过 claude-code SDK 模型名校验的官方模型名）字段。未配置 `llm.providers` 时 SHALL 视为空注册表，不改变任何现有行为。`ConfigLoader` 加载配置时 SHALL 校验 Provider 结构：`providers` 须为列表、每项 `name`/`baseurl`/`apikey` 非空、`name` 唯一；校验失败 SHALL 抛出配置错误。

#### Scenario: 手工编辑配置文件新增 Provider 被正确解析
- **WHEN** 用户在 `.fenix/config.yaml` 中 `llm.providers` 下新增一项 `{name: "volc-engine", baseurl: "https://api.example.com", apikey: "sk-xxx", model: "deepseek-v4-flash"}` 并重启 daemon
- **THEN** `ConfigLoader.load` 成功解析，配置中可读取到名为 `volc-engine` 的 Provider 及其全部字段

#### Scenario: 缺失必填字段或名称重复导致校验失败
- **WHEN** `llm.providers` 中存在缺少 `apikey` 的项，或存在两个 `name` 相同的 Provider
- **THEN** `ConfigLoader` 校验 SHALL 失败并抛出带字段说明的配置错误，拒绝加载该配置

#### Scenario: 未配置 providers 时行为不变
- **WHEN** `.fenix/config.yaml` 中不存在 `llm` 段
- **THEN** 配置正常加载，`llm.providers` 视为空列表，不产生任何校验错误或行为变化

### Requirement: 按 Agent 角色分配模型

系统 SHALL 支持在 `.fenix/config.yaml` 的 `agents.models` 下按 Agent 角色分配模型。每个角色（`implementer`、`planner-plan`、`planner-judge`、`verifier`）的分配项 SHALL 包含 `provider`（引用 `llm.providers` 中已定义的名称）与 `model`（该角色使用的模型名）。未在 `agents.models` 中列出的角色 SHALL 视为未分配，运行时完全维持现有默认模型行为（不注入任何覆盖环境变量）。`ConfigLoader` SHALL 校验分配项：角色键须为已知 Agent 类型、`provider` 须引用已定义 Provider、`model` 非空；校验失败 SHALL 抛出配置错误。

#### Scenario: 为 implementer 分配 Provider 与模型并在运行时注入环境
- **WHEN** 配置 `agents.models.implementer = {provider: "volc-engine", model: "deepseek-v4-pro"}`，且 daemon 调度 implementer 运行
- **THEN** 该 implementer 的 claude 子进程环境 SHALL 携带 `ANTHROPIC_BASE_URL=volc-engine.baseurl`、`ANTHROPIC_API_KEY=volc-engine.apikey`、`ANTHROPIC_MODEL=deepseek-v4-pro`，并传入 `--model`（值为 `sdk_model` 或 `agents.subagent_model` 的官方模型名）

#### Scenario: 未分配模型的 Agent 维持默认模型
- **WHEN** `agents.models` 未包含 `planner-judge`，且 daemon 调度 planner-judge 运行
- **THEN** 该子进程环境 SHALL 不注入任何 `ANTHROPIC_BASE_URL`/`ANTHROPIC_API_KEY`/`ANTHROPIC_MODEL` 覆盖，行为与未配置新字段时完全一致

#### Scenario: 分配引用不存在的 Provider 导致校验失败
- **WHEN** `agents.models` 中某角色的 `provider` 指向 `llm.providers` 中不存在的名称
- **THEN** `ConfigLoader` 校验 SHALL 失败并抛出指明未知 Provider 的配置错误

### Requirement: Dashboard 可视化编辑 LLM 配置

Dashboard SHALL 提供「配置」页面用于可视化查看与修改 LLM Provider 注册表及 Agent 模型分配。系统 SHALL 提供 `GET /api/config?project=<name>` 返回该项目的当前配置（含 `llm` 与 `agents.models` 段），以及 `POST /api/config?project=<name>` 接收修改后的配置并原子写回 `.fenix/config.yaml`（仅更新受管键 `llm` 与 `agents.models`，其它配置键原样保留）。POST 写入前 SHALL 执行与 `ConfigLoader` 一致的校验，校验失败 SHALL 返回 400 且不写盘。保存成功 SHALL 提示「配置已保存，重启 daemon 后生效」。

#### Scenario: 读取当前 LLM 配置
- **WHEN** 用户打开某项目的「配置」页，前端请求 `GET /api/config?project=<name>`
- **THEN** 返回 200 与含 `llm.providers`、`agents.models` 的配置 JSON

#### Scenario: 新增 Provider 并分配模型后写入文件
- **WHEN** 用户在配置页新增 Provider `{name: "volc-engine", baseurl: "...", apikey: "..."}`，将 `implementer` 分配为 `{provider: "volc-engine", model: "deepseek-v4-pro"}`，点击保存（POST /api/config）
- **THEN** 返回成功，`.fenix/config.yaml` 的 `llm.providers` 与 `agents.models` 已更新，且其它配置键（如 `project`、`schedule`）未被改动

#### Scenario: 提交非法配置被拒绝且不写盘
- **WHEN** 用户提交的配置中某 Provider 缺少 `apikey`，或某 Agent 分配引用不存在的 Provider
- **THEN** POST 返回 400 与错误说明，`.fenix/config.yaml` 内容保持不变

#### Scenario: 保存后提示重启生效
- **WHEN** 配置保存成功后
- **THEN** 前端 SHALL 显示「配置已保存，重启 daemon 后生效」的提示

### Requirement: 配置模板同步

`config.template.yaml` SHALL 包含 `llm.providers`、`agents.models`、`gates.approve_mode` 的骨架与字段说明注释，保证 `fenix-init` 生成的新项目自带新配置骨架。已存在的旧版 `.fenix/config.yaml` 缺省这些字段时 SHALL 正常运行（能力不激活）。

#### Scenario: 新项目模板包含新配置骨架
- **WHEN** 使用 `fenix-init` 基于更新后的 `config.template.yaml` 生成新项目配置
- **THEN** 生成的 `.fenix/config.yaml` 包含带注释说明的 `llm`、`agents.models`、`gates.approve_mode` 骨架

#### Scenario: 旧配置无新字段时正常启动
- **WHEN** 现有项目的 `.fenix/config.yaml` 不含 `llm` 与 `agents.models` 字段
- **THEN** daemon 正常启动，全部 Agent 使用默认模型，无校验错误
