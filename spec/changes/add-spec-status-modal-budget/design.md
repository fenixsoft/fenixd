# add-spec-status-modal-budget 设计

## Context

SPEC 列表页（`core/dashboard/static/src/pages/projects/list.tsx`）的「更多」菜单经多轮叠加（add-draft-promotion-gate、add-spec-scheduling-controls、add-spec-archive）已有 7+ 项，状态类操作可用性靠 disabled 位表达，用户辨识成本高。实现尝试预算自 add-fail-counter-budget 起为全局配置 `agents.impl_run_budget`（`core/pm_engine/budget.py` `ImplBudget._impl_run_budget()` 读 config，夹紧 1-10），per-spec 仅有已用计数 `_impl_run_budget_used`；预算耗尽冻结（blocked + impl_budget_exhausted 告警）后的人工出路是调大全局预算+解冻，波及面过大。

本变更两线并进：UI 收敛（纯入口重组，后端零新语义）与 per-spec 预算覆盖（新机制：STATE 属性 + 闸门解析优先级 + API + UI）。用户已确认口径：done/pushed 均可归档；冻结操作（含原「冻结管理」永久↔定时切换与解冻）全部并入弹窗；独立「晋升 ready」菜单移除；full 模式。

## Goals / Non-Goals

- **Goals**：
  1. 状态类操作收敛进「修改状态」弹窗，按状态条件渲染，零新状态语义；
  2. per-spec 预算覆盖：覆盖优先、全局兜底，与现有闸门口径（1-10 夹紧、耗尽冻结、对账）完全兼容；
  3. 桌面/移动端一致。
- **Non-Goals**：
  - 不改冻结/解冻/归档/晋升的后端行为与门禁；
  - 不改全局 `agents.impl_run_budget` 配置项与设置页 TokenBudgetPanel；
  - 不做 `_impl_run_budget_used` 重置（对账组件 `_reconcile_impl_budget` 管辖，不越界）；
  - 不做预算字段在列表列的展示（只在弹窗内）。

## Decisions

### D1 弹窗为单 Modal 分区块组件，复用既有 API

新组件 `SpecStatusModal`（`pages/projects/components/SpecStatusModal.tsx`），受控 props：`project` / `spec` / `open` / `onClose` / `summary`（SpecSummary，含新增预算字段）/ `onDone`（成功后触发父级刷新）。区块条件渲染：

| 区块 | 条件 | 交互 |
|------|------|------|
| 归档 | `done/pushed` | 沿用 `handleArchiveSpec` 的确认文案与 `archiveSpec` API |
| 冻结 | 非 done/pushed | 未冻结：「冻结」确认按钮（`freezeSpec`）；已冻结：模式展示 + 「立即解冻」（`setSpecFreezeConfig 'unfreeze'`）+ 永久↔定时切换（`setSpecFreezeConfig 'permanent'/'scheduled'`），交互对齐现「冻结管理」弹窗 |
| 晋升 | `drafted` | 确认文案沿用 `handlePromoteSpec`，调 `promoteSpec`，lint 违规 `result.violations` 明细展示 |
| 预算 | 非 done/pushed | 见 D3 |

理由：全部走既有端点（freeze/unfreeze/archive/promote/freeze-config），后端只新增预算一个端点，风险最小。被收敛的旧菜单处理函数（handleFreezeToggle/handlePromoteSpec/handleArchiveSpec/openFreezeManage 一族）迁移为弹窗内部逻辑，list.tsx 删除对应孤儿代码与「冻结管理」Modal。

### D2 菜单结构

`specMenuItems` 产出：`修改状态`（key `status`）→ `admin` → `priority` → `pickup-time` → divider → `delete`。已归档视图分支保持现状（divider + delete）。终态置灰仅作用于 priority/pickup-time（现状语义）；「修改状态」终态仍可点（归档区块可用）。`onSpecMenu` 新增 `status` 分支打开弹窗。

### D3 per-spec 预算：STATE 属性 + 闸门解析

- 属性名 `impl_run_budget_override`（不带下划线前缀：人工管理属性，与 `priority`/`start_after` 同类；下划线前缀保留给框架私有字段 `_impl_run_budget_used` 等）。
- `ImplBudget._impl_run_budget()` 签名改为 `_impl_run_budget(spec_name: str | None = None)`：spec_name 非空时读 `read_one(spec_name)` 的覆盖值——可解析为 int 则同口径夹紧 1-10 使用；None/非法/缺失回退全局 config 链（现状逻辑）。全库仅 3 个调用点（`_increment_impl_run_budget_used`、`_exempt_dead_run_budget`、`_check_impl_budget_exhausted`），全部补传 spec_name。闸门冻结文案与告警中的 budget 自然变为有效预算，无需额外改动。
- API `POST /api/spec-budget`（server.py，模式对齐 `_api_spec_priority`）：404 not found / 400 缺键或非法（`isinstance(int) and not isinstance(bool)` 且 1-10，null 合法）/ 403 终态 / 200 `{ok, budget}`。data.py 新增 `set_spec_budget(project_root, spec, budget)`，经 `StateMachine.update_spec` 写属性，返回形状对齐 `set_spec_start_after`。
- spec_summary 新增 `budget_used`（读 `_impl_run_budget_used`，int(entry.get(..., 0)) 容错）/ `budget_override`（读覆盖属性，容错非法为 None）/ `budget_effective`（与闸门同源：优先覆盖夹紧、回退全局 config、再回退 DEFAULT；data.py 读全局 config 走 dashboard 侧 config 读取器，夹紧逻辑与 budget.py 口径一致）。前端不重复实现解析。

### D4 冻结态判定复用 isFrozen

前端冻结态判定沿用 `record.status === 'blocked' && error.startsWith('用户指令冻结：')`（list.tsx `isFrozen`）；非冻结 blocked（如预算耗尽冻结）在冻结区块显示「冻结」操作（可再冻结属幂等 no-op 由后端兜底）且预算区块照常可用——预算耗尽冻结正是本能力的主要场景：调大覆盖 → 解冻 → 恢复调度，弹窗内闭环。

### D5 摘要增量与刷新

预算字段随 `spec_summary` 既有增量路径（SummaryIndex 签名含 STATE.md，SSE state 事件 patch 单行）自动更新，弹窗打开期间以父级传入 summary + 操作后 `onDone` 刷新为准，不为弹窗单开轮询。

## Risks / Trade-offs

- **[闸门口径漂移]** budget.py 与 data.py 两处解析若各写一份夹紧逻辑可能漂移 → 夹紧单点抽为模块级纯函数（budget.py 导出），data.py 引用同一实现。
- **[Modal 内多操作确认嵌套]** 冻结/归档/晋升均带确认弹窗，弹窗叠弹窗 → 确认改为弹窗内二次点击态（按钮 danger + 文案明示后果）或 antd Modal.confirm 层级（zIndex 递增），实现取其一，场景验收以「无误触」为准。
- **[移动端空间]** 预算区 + 冻结区 + 操作按钮在小屏堆叠 → 区块用 Card/Divider 分隔、字段单列，移动端验收走 useIsMobile 分支。

## Migration Plan

纯增量：新属性缺省 null 语义等于「跟随全局」，存量 STATE.md 无需迁移；旧菜单项直接移除（无外部 API 消费方）。

## Open Questions

- 无（执行模式 full、归档口径 done/pushed、冻结全并入、晋升菜单移除均已经用户确认）。
