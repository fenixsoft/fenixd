# model-billing-config 增量规格

## ADDED Requirements

### Requirement: 计费信息总开关
设置页「模型」页签 MUST 提供全局「启用计费信息」开关（配置 `llm.billing.enabled`，缺省 false）。开关关闭时价格编辑区隐藏、下游一律不展示成本；开关开启时每个 Provider 卡片内出现计费价格编辑区。开关与价格同属一次「保存」提交，不做独立保存入口。

#### Scenario: 开关关闭隐藏价格区
- **WHEN** 用户打开模型页签且计费开关为关
- **THEN** 各 Provider 卡片不渲染价格编辑区，SPEC 详情与时间轴不展示任何成本信息

#### Scenario: 开关开启出现价格区
- **GIVEN** 某项目已配置至少一个 Provider
- **WHEN** 用户开启「启用计费信息」开关
- **THEN** 每个 Provider 卡片内出现「添加模型价格」行编辑区，可与开关一并保存

### Requirement: 按 provider+model 的四项单价
每个 Provider 卡片 MUST 支持添加多条价格行，每行含：模型名（必填，非空）与四项单价——每百万输入 token 费用（`input_per_million`）、每百万输出 token 费用（`output_per_million`）、缓存命中 token 费用（`cache_read_per_million`）、缓存写入 token 费用（`cache_creation_per_million`），单位 $/1M tokens。同一价格行的四项单价 MUST 全部填写（非负数值），不支持部分填写；同一 `provider+model` 组合 MUST NOT 重复。

#### Scenario: 完整价格行保存成功
- **WHEN** 用户在 Provider「inferaiapi.com」下添加模型 `deepseek-v4-flash` 的四项单价（如 0.27 / 1.10 / 0.07 / 0.28）并保存
- **THEN** 配置写入 `llm.billing.prices` 并保存后回显

#### Scenario: 单价缺失被拒绝
- **WHEN** 用户填写模型名但仅填写输入/输出两项单价即保存
- **THEN** 保存被拒绝并提示「该价格行的四项单价必须全部填写」

#### Scenario: 重复组合被拒绝
- **GIVEN** Provider `inferaiapi.com` 已有模型 `deepseek-v4-flash` 的价格行
- **WHEN** 用户在同一 Provider 下再添加一条同模型名价格行并保存
- **THEN** 保存被拒绝并提示重复

### Requirement: 配置持久化与后端校验
计费配置 MUST 存储于受管配置段 `llm.billing`（结构与价格行字段同上），随 `/api/config` 既有读写链路持久化与回显，无需新增端点。写入时后端 MUST 校验：`enabled` 为布尔；每行 `provider` 引用必须存在于 `llm.providers`；`model` 非空；四项单价为非负数值；`provider+model` 不重复。校验失败 MUST 拒绝写入并返回错误（不静默忽略）。

#### Scenario: 引用不存在的 Provider 被拒绝
- **WHEN** 价格行填写的 provider 名不在 `llm.providers` 中且用户保存
- **THEN** 写入被拒绝，错误信息列出无效的 provider 名

#### Scenario: 非法单价被拒绝
- **WHEN** 某单价填写 `-1` 或非数值且用户保存
- **THEN** 写入被拒绝，提示该字段必须为非负数值

#### Scenario: 读侧回显
- **GIVEN** 配置文件已存在合法 `llm.billing`
- **WHEN** 前端读取配置（含项目级 effective 视图）
- **THEN** 开关状态与价格行完整回显
