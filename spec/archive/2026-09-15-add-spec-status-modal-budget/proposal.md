# add-spec-status-modal-budget

## Why

SPEC 列表页操作菜单随功能叠加已膨胀到 7 项（晋升 ready / 呼叫 Admin 介入 / 调整优先级 / 设置拾取时间 / 冻结管理 / 冻结·解冻 SPEC / 归档 SPEC / 删除 SPEC），状态相关操作（冻结、解冻、归档、晋升）散落在平级菜单项中，用户需要逐项辨识可用性。同时实现尝试预算（`agents.impl_run_budget`）是全局配置：单个反复失败的 SPEC 耗尽预算被冻结后，调大预算会波及所有 SPEC——缺少 per-spec 预算覆盖，无法只给问题 SPEC 多几次机会。

## What Changes

- **菜单收敛**：SPEC 列表「更多」操作菜单移除「晋升 ready」「冻结 SPEC / 解冻 SPEC」「冻结管理」「归档 SPEC」四组状态类菜单项，其功能全部合并入新增「修改状态」弹窗入口；保留「呼叫 Admin 介入」「调整优先级」「设置拾取时间」「删除 SPEC」。
- **修改状态弹窗**（按状态条件渲染操作区块）：
  - done/pushed 终态 → 提供「归档 SPEC」（沿用现有确认文案与 API）；
  - 未完成状态（非 done/pushed）→ 提供冻结操作区：未冻结时可冻结（永久）；已冻结时展示当前冻结模式（永久 / 定时解冻 + 目标时间）并支持立即解冻、切换永久↔定时（吸收原「冻结管理」弹窗全部能力）；
  - drafted → 提供「晋升 ready」（沿用现有晋升确认与 lint 违规展示）。
- **per-spec 实现尝试预算覆盖（新机制）**：
  - STATE.md 新增 per-spec 属性 `impl_run_budget_override`（null=跟随全局 `agents.impl_run_budget`）；
  - 预算闸门读取优先级：per-spec 覆盖优先（同口径夹紧 1-10），无覆盖回退全局配置；
  - 新增 API `POST /api/spec-budget`（设置 1-10 整数 / null 清除覆盖；终态拒绝）；
  - 「修改状态」弹窗对未完成 SPEC 展示预算区：已用次数 / 有效预算、覆盖值输入（1-10）、恢复跟随全局；
  - SPEC 摘要（`/api/specs` 列表项）新增 `budget_used` / `budget_override` / `budget_effective` 字段。
- 不改变冻结语义、归档语义、晋升 lint 门禁的既有行为——只改操作入口的组织方式与预算解析优先级。

## Capabilities

### New Capabilities

- `spec-status-actions-modal`: SPEC 列表操作菜单收敛与「修改状态」弹窗——按状态（终态/未完成/drafted/冻结态）条件提供归档、冻结（含永久↔定时切换与解冻）、晋升 ready 操作区块。
- `per-spec-impl-budget`: per-spec 实现尝试预算覆盖——STATE.md 属性、预算闸门「覆盖优先、全局兜底」解析、设置/清除 API、弹窗预算区展示与修改。

### Modified Capabilities

<!-- 无：spec/specs/ 当前无活跃 specs，既有相关能力（add-spec-archive、add-spec-scheduling-controls、add-draft-promotion-gate、add-fail-counter-budget）均已归档且需求行为不被修改，仅操作入口重组与预算解析新增优先级 -->

## Impact

- **前端**：`core/dashboard/static/src/pages/projects/list.tsx`（菜单重构 + 修改状态弹窗）；桌面 Table 与移动端 SpecCardList 共用 `specMenuItems`，自动一致；`core/dashboard/static/src/services/dashboard.ts`（新增 setSpecBudget）。
- **后端 API**：`core/dashboard/server.py`（新增 `/api/spec-budget` 路由）；`core/dashboard/data.py`（新增 `set_spec_budget`；`spec_summary` 增加 3 个预算字段）。
- **预算闸门**：`core/pm_engine/budget.py`（`_impl_run_budget` 接受 spec_name，per-spec 覆盖优先；3 处调用点补参）。
- **状态文件**：`.fenix/STATE.md` per-spec 新属性 `impl_run_budget_override`（经 `StateMachine.update_spec` 写入，随既有 watcher/SSE 增量路径流向前端，与 `start_after`/`frozen_until` 同构）。
- **测试**：`tests/test_dashboard_data.py` / `tests/test_dashboard_api.py` / `tests/test_dashboard_freeze.py` / `tests/test_spec_scheduling.py` 既有模式扩展；预算闸门测试覆盖覆盖优先与回退语义。
- **不涉及**：冻结/解冻/归档/晋升的后端语义与门禁逻辑、全局 `agents.impl_run_budget` 配置项及其设置页界面（TokenBudgetPanel 保持不变）。
