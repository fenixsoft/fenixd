# 任务：add-blocked-reverify-lane

## Deliverables

```yaml
- path: core/state_machine.py
  kind: modify
- path: core/pm_engine/verification.py
  kind: modify
- path: core/admin_monitor.py
  kind: modify
- path: core/agent_runner/prompt_builder.py
  kind: modify
- path: tests/test_blocked_reverify_gate.py
  kind: new
```

## 1. 状态机：GATE_TRANSITIONS 扩展与字段常量化

- [ ] 1.1 `core/state_machine.py`：`GATE_TRANSITIONS` 增加 `SpecStatus.BLOCKED: [SpecStatus.TESTING]`（含注释：仅 admin 处置收尾自动路径可用，复用 D7 逃生门约束语义；人工路径 `transition()` 仍受 VALID_TRANSITIONS 拒绝）
- [ ] 1.2 `core/state_machine.py`：字段名单区新增 `ENV_BLOCK_ROUNDS_FIELD = "_env_block_rounds"` 常量（IMPL_RUN_BUDGET_USED_FIELD 同款注释风格，注明唯一清零点=verified 落定与 unfreeze_spec）
- [ ] 1.3 `core/state_machine.py` `unfreeze_spec()`：updates 字典并入 `ENV_BLOCK_ROUNDS_FIELD: 0`（与 `_verify_redo_count`/`_inconclusive_attempts` 同一原子写，docstring 补充清零语义）
- [ ] 1.4 确认 `transition_gate()` 无需改动即支持新转换对（幂等短路、GATE_TRANSITIONS 查表逻辑通用）；如实现有 BLOCKED 特化假设则修正

## 2. 升级通道：清零点收敛与复位判定

- [ ] 2.1 `core/pm_engine/verification.py`：`_escalate_env_blocked` 与两处 verified 落定清零点改引 `ENV_BLOCK_ROUNDS_FIELD` 常量（行为不变，仅消除字符串漂移）
- [ ] 2.2 `core/pm_engine/verification.py`：新增复位判定辅助方法（输入 spec entry：守卫链=env 族信号、status=blocked 且非人工冻结、branch 非空、`git merge-base --is-ancestor` 合并判定（project_root 执行、subprocess timeout、异常按未合并）；返回 "testing" | "ready"）
- [ ] 2.3 `core/pm_engine/verification.py`：`verify_env_blocked` 自动呼叫提示词文本修订——声明处置范围限于环境修复、「框架将在处置收尾自动触发重验证，不要手动 reset spec 状态」
- [ ] 2.4 全库 grep `_env_block_rounds` 字符串字面量残留，清零点外无任何写入 0 的路径（处置复位/恢复/fix 链不动该字段）

## 3. 处置收尾：消费点接入直通道

- [ ] 3.1 `core/admin_monitor.py`：处置收尾消费点（disposition result ∈ resolved/partially-resolved 摄取处）接入复位判定——env 族信号 + 守卫通过 → `transition_gate(spec, "testing")` + 清 error（保留 rounds）+ `pm_engine.handle_event("spec_implemented", spec)` 入队重验；守卫不过 → 既有 `transition(spec, "ready")` + 清 error
- [ ] 3.2 `core/admin_monitor.py`：`verify_env_blocked` 信号的建议文本与处置提示同步 2.3 措辞（不再引导 admin 手动复位）
- [ ] 3.3 `core/agent_runner/prompt_builder.py`：administrator 模板权限边界段同步「不要手动 reset spec 状态、框架自动触发重验证」声明
- [ ] 3.4 手动复位兼容回归：Dashboard unfreeze / 手动 update_spec 复位 ready 的路径行为不变（不清 rounds、不拦截）

## 4. 测试与回归

- [ ] 4.1 `tests/test_blocked_reverify_gate.py`：GATE_TRANSITIONS 白名单断言——`transition_gate(blocked→testing)` 放行、人工 `transition(blocked→testing)` 拒绝返回 False、幂等自迁移短路
- [ ] 4.2 复位判定守卫链单测——branch 已合并→testing / 无 branch→ready / branch 未合并→ready / 人工冻结→不走直通道（沿用夹具替身模式，禁触用户级配置）
- [ ] 4.3 `_env_block_rounds` 生命周期语义单测——处置复位不清零、verified 落定清零、unfreeze_spec 清零、第 2 轮阻塞触发 frozen 冻结与人工告警
- [ ] 4.4 处置收尾集成测——disposition result=resolved 消费后自动 transition_gate(testing) 且 verifier 入队、`_impl_run_budget_used` 不变；result=escalated 不触发复位
- [ ] 4.5 全量回归 `python3 -m pytest tests/ -x -q`：既有状态机/升级/admin 测试零破坏；修复发现的问题直至全绿
