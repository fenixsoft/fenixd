# tasks — manual-intervention/verify_env_blocked 信号桶注册 revise_scenario_reverify

## 1. 注册表增量（core/dashboard/data/adjudication_choices.py）

- [ ] 1.1 把 `inconclusive_loop` 桶内联的 `revise_scenario_reverify` 条目（233-256 行，含其上注释块）原字提取为模块级常量 `_REVISE_SCENARIO_REVERIFY`，置于既有选项常量区（`_MANUAL_FIXED_REVERIFY` 之后）。
- [ ] 1.2 `inconclusive_loop` 元组改为引用 `_REVISE_SCENARIO_REVERIFY`（字段逐字不变，行为零变化）。
- [ ] 1.3 新增 `"manual-intervention": (_REVISE_SCENARIO_REVERIFY,)` 与 `"verify_env_blocked": (_REVISE_SCENARIO_REVERIFY,)` 两桶（`redispatch_loop_detected` 桶之后就近 placement），附桶头注释（立项来源：2026-10-30 / 2026-11-03 两次实弹事故 + 本 SPEC）。
- [ ] 1.4 确认模块 import 期 `_assert_registry_consistency` 通过（三桶同 id 四元组一致，无 AssertionError）。

### Deliverables

- `core/dashboard/data/adjudication_choices.py`：`_REVISE_SCENARIO_REVERIFY` 常量 + 两新桶 + `inconclusive_loop` 引用化

## 2. 测试扩展（tests/test_adjudication_choices.py）

- [ ] 2.1 正解断言：`resolve_choice("revise_scenario_reverify", "manual-intervention")` 与 `resolve_choice("revise_scenario_reverify", "verify_env_blocked")` 各返回 (dict 拷贝, "")，且 `requires_payload=True`、`spec_scoped=True`。
- [ ] 2.2 三桶等值断言：`inconclusive_loop` / `manual-intervention` / `verify_env_blocked` 三 signal_type 解析返回的选项 dict 逐项相等（跨桶单源不漂移）。
- [ ] 2.3 负向控制：未注册信号解析该 id 仍 `(None, "scoped-no-reverse")`；已注册桶（如 spec-review-rejected）内解析该 id 仍 `(None, "not-in-bucket")`。
- [ ] 2.4 `choice_requires_payload("revise_scenario_reverify", <两新 signal_type>)` 均为 True。

### Deliverables

- `tests/test_adjudication_choices.py`：新增用例

## 3. 回归验收

- [ ] 3.1 `pytest tests/test_adjudication_choices.py` 全量通过（含既有 inconclusive_loop / not-in-bucket / scoped-no-reverse 用例零变化）。
- [ ] 3.2 相邻契约回归全绿：`pytest tests/test_env_scenario_revision_exit.py tests/test_admin_prompt_choice_payload_contract.py tests/test_global_signal_choice_guard.py tests/test_dual_lane_adjudication.py`。

### Acceptance

- [ ] `resolve_choice("revise_scenario_reverify", "manual-intervention")` 命中且 requires_payload=True
- [ ] `resolve_choice("revise_scenario_reverify", "verify_env_blocked")` 命中且 requires_payload=True
- [ ] 上述测试文件全量通过；模块 import 自检（`_assert_registry_consistency`）无 AssertionError
