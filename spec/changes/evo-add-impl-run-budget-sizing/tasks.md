## Deliverables

```yaml
- path: core/fast_track_result.py
  kind: modify
- path: core/agent_runner/runner.py
  kind: modify
- path: tests/test_impl_run_budget_sizing.py
  kind: new
- path: spec/knowledge/adr/ADR-103-turn-limit-liveness-renewal-forced-kill-wip-salvage.md
  kind: modify
```

## 1. 规模化轮数预算

- [x] 1.1 core/fast_track_result.py：新增 `get_turn_budget_sizing_config(config)`（归一化 `agents.turn_budget_sizing` 段：enabled 布尔、full_scale_threshold 正整数、suggested_turn_cap 正整数、bookkeeping_share_threshold 浮点 [0,1]、kill_early 嵌套段，非法值逐项回退缺省 enabled=True/45/800/0.5/kill_early.enabled=False/10/0.1，风格与既有 `get_scale_precheck_config` 同源）与 `suggested_turn_cap_for_scale(base_turn_cap, scale, cfg)`（enabled 且 scale > full_scale_threshold 时返回 max(base, suggested_turn_cap)，否则返回 base）。
- [x] 1.2 core/agent_runner/runner.py：实现车道启动处（现 :2695 `max_turns=self._get_config("agents.max_turns", 300)` 的一次注入点）计算生效轮数上限——依次取 STATE 该 spec 的 `impl_turn_cap_override`（正整数优先）、`suggested_turn_cap_for_scale` 推算值（scale 用 `estimate_spec_scale(spec/changes/<spec>)`，传入 runner Logger 实例（core/logger.py 项目归属约定），解析异常 WARNING 回退 base 不阻断）、base；启动日志记录 base/override/effective 三元组；缺失 STATE 访问或字段非法时等价 override=None。

## 2. 扩容判定携带工作量维度

- [ ] 2.1 core/agent_runner/runner.py：`_turn_limit_action` 判定前用 `core.run_task_track.parse_tasks_md(project_root, spec_name)` 读剩余未勾选任务数（缺失/异常记 None 并在 evidence 注明 unavailable，不抛出），extend 与 kill 两个返回分支的 evidence 统一拼接 `remaining_tasks=<n|unavailable>`；调用点（:5284 附近）把该值随 `turn_extension` 事件新增 `remaining_tasks` 字段落盘，事件既有字段保持不变。
- [ ] 2.2 core/agent_runner/runner.py：从 `_run_claude` 已维护的 tool_metrics 直方图派生整 run 累计簿记占比（TaskCreate+TaskUpdate / tool_uses_total，总数为 0 时记 None；直方图为整 run 累计、无尾窗粒度，统一用整 run 口径与 proposal 实证一致），由调用点派生后以参数传入 `_turn_limit_action`（方法内不重扫转录）；占比 ≥ `get_turn_budget_sizing_config` 阈值时在轮次上限判定点写 WARNING（同点评估一次，不在常规轮询路径周期性发出）并在 `_turn_limit_action` evidence 注记（不改 extend/kill 结论）；run_metrics 事件新增 `remaining_tasks` 字段（写侧 :5413-5436 处，run 收尾时点快照，解析失败记 None）。

## 3. 末位扩容拆停守卫（缺省关闭）

- [ ] 3.1 core/agent_runner/runner.py：`_turn_limit_action` 增 kill_early 守卫——仅当 `get_turn_budget_sizing_config` 的 kill_early.enabled 为 true、且本次判定为最后一次可用扩容（extension_index+1 == TURN_EXTENSION_MAX）、且剩余未勾选任务数 ≥ remaining_tasks_threshold、且 run 期间任务勾选进度占比 ≤ progress_floor（基线：run 启动点在 1.2 同一读点顺带快照已勾选/未勾选任务数，进度 = 快照后新勾选 ÷ 启动时未勾选，分母 0 时视为健康不判；守卫仅对实现车道生效——`agent_type` 为 implementer/fast-track 系，dispute-judge/spec-review 等车道勾选进度恒零、不限车道则开启项目内必被误杀）时，返回 kill 并在 evidence 注明 early-split 与 remaining_tasks；收口完全复用既有 turn-limit kill 路径（含 WIP 保全锚点），不新增收口实现；enabled 为 false（含缺省）时函数对其余输入的 extend/kill 结论与引入前逐位一致。

## 4. 测试

- [ ] 4.1 tests/test_impl_run_budget_sizing.py：覆盖 `get_turn_budget_sizing_config` 归一化（非法类型/越界/倒挂逐项回退缺省）与 `suggested_turn_cap_for_scale` 边界（scale 等于阈值不抬、阈值+1 抬、suggested 小于 base 时取 base、override 优先序）。
- [ ] 4.2 tests/test_impl_run_budget_sizing.py：用 seed STATE + 进程内装配（仿 tests/test_turn_limit_lifecycle.py 既有装置）覆盖：大规模 spec 启动生效上限为 suggested_turn_cap、小规模等于 base、override 优先、tasks.md 解析失败回退 base 不阻断派发；`_turn_limit_action` 在 extend 与 kill 分支的 evidence 含 remaining_tasks、turn_extension 事件落盘含该字段、簿记占比超阈只注记不改判；kill_early 关闭时同输入同输出逐位一致、开启且三条件满足时提前 kill、进度健康时仍 extend、评审/裁决车道 agent_type 不触发守卫。

## 5. knowledge 注记

- [ ] 5.1 spec/knowledge/adr/ADR-103-turn-limit-liveness-renewal-forced-kill-wip-salvage.md：补一条注记，说明 turn_extension 事件 / run_metrics 新增的 `remaining_tasks` 与簿记占比观测字段、STATE 覆写键 `impl_turn_cap_override`、以及 kill_early 守卫（缺省关闭、仅实现车道）与 ADR-103 续期矩阵的关系——本 SPEC 是对该 ADR 的补充而非修订（proposal Impact 声明的义务，tasks.md 原漏列）。