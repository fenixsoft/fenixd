# self-review-midflight-signals 变更

## MODIFIED Requirements

### Requirement: run 指标离群初筛按车道分组基线

离群初筛的组中位基线必须按真实车道分组：指标行缺 agent_type 时以 run_id 前缀推断车道归属；批量相关车道（如 code-fix）以组内历史批分布为 turns 基线，正常长批不再越线；组内样本不足时保持既有跳过语义。

#### Scenario: 无 agent_type 指标行按 run_id 前缀归组

- **When** 初筛读到无 agent_type 字段的指标行（maintenance 三车道或 context metrics 兜底行）
- **Then** 以 run_id 前缀经 infer_run_agent_type 推断车道（evo- 前缀归 evolution），不再落入 unknown 混合组

#### Scenario: code-fix 正常长批不再全员越线

- **When** code-fix 批的 turns 落在同车道近期批分布（如同链/近 N 批 P90）正常范围内
- **Then** 不产生离群旗标；超分布的异常批仍被标出

#### Scenario: 组内样本不足保持跳过

- **When** 分组后某车道样本数低于最小样本阈值
- **Then** 该组跳过初筛，语义与既有行为一致，不回退

### Requirement: 未分组车道的成本维度可观测

初筛的成本维度不得对未写富指标行的车道整体失明。

#### Scenario: maintenance 车道成本入基线

- **When** code-fix/code-review/evo 车道 run 无 cost_usd 富指标行
- **Then** 初筛经补写的富指标行或交叉读 .fenix/cost/*_tokens.json 台账获得成本样本，成本维度参与该车道基线（如 85.68 美元的全仓扫描 run 可被成本维度看见）