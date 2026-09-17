## Why

空 spec 目录（`spec/changes/<spec>/` 无实质内容）仍会被派发 implementer 盲目实现、烧满实现预算后才被预算闸门拦下。scheduling-showcase 夹具已实证：c-sched-set / c-sched-clear 两条空占位 spec 各盲跑 6 个 implementer run（共 12 个）后才被 `impl_budget_exhausted` 冻结。派发路径上只有「次数」维度的闸门，缺「内容」维度闸门，任何真实项目的空 spec 目录都能这样烧穿整档预算。

## What Changes

- 新增派发前「内容完整性闸门」：implementer / fast-track 派发前校验 `spec/changes/<spec>/` 是否存在实质内容；缺失即中止派发，置 blocked + 冻结 + human-escalation 告警（signal_type=`spec_content_missing`）。
- 新增纯函数 `spec_has_content(project_root, spec_name)` 判定实质内容：目录存在且含 `proposal.md` / `design.md` / `tasks.md` / `specs/*.md` 任一，否则视为空；读目录 IO 异常保守放行（记 WARNING，不误伤）。
- `alert_lifecycle._SIGNAL_CONDITIONS` 注册 `spec_content_missing`，映射到既有 `spec_terminal_or_unblocked` 闭环条件，使告警在 spec 补内容解冻后自动 resolve。
- **无** dashboard UI、**无**数据迁移、**无**新配置键（纯正确性防护，不加开关）。

## Capabilities

### New Capabilities
- `spec-content-integrity-gate`: 派发前对 spec 目录做实质内容校验，空 spec 中止派发并冻结告警；读目录异常保守放行；告警接入生命周期闭环。

### Modified Capabilities
<!-- 无 requirement 级修改：fail-counter-budget（已归档）的预算闸门语义不变，本能力只在其
     派发前并列新增一道内容维度闸门，不改预算计数逻辑。 -->

## Impact

- **core/pm_engine/dispatch.py**：implementer / fast-track 两个派发分支各加一次闸门校验（与 `_check_impl_budget_exhausted` 同层）。
- **新文件 core/pm_engine/spec_integrity.py**（或挂接 budget.py）：`spec_has_content` 判定 + 闸门封装。
- **core/alert_lifecycle.py**：`_SIGNAL_CONDITIONS` 新增一个映射项。
- **tests/**：新增单测（判定函数各形态 + 闸门命中集成断言）。
- 不改 verifier 分支；不改 `_seed_spec` 的 non-fatal 语义。