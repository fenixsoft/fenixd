## Why

`start_after`（定时拾取）门控的覆盖范围在过去两天内变了两次，两次行为都是**正确**的，
但当前硬编码只能二选一，用户无法按项目偏好选择：

- **旧行为（`fix-start-after-premature-pickup` 之前）**：`start_after` 只约束**实现派发**
  ——处于 `drafted` 的定时 SPEC 会被立即自动晋升（`drafted → ready`，或按方案评审分流
  `drafted → reviewing`），方案评审活动**立刻进行**；SPEC 只在真正派发实现时等到期。
  用户「提前看到评审结论」的需求正是靠这条路径满足的。
- **新行为（`fix-start-after-premature-pickup` 之后）**：`start_after` 同时约束**晋升与评审
  入口**——定时 SPEC 停留在 `drafted` 不动，直到到期/激活才晋升并起评审。

2026-09-18 该修复落地后，多个项目（依赖「先跑评审、到期再实现」节奏）失去了旧行为且
无配置开关可切回。两种节奏都合理：要不要让方案评审提前跑，是**项目级偏好**，应由用户决定。

## What Changes

- 新增配置键 `gates.start_after_scope`（枚举 `full` / `dispatch`，**缺省 `dispatch`**），
  控制 `start_after` 未到期（含哨兵 `manual`）的 SPEC 是否**同时**被按住晋升/评审入口：
  - `full`：晋升入口（`_on_spec_drafted`）、评审入口（`_on_spec_reviewing`）与恢复分支
    （`_recover_one` 的 `drafted` / `reviewing`）一并受 `start_after` 约束——SPEC 停留
    `drafted` 直到到期/激活（即当前 `fix-start-after-premature-pickup` 后的行为）。
  - `dispatch`（缺省）：`start_after` **只**约束实现派发链（`_on_spec_ready` /
    `_recover_ready` / 派发队列）——SPEC 照常立即晋升、立即跑方案评审，只有实现派发等到期
    （即修复前的旧行为）。
- 该参数**同时作用于定时值与 `manual` 哨兵**：`manual` 哨兵在 `dispatch` 档下也立即晋升并
  评审，随后停在 `ready` 等人工激活（派发口的 `start_after` 门始终在，manual 仍不会实现）。
- 该参数 MUST NOT 影响**实现派发口**（`_on_spec_ready` / `_recover_ready` / 派发队列筛选）：
  那些门是无条件语义（`start_after` 的本职），与「是否提前晋升/评审」正交。
- 设置页「审批」页签新增一个单选控件（`ApprovalModePanel`），与 `promote_mode` /
  `spec_review_mode` 并列；受管键读写、用户级→项目级同步、配置校验一并纳入。
- **行为变更（缺省值）**：未显式配置的项目回到**旧行为**（定时 SPEC 立即晋升并评审）。
  依赖 `fix-start-after-premature-pickup` 守持语义的项目 MUST 显式设 `start_after_scope: full`。

## Capabilities

### New Capabilities

- `start-after-scope-config`: 配置键 `gates.start_after_scope`（枚举 `full`/`dispatch`）的
  取值语义、缺省值、校验、受管键读写与设置页「审批」页签控件。

### Modified Capabilities

- `scheduled-spec-pickup`: 现有 Requirement「调度器对未到期 SPEC 跳过拾取」中关于
  **晋升入口 / 评审入口** 的覆盖从**无条件**改为**受 `gates.start_after_scope` 条件约束**
  （`full` 时覆盖，`dispatch` 时不覆盖）；实现派发口的覆盖仍无条件。

## Impact

- **配置层**：`core/config.py`（新增 `VALID_START_AFTER_SCOPES` + 校验 + `get_start_after_scope`
  getter）。
- **门控层**：`core/state_machine.py`（新增谓词 `start_after_blocks_promotion(entry, config)`，
  组合 `start_after_pending` 与 scope 判定）；`core/pm_engine/engine.py`
  （`_on_spec_drafted` / `_on_spec_reviewing` 两处守卫改经新谓词）；`core/event_bus.py`
  （`_recover_one` 的 `drafted` / `reviewing` 两处早退改经新谓词）。
- **Dashboard 后端**：`core/dashboard/data/config_admin.py`（`_SOURCE_KEYS` 来源标注、
  `read_config` / `read_effective_config` 回显、`_deep_merge_managed` 合并、`write_config`
  校验、`_SYNC_PAGE_KEYS['approval']` 同步白名单）。
- **Dashboard 前端**：`core/dashboard/static/src/services/dashboard.ts`（`GatesConfig` 类型）、
  `core/dashboard/static/src/pages/settings/components/ApprovalModePanel.tsx`（新增单选）；
  **需 `npm run build` 重出 `dist`**。
- **文档**：`docs/help/06-governance.md`（定时拾取小节补 scope 说明）、
  `docs/help/09-config.md`（`gates.*` 键表新增一条）。
- **测试**：`tests/test_config.py`（枚举校验/缺省/getter）、`tests/test_dashboard_api.py`
  （读写回显）、`tests/test_start_after_gate.py`（扩展：两档下 4 个门控点的行为 + 派发口
  不受 scope 影响 + 缺省等同旧行为）。
- **无破坏性**：`start_after` 为 null 的 SPEC 行为完全不变；实现派发口行为完全不变；
  仅「定时/哨兵 SPEC 的晋升与评审时机」按 scope 开关变化。
