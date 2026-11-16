# provider-ref-validation 规范

## ADDED Requirements

### Requirement: config 加载路径 provider 引用校验

daemon 侧 config 加载（含热加载）SHALL 对 `agents.models.<role>.provider` 引用执行与 Dashboard 设置保存路径同源的校验规则：引用的 provider 名必须存在于本项目 `llm.providers` 注册表。校验规则 SHALL 单源化（同一实现供加载路径与 Dashboard 保存路径共用），禁止两路径规则漂移。

#### Scenario: 未注册 provider 触发告警而非静默跳过

- **WHEN** 项目 config.yaml 的 `agents.models.implementer.provider` 引用 `bigmodel.cn`，而 `llm.providers` 仅注册 `bigmodel-cn`，config 加载执行
- **THEN** 不再产生「已跳过，不阻塞加载」静默跳过语义；发一条 major 配置告警：文案含角色名、未注册名、当前注册表清单与修复指引（编辑 config.yaml 或 Dashboard 设置）

#### Scenario: 合法引用零行为变化

- **WHEN** 所有 `agents.models` 引用的 provider 均已注册
- **THEN** 加载行为、链解析结果与引入本能力前一致，无新增日志与告警

### Requirement: 相似名建议

未注册 provider 告警 SHALL 附相似名建议：当注册表存在与未注册名高度相似（大小写/分隔符差异级，如 `bigmodel.cn` vs `bigmodel-cn`）的已注册名时，告警文案显式给出「是否意指 `<已注册名>`」建议，建议算法用编辑距离/规范化比对，阈值内才输出建议、无相似项时输出注册表清单。

#### Scenario: 一字之差给出即修建议

- **WHEN** 未注册名 `bigmodel.cn`，注册表含 `bigmodel-cn`
- **THEN** 告警文案含「是否意指 bigmodel-cn」

#### Scenario: 无相似项时给注册表清单

- **WHEN** 未注册名 `nonexistent-llm`，注册表无相似项
- **THEN** 告警文案列出当前全部已注册 provider 名，不输出「是否意指」

### Requirement: 无分配与分配失效划界

`agents.models` 角色链经校验后 SHALL 区分两形态：**无分配**（角色无 `models` 条目，合法回落形态，走既有 `harness-default-fallback` 语义与一次性 WARN）；**分配失效**（有 `models` 条目但链条目经校验全部无效，配置错误形态）。分配失效 SHALL NOT 静默走回落语义，MUST 发配置告警并保留原分配内容（告警 evidence 含原始链条目）供修复参考；派发时该角色按无可用模型处理并以 `[model-chain-unavailable]` 既有语义归因。

#### Scenario: 分配失效不静默回落

- **WHEN** 角色 `implementer` 有 `models` 条目但全部 provider 引用未注册
- **THEN** 发一条配置告警（evidence 含原始链条目），日志不出现「回落 harness 默认配置」WARN；派发失败归因为模型链不可用而非回落形态

#### Scenario: 无分配保持回落语义

- **WHEN** 角色 `verifier` 无任何 `models` 条目
- **THEN** 行为与引入本能力前一致（对称回落 + 一次性 WARN），无新增告警
