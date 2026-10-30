# specs/code-review-fix-pacing/spec.md

## ADDED Requirements

### Requirement: 发现分级处置门限

code-review-fix 车道 SHALL 按发现的 severity 分流处置：severity 达到 min_immediate_severity（缺省 major）的条目保持既有当日批序；低于门限的条目（minor/info）延后累积，仅在 minor_batch_cadence（天数，缺省 7）定义的周批窗口进入修复批。分级门限 SHALL NOT 作用于 category 以 `regression-` 为前缀的回归来源条目——回归复发保持既有当日重修语义（add-regression-auto-fix）。

#### Scenario: 回归来源条目豁免门限

- **WHEN** 一轮选批同时含 code-review 来源 minor 条目与 regression- 来源复发条目
- **THEN** regression- 来源条目照常进入当日批
- **AND** 仅 code-review 来源 minor/info 条目被挂起

#### Scenario: 混合严重度选批分流

- **WHEN** 一轮评审产出含 major 与 minor 两类 open 发现且触发 code-fix
- **THEN** 当日批只纳入 major 以上条目
- **AND** minor/info 条目保持 open 且带 deferred 标记，不进入当日批

#### Scenario: 周批晋级

- **WHEN** 距上次 minor/info 批达到 minor_batch_cadence 窗口
- **THEN** 累积的 deferred 条目按既有批序规则进入当批
- **AND** 批完成后 deferred 标记清除

### Requirement: 双入口同门

候选筛选规则 SHALL 在 code_review.py generate_fix_spec 与 code_fix.py 选批两处同源生效，Dashboard 手工触发的修复通道不得绕过分级门限。

#### Scenario: 手工通道绕过被拒

- **WHEN** 通过 Dashboard 手工通道对纯 minor/info 的 open 集合触发修复批且未到周批窗口
- **THEN** 该触发按空批处理并说明原因

### Requirement: deferred 与链收敛对账

deferred 条目 SHALL NOT 被链收敛判据（chain_skipped 对账与链末批判定）误判为 skipped/lost；同一指纹在 deferred 期间被再次报出 SHALL 沿既有台账 upsert 合并分支（core/code_review.py upsert_findings）刷新而非新增，分级门限 MUST NOT 引入重复立项路径。severity 挂起台账 MUST 与既有 WIP-defer 延迟合回台账（core/code_fix.py fix-deferred.json / _deferred_item_ids / first_deferred_at）保持独立命名与独立载体，互不串写。

#### Scenario: deferred 不误判收敛

- **WHEN** 某 minor 条目处于 deferred 态且其修复链尚未建立
- **THEN** 链收敛统计不将其计为 skipped/lost
- **AND** 同指纹后续轮次的重复发现合并到原条目

### Requirement: 门限配置回退缺省

admin.code_review_fix.min_immediate_severity 与 minor_batch_cadence SHALL 沿既有严格校验+回退缺省范式：非法值回退缺省（major / 7）并告警，不阻断评审与修复主链。

#### Scenario: 非法配置回退

- **WHEN** 配置写入 min_immediate_severity: critical（非 severity 词表值）
- **THEN** 读取器回退缺省 major 并留一条配置告警
- **AND** 当日评审与修复链不受阻
