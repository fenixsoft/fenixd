# scenario-defect-reroute-stoploss

## ADDED Requirements

### Requirement: 改道止损判据

场景缺陷改道门在**改道重入轮**（`_repair_depth >= 1` 且留存记录轮次与 `_repair_depth - 1` 匹配）的门触发入口，MUST 把重跑失败场景集与改道前失败场景集对比：改道前失败集为重跑失败集的子集（含相等，即无任一改道前失败场景被修复）时 MUST 判定「改道无效」并提前止损升级人工（human-escalation-alert scenario_defect_reroute_stoploss），MUST NOT 继续消耗剩余 _repair_depth 预算；存在改道前失败场景已不在重跑失败集中（有场景被修复）时 MUST 继续走既有改道预算通道。链首触发（`_repair_depth == 0`）MUST NOT 做同批判定（只写留存、照常走既有改道通道）。

#### Scenario: 改道重入后仍同批失败提前止损

- **WHEN** 改道重入轮重跑失败场景集包含改道前全部失败场景（含完全相同）
- **THEN** 立即升级人工并留 human-escalation-alert，不等待 _SCENARIO_REPAIR_MAX_ROUNDS 耗尽、不再重派 judge

#### Scenario: 改道有进展继续预算

- **WHEN** 改道重入轮重跑失败场景集中有改道前失败场景已被修复（改道前失败集不再是重跑失败集的子集）
- **THEN** 覆盖留存后继续走既有改道预算通道，预算耗尽仍升级人工

#### Scenario: 链首触发的陈旧留存不误停

- **WHEN** 全新验证轮（`_repair_depth == 0`）的门触发读到上一链条遗留的留存且失败集与之相同
- **THEN** 不做同批判定，写入留存并照常走既有改道通道（MUST NOT 直接升级人工）

### Requirement: 跨轮失败集留存

改道门 MUST 把改道前失败场景集持久化到 spec 级 verify-progress 状态（`.fenix/verify-progress/<spec>/scenario_reroute_stoploss.json`），供改道重入轮的门触发入口比对；留存 MUST 含失败场景 id 列表、写入时的 _repair_depth 轮次与写入时间。读取缺失/损坏/结构不符/轮次不匹配时 MUST 保守放行（不因本机制误停）。

#### Scenario: 失败集跨轮可见

- **WHEN** 改道门触发（写入）且改道重入重跑后下次门触发（读取）
- **THEN** 重跑失败集可与改道前失败集对比，判定同批与否
