# spec-agent-prompt-files

## ADDED Requirements

### Requirement: 通用提示词文件为唯一真相
六类 agent（implementer / verifier / planner-plan / planner-judge / fast-track / administrator）的 prompt 主体 MUST 存储于框架项目根 `agents/<agent-type>.md`，prompt_builder MUST 从文件加载并替换路径占位符（`{spec_name}`、`{spec_dir}`、`{scenarios_path}`、`{result_path}`、`{report_path}`、`{progress_path}` 等）。条件动态段（REPLAN 反馈、断点续跑、上轮 error、遗产上下文、场景冻结、交互契约、复核清单、verdict 退回）仍由代码按状态追加。文件缺失时 MUST 派发显式报错（不再回退内置字符串）。

#### Scenario: 文件加载与占位符替换
- **WHEN** 派发任一类 agent 且对应 agents/*.md 存在
- **THEN** prompt 主体来自文件内容，占位符已替换为该项目实际路径，动态段按状态追加

#### Scenario: 文件缺失 fail-fast
- **WHEN** agents/<agent-type>.md 不存在
- **THEN** 该 agent 派发报错并登记（不静默回退内置 prompt）

#### Scenario: 动态段语义保持
- **WHEN** 存在上轮 error / 遗产 / REPLAN 反馈 / 验证断点的 spec 派发对应 agent
- **THEN** 对应动态段仍按既有条件注入，语义与文件化前一致

### Requirement: 项目级附加提示词
被管项目根 `.fenix/agents/<agent-type>.md` 存在时，其内容 MUST 以「项目附加提示词」段附加在该 agent 通用 prompt（含动态段）之后；文件缺席时 MUST 零注入。框架代码 MUST NOT 写入项目 `.fenix/agents/`（仅 Dashboard API 按用户操作写入）。

#### Scenario: 项目级附加生效
- **WHEN** 某项目存在 .fenix/agents/verifier.md 且派发该项目的 verifier
- **THEN** prompt 末尾含「项目附加提示词」段（内容为该文件）

#### Scenario: 缺席零注入
- **WHEN** 项目无 .fenix/agents/ 目录
- **THEN** prompt 与仅通用层时逐字节一致

### Requirement: 死知识清理与领域知识迁移
通用提示词文件 MUST NOT 含 AMIS/dark- 选择器内容（选择器大全段删除，`.dark-Card`、`dark-Card--link` 示例改为 data-testid 风格通用示例）；verifier 的被管产品面板清单（Quick Links/Stock/Notes/Calculator/Email）MUST 改为通用表述（点击遍历被测应用每个主要界面，交互必须有可见结果否则 BLOCKING BUG）。云端 COS e2e、壳路由 href、seed 键格式三段领域知识 MUST 迁移为对应被管项目的 `.fenix/agents/` 条目（项目不可定位则在 run result findings 登记）。

#### Scenario: 死关键词断言
- **WHEN** 加载六类 agent 通用提示词
- **THEN** 不含 "dark-SelectControl"、"amis-dialog-widget"、"dark-Card"、"sh600036" 字样

#### Scenario: 领域知识不丢失
- **WHEN** 检查对应被管项目的 .fenix/agents/ 文件
- **THEN** 云端 e2e、壳路由、seed 格式知识以项目附加提示词形式存在

### Requirement: 设置页「提示词」页签
设置界面 MUST 统一新增「提示词」页签：用户级视图仅展示六类通用提示词（只读，按 agent 切换查看）；项目级视图展示通用提示词（只读）与项目附加提示词（可编辑，保存写入该项目 `.fenix/agents/<agent-type>.md`）。fenixd 自身项目（`.fenix` 自引用指向框架根）MUST 禁用项目级编辑并说明原因（项目级与通用层同目录，防止经项目通道修改不可修改的通用文件）。

#### Scenario: 用户级只读
- **WHEN** 用户在提示词页签查看用户级通用提示词
- **THEN** 六类 prompt 内容可见但无编辑入口

#### Scenario: 项目级编辑保存生效
- **WHEN** 用户在某项目的提示词页签编辑项目附加提示词并保存
- **THEN** `.fenix/agents/<agent-type>.md` 落盘，该项目下次派发对应 agent 的 prompt 附加该内容

#### Scenario: 自引用项目禁用编辑
- **WHEN** 当前项目为 fenixd 自身（.fenix 自引用）
- **THEN** 项目级编辑禁用并显示原因说明

### Requirement: dist 产物一致性
Dashboard 前端改动后 v3 dist MUST 重建并提交（dist 为入库产物），避免 UI 验证假阴性。

#### Scenario: 页签真实可访问
- **WHEN** 打开 Dashboard 设置页
- **THEN** 「提示词」页签在浏览器中真实渲染（重建后的 dist 承载）
