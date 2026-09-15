# per-spec-impl-budget 规格

## ADDED Requirements

### Requirement: per-spec 预算覆盖属性

每个 SPEC 在 STATE.md 的条目 MUST 支持可选属性 `impl_run_budget_override`：

- 缺失或 null：该 SPEC 跟随全局预算 `agents.impl_run_budget`（现有配置项及其设置页界面不变）；
- 设为 1-10 整数：该 SPEC 的实现尝试预算以此为有效值。

写入 MUST 经 StateMachine 既有写路径（flock + 原子 rename），与 daemon 并发写安全；该属性随既有 STATE watcher/SSE 增量路径流向前端（与 `start_after` / `frozen_until` 同构），MUST NOT 引入新的同步机制。

#### Scenario: 无覆盖时跟随全局

- **WHEN** SPEC 条目无 `impl_run_budget_override` 或其为 null，全局配置 `agents.impl_run_budget` 为 6
- **THEN** 该 SPEC 的有效实现尝试预算为 6

#### Scenario: 设置覆盖后按覆盖值生效

- **WHEN** SPEC 的 `impl_run_budget_override` 被设为 8，全局配置为 6
- **THEN** 该 SPEC 的有效实现尝试预算为 8，其余 SPEC 仍为 6

### Requirement: 预算闸门覆盖优先解析

实现尝试预算闸门（`ImplBudget._impl_run_budget`）MUST 按以下优先级解析有效预算：

1. per-spec 覆盖值（`impl_run_budget_override`）存在且可解析为整数 → 使用之；
2. 否则回退全局配置 `agents.impl_run_budget`；
3. 全局配置缺失或非法 → 模块缺省 DEFAULT_IMPL_RUN_BUDGET。

覆盖值与全局值同口径夹紧到 1-10（越界夹紧、非整数忽略并回退下一优先级）。闸门全部调用点（预算计数递增日志、死亡 run 豁免日志、耗尽判定）MUST 使用同一解析结果；耗尽判定语义不变（used >= 有效预算 → 冻结 blocked + 告警），仅预算来源增加覆盖优先级。

#### Scenario: 覆盖值越界夹紧

- **WHEN** SPEC 的 `impl_run_budget_override` 被写为 0、11 或非整数
- **THEN** 闸门不使用该非法值：0 与 11 夹紧为 1 与 10（与全局同口径），非整数回退全局

#### Scenario: 耗尽判定按有效预算触发

- **WHEN** SPEC 有效预算为 8（覆盖值），`_impl_run_budget_used` 达到 8
- **THEN** 派发前耗尽判定触发：SPEC 冻结为 blocked 并发送 impl_budget_exhausted 告警，告警 evidence 中的 budget 为 8

#### Scenario: 覆盖值只影响本 SPEC

- **WHEN** SPEC A 覆盖预算为 2，SPEC B 无覆盖（全局 6）
- **THEN** SPEC A 在 used 达 2 时冻结，SPEC B 在 used 达 6 时冻结，互不影响

### Requirement: 预算设置 API

新增 `POST /api/spec-budget?project=<name>&spec=<name>` 端点，请求体 `{"budget": <1-10 整数 | null>}`：

- spec 不存在 → 404；
- body 缺 budget 键 / 非整数 / 越界（0、11、浮点、字符串数字）→ 400；
- spec 为终态（done/pushed）→ 403 拒绝（终态修改预算无意义）；
- 成功 → 200 + `{ok: true, budget: <值|null>}`：整数写入覆盖，null 清除覆盖（属性置 null，恢复跟随全局）。

修改预算 MUST NOT 重置 `_impl_run_budget_used` 已用计数（已用次数是对账组件的管辖，本能力只改预算上限）。

#### Scenario: 设置与清除覆盖

- **WHEN** 对未完成 SPEC 依次请求 budget=3、budget=null
- **THEN** 第一次返回 200 且 effective 预算变为 3；第二次返回 200 且属性为 null、恢复跟随全局

#### Scenario: 非法请求被拒绝

- **WHEN** 请求体为 `{"budget": 0}`、`{"budget": 11}`、`{"budget": "5"}`、`{}` 或浮点值
- **THEN** 返回 400，STATE.md 不发生任何变化

#### Scenario: 终态 SPEC 拒绝修改

- **WHEN** 对 done 或 pushed 的 SPEC 请求设置预算
- **THEN** 返回 403，STATE.md 不发生任何变化

### Requirement: SPEC 摘要暴露预算字段

`/api/specs` 列表项（spec_summary）MUST 新增三个字段：

- `budget_used`：该 SPEC 当前 `_impl_run_budget_used`（整数，缺省 0）；
- `budget_override`：覆盖值（1-10 整数或 null）；
- `budget_effective`：按闸门同源优先级解析的有效预算（覆盖 > 全局 > 缺省）。

前端展示 MUST 消费这三个字段，MUST NOT 在前端重复实现解析逻辑。

#### Scenario: 摘要字段与闸门口径一致

- **WHEN** SPEC 覆盖为 8、used 为 5，全局为 6
- **THEN** 该 SPEC 列表项 budget_used=5、budget_override=8、budget_effective=8

### Requirement: 修改状态弹窗预算区块

修改状态弹窗对未完成 SPEC（非 done/pushed）MUST 渲染预算区块：

- 展示「已用 used / 有效预算 effective」（消费摘要字段）；
- 覆盖值输入（1-10 整数，含当前覆盖预填；无覆盖时提示跟随全局及全局值口径）；
- 保存调用预算设置 API；「恢复跟随全局」操作清除覆盖（budget=null）；
- 操作成功后提示并刷新，used 与有效预算随新数据更新。

终态 SPEC 的弹窗 MUST NOT 渲染预算区块。

#### Scenario: 修改覆盖并生效展示

- **WHEN** 对 used=5、跟随全局（6）的未完成 SPEC 在弹窗中输入 3 并保存
- **THEN** 保存成功后预算区显示已用 5 / 有效预算 3；该 SPEC 后续按 3 的预算触发耗尽冻结

#### Scenario: 恢复跟随全局

- **WHEN** 对覆盖为 3 的 SPEC 点击「恢复跟随全局」
- **THEN** 覆盖清除，预算区显示已用 used / 全局有效预算

#### Scenario: 终态不渲染预算区块

- **WHEN** 对 done 或 pushed 的 SPEC 打开修改状态弹窗
- **THEN** 弹窗无预算区块
