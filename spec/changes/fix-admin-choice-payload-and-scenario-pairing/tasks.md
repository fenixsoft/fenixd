## Deliverables

```yaml
- path: core/dashboard/data/adjudication_choices.py
  kind: modify
- path: core/agent_runner/result_gate.py
  kind: modify
- path: core/agent_runner/maintenance_runs.py
  kind: modify
- path: core/admin_monitor.py
  kind: modify
- path: agents/administrator.md
  kind: modify
- path: tests/test_adjudication_choices.py
  kind: modify
- path: tests/test_dual_lane_adjudication.py
  kind: modify
- path: tests/test_global_signal_choice_guard.py
  kind: modify
- path: tests/test_admin_disposition_failure_context.py
  kind: modify
- path: tests/test_admin_prompt_choice_payload_contract.py
  kind: new
```

## 1. 注册表 requires_payload 单源

- [ ] 1.1 `core/dashboard/data/adjudication_choices.py`：`revise_scenario_reverify` 条目新增静态键 `requires_payload: True`（附注释说明载荷经处置记录 `choice_payload`/人工 note 传入）；未声明键的选项由消费侧按 `false` 缺省处理；新增模块级助手 `choice_requires_payload(choice_id, signal_type)`（内部走 `resolve_choice` 单源解析，choice 未注册/解析异常时兜底 `False`），扩展 `tests/test_adjudication_choices.py`：解析 `revise_scenario_reverify` 携带 `requires_payload=True`、未声明选项（如 `manual_fixed_reverify`）缺省 `False`、未注册 id 兜底 `False`。

## 2. AdminDisposition 载荷字段与透传

- [ ] 2.1 `core/agent_runner/result_gate.py`：`AdminDisposition` 新增 `choice_payload: str = ""` 字段并纳入 `to_dict`；`core/agent_runner/maintenance_runs.py` 处置记录读取构造点透传 `disp.get("choice_payload")`（缺键缺省空串，存量记录零迁移）；grep 核对 `AdminDisposition(` 全部构造点兼容（新字段带缺省不破坏既有构造）；`tests/test_admin_disposition_failure_context.py` 扩展：处置记录含 `choice_payload` → 字段与 final 记录到位、缺键 → 空串。

## 3. 缺载荷 fail-closed 硬门

- [ ] 3.1 `core/agent_runner/maintenance_runs.py`：既有两道处置产物硬门（未写处置文件 / result 非法）之后追加第三道——`success` 且 `choice_id` 非空且 `choice_requires_payload(choice_id, 本次 admin 信号 signal_type)` 为真且 `choice_payload` 缺空 → 折算失败（success=False、result 通道同步折算防透传），错误信息点名「该选项需要 choice_payload JSON 载荷（{"scenarios": [...], "reason": "...", "fixture_files": [...]}）」；`choice_payload` 存在时不做内容校验（非法载荷由执行器既有解析失败路径拒绝）；扩展 `tests/test_admin_disposition_failure_context.py`：缺载荷判失败且错误点名、合法载荷放行、非载荷选项无载荷照常放行（行为不变）。

## 4. 自动执行通道载荷优先

- [ ] 4.1 `core/admin_monitor.py` `_apply_choice_execution`：在既有 `resolve_choice` 作用域守卫处顺带读取 `requires_payload`——`choice_payload` 为空且选项必需 → 返回 not-ok skipped 形态（错误说明缺载荷、信号保留待重审），MUST NOT 调执行器制造必然失败日志；`choice_payload` 非空 → `note` 取 `choice_payload` 原文整体直传（MUST NOT 经 actions_taken 拼接或截断）；其余情况 `note` 维持 `actions_taken[:200]` 现状；扩展 `tests/test_global_signal_choice_guard.py` 与 `tests/test_dual_lane_adjudication.py`：载荷直达执行器（断言执行器收到 payload 原文）、缺载荷 skipped 不调执行器、非载荷选项 note 仍为依据文本三分支。

## 5. administrator 契约增补

- [ ] 5.1 `agents/administrator.md`：「裁决选项消费契约」段新增一条规则——需要修订场景定义或夹具供给层文件时，MUST 以 `choice_id=revise_scenario_reverify` + `choice_payload`（完整场景集 JSON：{"scenarios": [...], "reason": "...", "fixture_files": [...]}）提交，由执行器白名单路径成对写回 `test_scenarios.json` 与 `_scenarios_full.json`；MUST NOT 绕开执行器直接编辑场景定义文件、全量备份或夹具供给层文件（附理由：单独手改单侧文件破坏成对一致，旧定义可经「无理由缺场景补齐」分支回填复辟）；处置记录模板补 `choice_payload` 可选键说明；新增 `tests/test_admin_prompt_choice_payload_contract.py` 断言契约段含「choice_payload」「MUST NOT 直接编辑/手改」关键纪律句与模板键（防后续 prompt 改写静默丢失契约）。

## 6. 收尾回归

- [ ] 6.1 全量运行受影响测试族并全绿：`tests/test_adjudication_choices.py`、`tests/test_dual_lane_adjudication.py`、`tests/test_global_signal_choice_guard.py`、`tests/test_admin_disposition_failure_context.py`、`tests/test_admin_prompt_choice_payload_contract.py`，及 admin 处置链相邻族（test_admin.py、test_admin_orphan_disposition_effect_check.py）无回归。
