# scenario-defect-reroute-stoploss

## ADDED Requirements

### Requirement: 改道止损判据

场景缺陷改道门改道重派 judge 后，MUST 把重跑失败场景集与改道前失败场景集对比：同批失败（失败集相同或完全包含）时 MUST 判定「改道无效」并提前止损升级人工（human-escalation-alert scenario_defect_reroute_stoploss），MUST NOT 继续消耗 _repair_depth 预算；失败集发生变化（任一失败场景修复或新增）时 MUST 继续走既有改道预算通道。

#### Scenario: 改道后仍同批失败提前止损

- **WHEN** 改道重派 judge 后重跑失败场景集与改道前完全相同
- **THEN** 立即升级人工并留 human-escalation-alert，不等待 _SCENARIO_REPAIR_MAX_ROUNDS 耗尽

#### Scenario: 改道有进展继续预算

- **WHEN** 改道重派后失败场景集发生变化（有场景修复）
- **THEN** 继续走既有改道预算通道，预算耗尽仍升级人工

### Requirement: 跨轮失败集留存

改道前失败场景集 MUST 持久化到 spec 级 verify-progress 状态（.fenix/verify-progress/<spec>/），供改道重跑后对比；留存包含失败场景 id 列表与归属轮次。

#### Scenario: 失败集跨轮可见

- **WHEN** 改道门触发且改道重派完成后
- **THEN** 重跑失败集可与改道前失败集对比，判定同批与否