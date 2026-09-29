<!-- knowledge: capability=per-spec-impl-budget rev=1 sources=spec/archive/2026-09-15-add-spec-status-modal-budget -->

# 单 SPEC 实现预算覆盖

按 SPEC 覆盖实现尝试预算上限：STATE 属性 + 设置 API + 修改状态弹窗三件套，与全局预算共用同一解析口径。

## 现行规则

- STATE 条目可选属性 `impl_run_budget_override`：缺失或 null 时跟随全局 `agents.impl_run_budget`（全局配置及其设置页界面不变）；设为 1-10 整数时该 SPEC 的实现尝试预算以此为有效值。写入经 StateMachine 既有写路径（flock + 原子 rename），随既有 STATE watcher/SSE 增量路径流向前端，不引入新的同步机制。
- 闸门覆盖优先解析：per-spec 覆盖值（存在且可解析为整数）> 全局配置 `agents.impl_run_budget` > 模块缺省 `DEFAULT_IMPL_RUN_BUDGET`。覆盖值与全局值同口径夹紧到 1-10（越界夹紧、非整数忽略并回退下一优先级）。闸门全部调用点（预算计数递增日志、死亡 run 豁免日志、耗尽判定）使用同一解析结果；耗尽判定语义不变（used >= 有效预算 → 冻结 blocked + impl_budget_exhausted 告警，evidence 中 budget 为有效值），覆盖值只影响所在 SPEC，其余 SPEC 跟随各自的有效预算。
- 预算设置 API：`POST /api/spec-budget?project=<name>&spec=<name>`，请求体 `{"budget": <1-10 整数 | null>}`。spec 不存在 → 404；body 缺 budget 键 / 非整数 / 越界（0、11、浮点、字符串数字）→ 400 且 STATE 无任何变化；spec 为终态（done/pushed）→ 403；成功 → 200 + `{ok: true, budget: <值|null>}`，整数写入覆盖，null 清除覆盖恢复跟随全局。修改预算不重置 `_impl_run_budget_used` 已用计数（已用次数是对账组件的管辖）。
- SPEC 摘要暴露预算字段：`/api/specs` 列表项含 `budget_used`（当前已用计数）、`budget_override`（覆盖值或 null）、`budget_effective`（按闸门同源优先级解析的有效预算）；前端消费这三个字段，不在前端重复实现解析逻辑。
- 修改状态弹窗对未完成 SPEC（非 done/pushed）渲染预算区块：「已用 used / 有效预算 effective」展示、覆盖值输入（1-10 整数，当前覆盖预填；无覆盖时提示跟随全局及全局值口径）、保存调用预算设置 API、「恢复跟随全局」清除覆盖；操作成功后提示并刷新。终态 SPEC 的弹窗不渲染预算区块。

## 溯源

- [2026-09-15 add-spec-status-modal-budget](spec/archive/2026-09-15-add-spec-status-modal-budget/) — 确立 per-spec 预算覆盖属性、闸门覆盖优先解析口径、预算设置 API 的状态码契约、摘要三字段与弹窗预算区块
