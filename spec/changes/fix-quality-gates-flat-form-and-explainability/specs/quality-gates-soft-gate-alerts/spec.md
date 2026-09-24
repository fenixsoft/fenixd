## ADDED Requirements

### Requirement: 宽松对账形态违规写人工告警

`core/agent_runner/result_gate.py` 的 `_check_quality_gates_soft` 发现 quality-gates.json
形态违规时，MUST 在保留既有 WARNING 日志的同时，向 admin_alerts 人工告警通道写入一条告警，
使 dashboard 告警面板可见。覆盖四类违规：

1. 顶层缺 `gates` 对象（含平铺形态——容错读侧兜底后仍应让人工知晓写侧偏离契约）；
2. JSON 无法解析；
3. 契约外 gate-id；
4. gate 条目 status 枚举外。

约束：

- **软约束边界不变**：告警 MUST NOT 产生任何失败终态、打回、预算消耗或派发阻塞——
  本变更只加可见性、不加强度；
- 告警内容 MUST 包含 spec 名、文件相对路径与违规描述（复用既有 WARNING 文案语义）；
- 告警为「仅可见不需裁决」语义：不进入人工裁决选择题（choices）流程，人工确认
  处理即可（与既有不可裁决信号桶同档）；
- 同一 (spec, 文件, 违规类别) 组合在告警未处理期间 MUST NOT 重复刷屏（复用/对齐
  admin_alerts 既有去重或节流机制）；
- 告警写入失败 MUST fail-open：仅记日志，不影响 run 收尾主流程。

#### Scenario: 平铺形态违规产生人工可见告警

- **WHEN** implementer 收尾对账发现 quality-gates.json 顶层缺 gates 对象
- **THEN** daemon 日志出现既有 WARNING，且 admin_alerts 新增一条含 spec 名与
  「顶层缺 gates 对象」描述的告警，dashboard 告警面板可见

#### Scenario: 软约束边界零回归

- **WHEN** 存在任意形态违规（含 JSON 损坏）
- **THEN** run 收尾流程照常完成，无 gate-blocked、无打回、无预算惩罚——与变更前一致

#### Scenario: 未处理告警不重复刷屏

- **WHEN** 同一 spec 的同一违规类别告警尚未被人工处理，对账再次发现同类违规
- **THEN** 不新增重复告警（命中去重/节流），仅既有告警保持可见

#### Scenario: 告警通道故障 fail-open

- **WHEN** admin_alerts 写入通道异常（存储不可写等）
- **THEN** 仅记 WARNING 日志，run 收尾与对账主流程零影响
