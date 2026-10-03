# maintree-wip-attribution 规格

## ADDED Requirements

### Requirement: 主树活交互会话归因源
identify_wip_occupant SHALL 在既有在飞车道归因零命中时，尝试只读的「主树活交互会话」探测（会话注册/锁文件、最近提交人识别等只读信号），命中时把主树直改散件归因到该会话。

#### Scenario: 活交互会话直改主树
- **WHEN** 主树 tracked 散件的修改来自仍在活跃的交互会话且车道归因零命中
- **THEN** 归因结果标注该会话线索（非「无主」），maintree_stray_wip_stale 盘点侧对这类散件降级为 info 留痕，不派 major 告警、不触发 admin 代查

#### Scenario: 探测源缺失或零命中
- **WHEN** 无活跃会话信号可读或探测零命中
- **THEN** 行为与现状一致（按无主走既有宽限升级），不新增误报、全程无主树写入

### Requirement: 归因输出消费同步
新的会话归因输出 SHALL 对既有归因消费者（stray_wip 盘点、code_fix defer 告警）透明生效，各消费者不得复制探测逻辑。

#### Scenario: 多消费者同步受益
- **WHEN** identify_wip_occupant 返回活会话归因
- **THEN** stray_wip 与 code_fix 两处告警 evidence 均携带同一会话归因文本

### Requirement: 降级行为可配置回退
会话归因散件的「降级不派 major 告警」SHALL 提供配置开关回退为既有行为，防止误放真实滞留。

#### Scenario: 配置回退
- **WHEN** 配置将降级行为回退为 keep
- **THEN** 会话归因散件与无主散件走同一宽限升级路径（现状行为）