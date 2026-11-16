## Deliverables

```yaml
- path: core/dashboard/data/adjudication_choices.py
  kind: modify
- path: core/admin_choice_exec.py
  kind: modify
- path: core/admin_monitor.py
  kind: modify
- path: tests/test_admin_direct_exclusive_choice_guard.py
  kind: new
```

## 1. 执行边界收口

- [x] 1.1 core/dashboard/data/adjudication_choices.py：新增 `is_human_exclusive_choice(choice_id)` 助手，对 `ADMIN_CHAIN_EXCLUDED_CHOICE_IDS` 做 strip 归一化成员判断；把常量头注从「链上 Admin 拍板面排除集」改为「全部 agent 驱动通道的执行排除集」，链侧复核与执行机器守卫共用本单源。
- [x] 1.2 core/admin_choice_exec.py：在 `execute_choice_for_disposition` 解析出 choice_id 之后、调用 `execute_adjudication_choice` 之前插入守卫；命中排除集时记 ERROR 日志并返回 `{"ok": False, "skipped": True, "action": choice_id, "steps": [], "error": "choice 越界（人类拍板面专属）: <choice_id>，agent 通道拒绝执行"}`，不进入后续执行与陈旧代码预检分支。
- [x] 1.3 core/admin_monitor.py：直派消费侧识别上述拒绝形态（skipped=True 且 error 含「人类拍板面专属」），为 disposition 记 `handoff_reason` 并跳过终态回写（不写 handled/resolved），与链路径 chain-handoff 同口径。落点约定：handoff_reason 写 `AdminDisposition.handoff_reason` 属性（core/agent_runner/result_gate.py dataclass 已有该字段）+ ERROR 日志；`append_admin_final` 落账 schema 不扩字段（不引入 admin_store.py 改动）——落盘文本留痕经既有 fail-closed 通道天然覆盖（choice_failed 时 final_error_note 已把守卫 error 文案并入落账 error 字段）。
- [x] 1.4 确认人工通道零改动：`core/dashboard/routes/alert_routes.py:640` 与 `execute_adjudication_choice` 的默认行为保持原样，并在测试中显式断言人工路径可执行 grant_env_exemption。

## 2. 测试

- [x] 2.1 tests/test_admin_direct_exclusive_choice_guard.py：覆盖「agent 通道 × 人类专属 choice」矩阵——直派通道对 grant_env_exemption/abandon 返回 ok=false+skipped=true 且未调用 execute_adjudication_choice；对 revise_scenario_reverify 等非排除项正常放行；人工 alert-resolve 路径对 grant_env_exemption 仍成功；拒绝时信号不回写 handled/resolved。
- [x] 2.2 tests/test_admin_direct_exclusive_choice_guard.py：覆盖 handoff 留痕——直派拒绝后 AdminDisposition 的 handoff_reason 属性含「人类拍板面专属」（断言落点为 disp 对象属性与落账记录 error 文本；落账 schema 无 handoff_reason 字段、不按字段断言），且 STATE 的 `_env_exemptions` 未被写入。
- [x] 2.3 回归既有守卫：确认 tests/test_escalation_chain.py 的 `test_out_of_allowlist_choice_still_hands_off` 与 tests/test_global_signal_choice_guard.py 全绿（链侧行为零变化）。
