# help-docs 规格

## ADDED Requirements

### Requirement: 帮助文档集由 11 篇文档构成
`docs/help/` 目录 SHALL 恰好包含以下文档：`README.md`（帮助中心目录索引）与 10 篇正文——`01-quick-start.md`（快速上手）、`02-concepts.md`（核心概念与架构）、`03-lifecycle.md`（SPEC 生命周期与状态机）、`04-cli.md`（CLI 操作手册）、`05-verification.md`（验证体系详解）、`06-governance.md`（调度与治理规则）、`07-dashboard.md`（Dashboard 使用指南）、`08-config.md`（配置参考）、`09-artifacts.md`（文件与数据地图）、`10-faq.md`（FAQ 与故障排查）。每篇正文 SHALL 有唯一的主标题（一级标题）。

#### Scenario: 文档文件齐备
- **WHEN** 检查仓库 `docs/help/` 目录
- **THEN** 上述 11 个文件全部存在，且每个文件非空、含一个一级标题

#### Scenario: 目录索引可导航
- **WHEN** 阅读 `docs/help/README.md`
- **THEN** 其中包含指向全部 10 篇正文的相对链接，并给出「新用户入门」与「运维排查」两条阅读路径建议

### Requirement: 覆盖范围完整
文档集 SHALL 覆盖以下主题，且主题归属与提纲一致：完整开发流程（安装→初始化→启动→提需求→自动循环→审批推送）落入快速上手与核心概念；状态机 10 状态与全部合法转移落入生命周期篇；7 个 fenix-* skill 与 bin/ 辅助脚本落入 CLI 篇；fast-track 与 full 执行模式的选择标准落入 CLI 篇；三步验证流水线、verify.yaml 契约、场景冻结、verdict 分类与修复循环落入验证篇；优先级/并发/三类预算/重试退避/超时监督/自动恢复/merge 熔断/fix 族谱收敛/告警分级/重启协议落入治理篇；Dashboard 四页与帮助页自身的用法落入 Dashboard 篇；分级配置合并、热更新、全部配置键落入配置篇；STATE.md、SPEC artifacts、Deliverables 声明段、runs/verify-progress/admin_alerts/todo.md/PROJECT_LOG.md 落入数据地图篇；常见故障现象→根因→处置落入 FAQ 篇。

#### Scenario: 状态机文档与代码一致
- **WHEN** 对照 `core/state_machine.py` 的 `SpecStatus` 与 `VALID_TRANSITIONS` 审阅生命周期篇
- **THEN** 文档列出的状态集合、每个状态的可转移目标与代码一致（含 blocked→ready 人工恢复、verified→done、pushed 终态），并说明门禁逃生门（verified→testing 仅自动触发）与冻结机制

#### Scenario: 治理篇覆盖间接规则
- **WHEN** 审阅调度与治理规则篇
- **THEN** 文档解释了 impl_run_budget 耗尽→blocked+人工告警、token 预算 80%/100% 告警、merge 熔断阈值、fix 族谱上限、告警 critical/major 与 warning/minor 的分级去向，且每条规则配有「对用户意味着什么」的说明

### Requirement: 图表一律使用 mermaid
文档中所有示意图（架构、流程、状态转移、时序）SHALL 使用 mermaid 代码块（```mermaid```）承载，SHALL NOT 使用 ASCII 字符画。至少包含：架构图（核心概念篇）、端到端流程图（快速上手篇）、状态图 stateDiagram（生命周期篇）、验证流水线图（验证篇）、告警分级流向图（治理篇）。

#### Scenario: 无 ASCII 图
- **WHEN** 对 11 篇文档做静态检查
- **THEN** 存在 ```mermaid``` 代码块；不存在以 `┌`、`│`、`──▶` 等制表/箭头字符为主的 ASCII 示意图

#### Scenario: 必备图表在场
- **WHEN** 检查核心概念、快速上手、生命周期、验证、治理五篇
- **THEN** 分别能找到架构 mermaid 图、流程 mermaid 图、stateDiagram-v2 状态图、验证流水线图、告警分级流向图

### Requirement: 内容以代码为准并标注已知漂移
文档描述的行为 SHALL 以当前代码实现为准。凡 README.md 或 config.template.yaml 与代码缺省不一致的点（daemon 由 supervisor 托管而非 tmux、token 预算 100% 告警实际为 warning 级、impl_run_budget 模板值 4 与代码缺省 6、daily_run_limit 模板值 300 与代码缺省 50 等），SHALL 按实际行为书写且在 FAQ 或配置篇集中列出这些易混淆项。

#### Scenario: 漂移点澄清
- **WHEN** 阅读配置参考篇
- **THEN** 能找到「模板值与代码缺省不一致」的小节，逐条列出上述差异并给出「实际生效值以项目 config.yaml 为准」的结论

### Requirement: 每篇可独立阅读且交叉链接
每篇文档 SHALL 不依赖阅读顺序即可理解（首次出现的术语给出一句话解释或指向术语表），相关主题之间 SHALL 使用相对链接交叉引用（如治理篇→配置篇的具体键、FAQ→数据地图篇的排查文件）。

#### Scenario: 交叉链接有效
- **WHEN** 抽取任一篇文档中的全部相对链接目标
- **THEN** 链接目标文件均存在于 `docs/help/`，且锚点指向的标题真实存在
