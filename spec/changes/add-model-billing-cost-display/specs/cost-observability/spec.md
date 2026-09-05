# cost-observability 增量规格（add-model-billing-cost-display）

## MODIFIED Requirements

### Requirement: 金额展示不伪造
成本 MUST 且 ONLY 以本地计算为准：run 成本 = 该 run 的 usage 分项（input_tokens、output_tokens、cache_read_input_tokens、cache_creation_input_tokens）× 该 run 实际 `model@provider` 的配置单价。该 run 的模型未配置价格（或计费开关关闭）时展示「成本不可用」而非 $0.00，且 MUST NOT 回退展示网关回传金额（原口径「网关回传 total_cost_usd 才展示」废止；STATE `_cost_usd` 网关回传累计保留但退出展示）。

#### Scenario: 未配置价格不伪造金额
- **WHEN** 某模型的计费价格未配置且用户查看相关成本展示
- **THEN** 界面显示「成本不可用」标注而非 $0.00，也不显示网关回传金额

#### Scenario: 已配置价格本地计算
- **GIVEN** `model@provider` 已配置四项单价且计费开关开启
- **WHEN** 该模型的一次 run 收工（usage：input 1M / output 0.1M / cache_read 2M / cache_creation 0.2M）
- **THEN** 该 run 成本 = 1×输入价 + 0.1×输出价 + 2×缓存读价 + 0.2×缓存写价

## ADDED Requirements

### Requirement: run 级成本本地计算
系统 MUST 从 run 产物尾部（`.fenix/runs/*.jsonl`，含归档与历史 run）的 result 事件提取 usage 分项、provider_marker 提取实际 `model@provider`，按配置单价本地计算每 run 成本；历史 run 无需迁移即可计算。单价匹配 MUST 按 `provider+model` 精确匹配 `llm.billing.prices`。无 result 事件（运行中/中断/无 LLM 的 run）视为不可计价。失败重试产生的中间 attempt 消耗与既有 usage 统计口径一致：仅最终 result 计入。

#### Scenario: 历史 run 补算成本
- **GIVEN** 计费价格在 run 完成之后才配置
- **WHEN** 用户打开该 run 所在 spec 的时间轴
- **THEN** 该历史 run 节点按其 usage 与配置单价显示成本

#### Scenario: 中断 run 不可计价
- **WHEN** 某 run 因中断无 result 事件
- **THEN** 该 run 不计入成本合计，节点不显示成本标注

### Requirement: SPEC 详情成本展示
SPEC 详情页 MUST 展示该 spec 的成本信息：可计价 run 的成本求和；存在未计价 run 时 MUST 附注未计价 run 数量（如「含 N 个未计价 run」）。全部 run 均不可计价（含计费开关关闭/无任何匹配价格）时展示「成本不可用」。展示 MUST 与既有累计 token 展示同区（项目信息区），不新增独立页面。

#### Scenario: 混合计价附注
- **GIVEN** 某 spec 共 5 个 run，其中 4 个模型的模型已计价、1 个未计价
- **WHEN** 打开该 spec 详情
- **THEN** 展示 4 个可计价 run 的成本合计，并附注「含 1 个未计价 run」

#### Scenario: 全部未计价
- **WHEN** 打开一个无任何可计价 run 的 spec 详情
- **THEN** 成本展示「成本不可用」

### Requirement: 时间轴 run 节点成本标注
运行时间轴的每个 run 节点 MUST 在可计价时显示该 run 的成本标注（含其 `model@provider` 信息与成本，如既有 llm Tag 风格）；不可计价时节点 MUST NOT 显示成本标注（避免历史节点噪音）。成本标注 MUST NOT 改变时间轴既有节点结构与交互。

#### Scenario: 可计价节点显示成本
- **GIVEN** 某 run 的 `model@provider` 已计价
- **WHEN** 时间轴渲染该 run 节点
- **THEN** 节点头部显示成本标注

#### Scenario: 未计价节点无标注
- **WHEN** 时间轴渲染一个未计价模型的 run 节点
- **THEN** 该节点不显示成本标注，其余内容（状态/耗时/总结）不受影响
