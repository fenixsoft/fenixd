# spec-provider-chain-config

## ADDED Requirements

### Requirement: 角色级多 provider 候选链
`agents.models.<role>.provider` SHALL 支持 `str` 与 `list[str]` 两种形态；list 表示按序候选链，首个元素为首选。单值形态解析为单元素链，行为与现状完全一致。config loader SHALL 在启动与热更新时校验链中每个名字存在于 llm.providers，未知名字打 ERROR 日志但不阻塞加载。

#### Scenario: 列表链解析
- **WHEN** 配置 `provider: [inferaiapi.com, aliyun]` 且两者都存在于 llm.providers
- **THEN** 解析为两元素链，首选 inferaiapi.com

#### Scenario: 单值完全兼容
- **WHEN** 配置 `provider: inferaiapi.com`（字符串）
- **THEN** 行为与变更前逐字段一致

#### Scenario: 未知名字告警不阻塞
- **WHEN** 链含不存在的 provider 名
- **THEN** 启动日志出现 ERROR 记录，daemon 照常运行，该元素在运行期被跳过

### Requirement: 模型名按 provider 独立解析
候选链上每个 provider 的模型名 SHALL 从该 provider 项自身的 model 字段解析（保持现状逐 provider 独立），链条目仅引用 provider 名；切换到链上第 N 项时使用的 baseurl/apikey/model MUST 全部来自第 N 项。

#### Scenario: 切换后三件套一致
- **WHEN** attempt 因切换推进到链第二项
- **THEN** 注入的 ANTHROPIC_BASE_URL/API_KEY/MODEL 与第二项 provider 配置完全一致，CLAUDE_CONFIG_DIR 隔离目录同步切换
