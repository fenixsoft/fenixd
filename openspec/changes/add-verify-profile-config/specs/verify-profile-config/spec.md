# spec-verify-profile-config

## ADDED Requirements

### Requirement: verify.yaml 档案条目 schema
`.fenix/verify.yaml` MUST 支持 `profile:` 顶层键，值为条目列表，每条目含：`id`（kebab-case 唯一标识）、`agents`（适用 agent 列表，取值 `planner` / `verifier` / `fast-track`，planner-plan 与 planner-judge 均按 planner 匹配）、`text`（Markdown 正文）。schema 校验放行无 `profile` 键的既有 verify.yaml（向后兼容）。

#### Scenario: 既有 verify.yaml 不受影响
- **WHEN** verify.yaml 仅有 prepare/serve/ready 三段、无 profile 键
- **THEN** load_verify_contract 解析成功，验证契约行为与引入前一致

#### Scenario: 合法条目解析
- **WHEN** verify.yaml 含 profile 条目（id/agents/text 齐全）
- **THEN** 解析出结构化条目供 prompt_builder 与 Dashboard API 消费

### Requirement: prompt 按适用 agent 注入档案
prompt_builder 构建 planner-plan、planner-judge、verifier、fast-track prompt 时，MUST 读取本项目的 verify.yaml profile 条目，将 `agents` 命中该 agent 类型的条目 text 以「## 项目验证档案（用户配置）」标题段注入。无命中条目时 MUST 不注入该段（prompt 与未引入本能力前逐字节一致）。

#### Scenario: 条目按 agent 过滤注入
- **WHEN** 某条目 agents=[planner]，构建 planner-plan 与 verifier prompt
- **THEN** planner-plan prompt 含该条目 text，verifier prompt 不含

#### Scenario: 无档案零注入
- **WHEN** verify.yaml 无 profile 键或条目列表为空
- **THEN** 各 agent prompt 与引入本能力前逐字节一致

### Requirement: 死知识清理与迁移
prompt_builder MUST 删除 AMIS 选择器大全段（planner 选择器规范中 dark-/amis- 相关 19 行）及 planner-judge、interaction_contract_section 中的 `.dark-Card` / `dark-Card--link` 示例（示例改为 data-testid 风格通用示例）；verifier Step 3 的被管产品面板清单 MUST 替换为通用表述。被删的项目特定知识（云端 COS e2e、壳路由 href、seed 键合法格式）MUST 迁移为 fenixd 自身 `.fenix/verify.yaml` 的 profile 条目（agents 标注为 planner/verifier 按原适用）。

#### Scenario: 死关键词不再出现在 prompt
- **WHEN** 构建 planner-plan / planner-judge / verifier prompt（在无档案的项目上）
- **THEN** prompt 不含 "dark-SelectControl"、"amis-dialog-widget"、"dark-Card"、"sh600036" 字样

#### Scenario: 迁移知识不丢失
- **WHEN** 查看项目 `.fenix/verify.yaml` 的 profile 条目
- **THEN** 云端 e2e、壳路由、seed 格式三段知识以条目形式存在并按原适用 agent 标注

### Requirement: Dashboard 验证页签档案编辑
Dashboard 设置页「验证」页签 MUST 新增「项目验证档案」编辑区：展示既有条目（id、agents、text），支持新增、修改、删除条目并保存落盘到该项目 `.fenix/verify.yaml` 的 profile 键；保存后新派发的 agent prompt 即携带更新后条目。

#### Scenario: 编辑保存生效
- **WHEN** 用户在验证页签新增条目（id/agents/text）并保存
- **THEN** verify.yaml 落盘含该条目，下一次构建的对应 agent prompt 注入该条目 text

#### Scenario: 删除条目零残留
- **WHEN** 用户删除某条目并保存
- **THEN** verify.yaml 中该条目移除，后续 prompt 不再含其 text
