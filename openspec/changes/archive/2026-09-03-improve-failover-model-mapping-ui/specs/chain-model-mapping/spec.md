# spec-chain-model-mapping

> 本能力取代 add-provider-failover 交付的 provider-chain-config 中「角色级 model 强制且对全链生效」的解析行为；str/list 旧形态逐字节兼容。

## ADDED Requirements

### Requirement: 链元素支持对象形态与元素级模型
`agents.models.<role>.provider` 列表元素 SHALL 支持 `str` 与 `{provider: str, model?: str}` 对象两种形态。元素模型解析顺序：元素自带 model > 角色级 model > llm.providers 条目的 model 字段；三者皆空的元素在运行期被跳过并打 ERROR（不阻塞加载）。角色级 `model` SHALL 不再被要求非空，语义为全链缺省。

#### Scenario: 对象元素按自身模型请求
- **WHEN** 链为 `[{provider: inferaiapi.com, model: deepseek-v4-flash}, {provider: bigmodel.cn, model: glm-5.3-flash}]`
- **THEN** 首选失败切换到第二项时，请求携带 `glm-5.3-flash` 而非首项模型名

#### Scenario: 角色级 model 作为缺省
- **WHEN** 链为 `[inferaiapi.com, aliyun]` 且角色级 `model: deepseek-v4-flash`、aliyun 的 providers 条目含 `model: deepseek-v4-flash-0731`
- **THEN** 两项均解析出模型：inferaiapi 用角色级缺省，aliyun 因角色级已提供而同样使用 `deepseek-v4-flash`（条目字段仅在角色级缺省时生效）

#### Scenario: 全空链回退默认网关
- **WHEN** 角色级无 model 且所有元素均不可解析出模型
- **THEN** 分配返回 None，该角色走默认网关，行为与未配置一致

### Requirement: 校验规则替换
校验 SHALL 删除"角色级 model 必须非空"，改为"逐元素模型可解析性检查"；不可解析元素打 ERROR 指明元素下标但不阻塞加载；完全无可用元素的链校验通过（分配层返回 None）。

#### Scenario: 缺角色级 model 的合法配置通过校验
- **WHEN** 配置 `provider: [{provider: a, model: m1}]` 且无角色级 model
- **THEN** 校验通过，无 ERROR

#### Scenario: 不可解析元素报下标
- **WHEN** 链第二项无法解析出任何模型名
- **THEN** ERROR 日志包含 `agents.models.<role>.provider[1]` 与原因

### Requirement: 切换时的模型变化留痕
failover 链推进 SHALL 使用目标元素解析出的模型名注入 env；provider_marker 行 SHALL 含所用 model；switch 日志在模型名发生变化时 MUST 附加 `model_changed: <old>→<new>`。

#### Scenario: 跨模型切换留痕
- **WHEN** attempt 从 deepseek-v4-flash（inferaiapi）切换到 glm-5.3-flash（bigmodel）
- **THEN** daemon 日志出现 provider switched 且含 `model_changed: deepseek-v4-flash→glm-5.3-flash`，新 attempt 的 provider_marker 行 model=glm-5.3-flash
