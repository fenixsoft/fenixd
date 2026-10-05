## ADDED Requirements

### Requirement: 裁决结果文件派发前留档

裁决（planner-judge）run 派发前，若上轮结果文件 .fenix/verify-progress/<spec>/.fenix-run-result.json 存在，编排层须将其原子改名为 prev-judge-result.json 留档后再派发；改名失败仅 WARNING 不阻断派发；除该单文件外不得触碰其他跨轮产物。

#### Scenario: 上轮遗留文件被留档

- **WHEN** 裁决 run 派发且上轮 .fenix-run-result.json 存在
- **THEN** 该文件被改名为 prev-judge-result.json，本轮产物硬门不再命中陈旧残留

#### Scenario: 无遗留文件时零影响

- **WHEN** 裁决 run 派发且无遗留结果文件
- **THEN** 派发行为与既有快道（verdict 稳定复用/全绿快道）行为零变化

### Requirement: 陈旧残留重试前清理

产物硬门命中「结果文件早于本轮启动」进入原地重试前，须先改名/删除该陈旧文件，使再败归因退化为「结果文件缺失」，并防止同一陈旧文件烧光全部原地重试预算。

#### Scenario: 重试不再重复命中同一陈旧文件

- **WHEN** 硬门命中陈旧残留并触发原地重试
- **THEN** 重试前陈旧文件已被清理，重试的失败归因不再是「陈旧残留」