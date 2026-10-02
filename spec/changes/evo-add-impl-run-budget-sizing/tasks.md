## Deliverables

```yaml
- path: core/fast_track_result.py
  kind: modify
- path: core/agent_runner/runner.py
  kind: modify
- path: tests/test_impl_run_budget_sizing.py
  kind: new
```

## 1. 规模化轮数预算

- [ ] 1.1 core/fast_track_result.py：新增 `get_turn_budget_sizing_config(config)`（归一化 `agents.turn_budget_sizing` 段：enabled 布尔、full_scale_threshold 正整数、suggested_turn_cap 正整数、bookkeeping_share_threshold 浮点 [0,1]、kill_early 嵌套段，非法值逐项回退缺省 enabled=True/45/800/0.5/kill_early.enabled=False/10/0.1，风格与既有 `get_scale_precheck_config` 同源）与 `suggested_turn_cap_for_scale(base_turn_cap, scale, cfg)`（enabled 且 scale > full_scale_threshold 时返回 max(base, suggested_turn_cap)，否则返回 base）。
- [ ] 1.2 core/agent_runner/runner.py：实现车道启动处（现 :2695 `max_turns=self._get_config("agents.max_turns", 300)` 的一次注入点）计算生效轮数上限——依次取 STATE 该 spec 的 `impl_turn_cap_override`（正整数优先）、`suggested_turn_cap_for_scale` 推算值（scale 用 `estimate_spec_scale(spec/changes/<spec>)`，解析异常 WARNING 回退 base 不阻断）、base；启动日志记录 base/override/effective 三元组；缺失 STATE 访问或字段非法时等价 override=None。

## 2. 扩容判定携带工作量维度

- [ ] 2.1 core/agent_runner/runner.py：`_turn_limit_action` 判定前用 `core.run_task_track.parse_tasks_md(project_root, spec_name)` 读剩余未勾选任务数（缺失/异常记 None 并在 evidence 注明 unavailable，不抛出），extend 与 kill 两个返回分支的 evidence 统一拼接 `remaining_tasks=<n|unavailable>`；调用点（:5284 附近）把该值随 `turn_extension` 事件新增 `remaining_tasks` 字段落盘，事件既有字段保持不变。
- [ ] 2.2 core/agent_runner/runner.py：从 `_run_claude` 已维护的 tool_metrics 直方图派生尾窗簿记占比（TaskCreate+TaskUpdate / tool_uses_total，总数为 0 时记 None）；占比 ≥ `get_turn_budget_sizing_config` 阈值时写 WARNING 并在 `_turn_limit_action` evidence 注记（不改 extend/kill 结论）；run_metrics 事件新增 `remaining_tasks` 字段（写侧 :5413-5436 处与 2.1 同口径）。

## 3. 末位扩容拆停守卫（缺省关闭）

- [ ] 3.1 core/agent_runner/runner.py：`_turn_limit_action` 增 kill_early 守卫——仅当 `get_turn_budget_sizing_config` 的 kill_early.enabled 为 true、且本次判定为最后一次可用扩容（extension_index+1 == TURN_EXTENSION_MAX）、且剩余未勾选任务数 ≥ remaining_tasks_threshold、且 run 期间任务勾选进度占比 ≤ progress_floor 时，返回 kill 并在 evidence 注明 early-split 与 remaining_tasks；收口完全复用既有 turn-limit kill 路径（含 WIP 保全锚点），不新增收口实现；enabled 为 false（含缺省）时函数对其余输入的 extend/kill 结论与引入前逐位一致。

## 4. 测试

- [ ] 4.1 tests/test_impl_run_budget_sizing.py：覆盖 `get_turn_budget_sizing_config` 归一化（非法类型/越界/倒挂逐项回退缺省）与 `suggested_turn_cap_for_scale` 边界（scale 等于阈值不抬、阈值+1 抬、suggested 小于 base 时取 base、override 优先序）。
- [ ] 4.2 tests/test_impl_run_budget_sizing.py：用 seed STATE + 进程内装配（仿 tests/test_turn_limit_lifecycle.py 既有装置）覆盖：大规模 spec 启动生效上限为 suggested_turn_cap、小规模等于 base、override 优先、tasks.md 解析失败回退 base 不阻断派发；`_turn_limit_action` 在 extend 与 kill 分支的 evidence 含 remaining_tasks、turn_extension 事件落盘含该字段、簿记占比超阈只注记不改判；kill_early 关闭时同输入同输出逐位一致、开启且三条件满足时提前 kill、进度健康时仍 extend。