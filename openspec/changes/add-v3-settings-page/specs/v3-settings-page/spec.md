# v3 设置页（settings-page）

## ADDED Requirements

### Requirement: 设置页整体布局

v3 的 `/settings` 路由渲染设置页，采用 ant-design account/settings 风格布局：左侧竖向子项菜单（LLM Provider / Agent 模型分配 / 并行度设置 / 审批模式 / Token 预算 / 界面风格），右侧为当前选中子项的设置面板；页面加载后默认选中「LLM Provider」。

#### Scenario: 打开设置页

- **WHEN** 用户点击 v3 左侧菜单「设置」进入 `/settings`
- **THEN** 页面展示左侧六个子项菜单，右侧默认渲染「LLM Provider」面板，页面不出现"建设中"占位内容

#### Scenario: 切换设置子项

- **WHEN** 用户点击左侧菜单中任意其它子项（如「审批模式」）
- **THEN** 右侧面板切换为该子项的设置内容，左侧选中态高亮跟随

### Requirement: 配置读取与作用域

设置页通过 `GET /api/config?project=<name>` 读取配置（复用 v1 后端，零后端改动）。支持用户级（无项目参数，写 `~/.fenix/config.yaml`）与项目级（带项目参数，写 `.fenix/config.yaml`）两种作用域切换；默认进入项目级并以 v1 相同的项目选择方式确定目标项目。

#### Scenario: 读取项目级配置

- **WHEN** 用户选择某项目后打开设置页
- **THEN** 页面通过 `GET /api/config?project=<name>` 拉取配置并填充各子项表单，无配置文件时展示"项目尚无配置文件"类提示且表单为默认值

#### Scenario: 继承自用户级标注

- **WHEN** 某受管键在响应的 `sources` 中标记为 `user`
- **THEN** 该键所在子项面板展示"继承自用户级"提示（语义同 v1 的 config-inherit-badge）

### Requirement: LLM Provider 子项

「LLM Provider」子项管理 `llm.providers` 列表：展示现有 Provider 卡片（名称、baseurl、apikey、默认模型），支持新增（追加空白卡片）、编辑字段、删除卡片；保存时整体写回数组。

#### Scenario: 新增并保存 Provider

- **WHEN** 用户点击「新增 Provider」并填写 baseurl / apikey / 默认模型后点击保存
- **THEN** 页面发起 `PUT /api/config` 保存，`llm.providers` 包含新卡片数据，保存成功后给出成功提示

#### Scenario: 删除 Provider

- **WHEN** 用户在某 Provider 卡片上点击删除并确认
- **THEN** 保存后 `llm.providers` 不再包含该条目

### Requirement: Agent 模型分配子项

「Agent 模型分配」子项按 Agent 角色（v1 `KNOWN_AGENT_TYPES` 全集）逐个分配：选择 Provider（下拉，取自 `llm.providers`）与模型名（输入或选择，留空使用该 Provider 默认模型），写回 `agents.models`。

#### Scenario: 为角色分配模型

- **WHEN** 用户为某 Agent 角色选择 Provider 并填写模型名后保存
- **THEN** `PUT /api/config` 的 `agents.models` 中该角色键为 `{provider, model}`，保存成功

#### Scenario: 无可用 Provider 提示

- **WHEN** 作用域内 `llm.providers` 为空
- **THEN** 面板展示"请先在 LLM Provider 子项添加 Provider"的引导提示（语义同 v1）

### Requirement: 并行度设置子项

「并行度设置」子项提供三个正整数设置：并行度 `agents.max_concurrent`（默认 2）、单次运行轮次上限 `agents.max_turns`、单次运行时长上限 `agents.run_timeout_seconds`（秒），并展示 v1 同款说明文案（严格优先级并行语义、热加载生效）。

#### Scenario: 修改并行度

- **WHEN** 用户将并行度改为 3 并保存
- **THEN** `PUT /api/config` 的 `agents.max_concurrent` 为 3，页面提示"约 30 秒内热加载生效"

### Requirement: 审批模式子项

「审批模式」子项提供 `gates.approve_mode` 单选：manual（SPEC 完成后停留 done，等待人工推送）/ auto（自动推送），选项附 v1 同款说明文案。

#### Scenario: 切换审批模式

- **WHEN** 用户选择 auto 并保存
- **THEN** `PUT /api/config` 的 `gates.approve_mode` 为 `auto`

### Requirement: Token 预算子项

「Token 预算」子项提供三个数值设置：Token 预算（百万，`agents.token_budget_millions`，0=关闭，默认 50）、每日 Agent 运行限额（`agents.daily_run_limit`，0=不限）、实现尝试预算（`agents.impl_run_budget`，1-10），并展示 v1 同款说明文案。

#### Scenario: 关闭 Token 预算

- **WHEN** 用户将 Token 预算设为 0 并保存
- **THEN** `PUT /api/config` 的 `agents.token_budget_millions` 为 0，页面提示预算检查已关闭

### Requirement: 界面风格子项

「界面风格」子项提供亮色/暗色切换，选择后立即全站生效并写入浏览器 localStorage（键 `fenix.theme`）；该项不参与 `PUT /api/config` 保存路径。

#### Scenario: 切换暗色主题

- **WHEN** 用户在界面风格子项选择暗色
- **THEN** 页面立即切换为暗色配色且 localStorage `fenix.theme` 为 `dark`，刷新后保持；不发起 `PUT /api/config`

### Requirement: 保存与错误反馈

各子项面板提供统一的保存操作：保存前进行基础校验（数值范围等），成功后展示成功提示并静默刷新配置数据；失败时展示可读错误（后端 `error` 字段优先），不重置用户已填写内容。

#### Scenario: 保存失败反馈

- **WHEN** 保存请求失败（如校验 400）
- **THEN** 页面展示后端返回的错误信息，表单保留用户当前输入
