# codefix-batch-wip-precheck 规格

## ADDED Requirements

### Requirement: 选批前脏文件重叠预检

code-fix 车道每轮选批后、批任务投递前，系统 SHALL 取主树 dirty tracked 文件集合与候选批条目的 file 字段求交（经产物判别排除 dist 类产物路径），作为选批预检。

### Requirement: 重叠整批推迟

预检命中时，系统 SHALL 跳过本轮选批并写 progress（running=False、phase=blocked、reason=wip_overlap_at_select、附交集文件文案），不投递批任务、不消耗实现预算；下一轮节拍自动重查。

### Requirement: 推迟可观测且不锁死

预检推迟 SHALL 纳入既有「选批为空」出口的 reason 分流文案体系；WIP 长期不清理时 SHALL 沿用既有 defer/预算降级语义收敛，SHALL NOT 无限空转重复推迟。

#### Scenario: WIP 重叠时整批推迟

- WHEN 主树未提交文件与候选批任一条目的 file 字段重叠（非产物路径）
- THEN 本轮不投递批任务，progress 写 wip_overlap_at_select 与交集文件文案，台账条目保持 open 待下轮

#### Scenario: 无重叠正常选批

- WHEN 交集为空
- THEN 选批与投递流程和现状完全一致

#### Scenario: 产物脏文件不误伤

- WHEN 交集仅含 dist 类产物路径（merge-time 闸门豁免的同一切分口径）
- THEN 不触发推迟，照常投递
