## ADDED Requirements

### Requirement: 管理员车道收尾宽限

框架在轮数上限的末次扩容点（turn extension 2/2）与墙钟监督末次扩容点，对非 impl 车道（administrator 等）且 run 内自建任务清单全部 completed 的 run，发放一次性收尾宽限（默认 20 轮，可配）；宽限期内 run 只应用于收尾动作（写处置记录、end_turn）；宽限耗尽仍未终态时按既有击杀路径落终态。

#### Scenario: 任务清零后获收尾宽限

- **WHEN** 管理员 run 触达原轮数上限且 run 内自建任务全部 completed
- **THEN** 框架发放一次性收尾宽限并在 turn_extension evidence 注记
- **AND** 宽限耗尽仍未终态时按既有超限路径落终态

#### Scenario: 自建任务未清零时不触发宽限

- **WHEN** 管理员 run 触达原轮数上限但 run 内自建任务仍有未完成项
- **THEN** 维持既有流量型续期判据，不发收尾宽限

### Requirement: 处置记录先行契约

administrator 提示词约束：诊断闭环判定后 MUST 先覆盖写最终处置记录，再执行环境恢复/清理等长动作；自建任务全部 completed 后 MUST NOT 开启新一轮实验；最终处置记录不得留作最后一个动作。

#### Scenario: 诊断闭环先落记录

- **WHEN** 管理员判定诊断链闭环
- **THEN** 最终处置记录先于任何长恢复动作落盘