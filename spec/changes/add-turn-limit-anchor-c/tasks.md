# Tasks: add-turn-limit-anchor-c

## Deliverables

```yaml
- path: core/wip_checkpoint.py
  kind: modify
- path: core/agent_runner/runner.py
  kind: modify
- path: core/agent_runner/session.py
  kind: modify
- path: tests/test_impl_wip_checkpoint.py
  kind: modify
- path: tests/test_turn_limit_lifecycle.py
  kind: new
```

## 1. 锚点 C（turn-limit 收口 WIP 保全）

- [x] 1.1 `core/wip_checkpoint.py` 新增 `ANCHOR_TURN_LIMIT = "turn-limit"` 常量（模块 docstring 锚点清单补第三锚点条目）
- [x] 1.2 `core/agent_runner/runner.py` 新增 `_wip_checkpoint_on_forced_kill(spec_name, wt_path)` 私有方法：载体有效性检查（复用 `_worktree_path_valid`）后调 `commit_wip_checkpoint(wt_path, spec_name, ANCHOR_TURN_LIMIT, logger)`，失败降级不阻断（helper 内建语义，不额外 try/except 包裹收口路径）
- [x] 1.3 turn-limit 收口分支（`turn_limit_error is not None` 处，`append_run_error` 之前）调用 1.2 方法；timeout 收口分支（`timeout_error is not None` 处）同样接入（design D1：两强杀路径共用）
- [x] 1.4 `tests/test_impl_wip_checkpoint.py` 补锚点 C 单测：dirty worktree 强杀收口产生 `fenix(wip): checkpoint turn-limit <spec>` 提交；干净 worktree 零动作幂等；helper 失败（git 超时桩）收口流程照常走完 error 终态

## 2. 活性感知续期（封闭矩阵）

- [x] 2.1 `core/agent_runner/runner.py` 模块级新增续期常量 `TURN_EXTENSION_STEP_FRACTION = 0.25`、`TURN_EXTENSION_MAX = 2`（含 design D2 参数依据注释）
- [x] 2.2 新增 `_turn_limit_action(run_file, spec_name, run_id, turn_extensions_used, wt_path, agent_type)` 判定方法：双活性证据（分支 rev-list 增量 + 尾部窗口 tool_result 流量，design D2 a/b），返回 `{"action": "extend"/"kill", "extension_index", "turn_step", "evidence", "new_turn_cap"}`，结构对齐 `_supervision_deadline_action`
- [x] 2.3 轮询环改造：`extensions_used` 旁新增 `turn_extensions_used` 局部变量与 `current_turn_cap`（初始 max_turns）；turn-limit 判定改调 2.2 方法——extend 分支追加 `turn_extension` 事件落 run 文件（含 extension/turn_step/evidence ≤400 字符/new_turn_cap）、累加 cap、INFO 日志；kill 分支保持既有 `proc.kill()` + `turn_limit_error` 流程（design D2/D3）
- [x] 2.4 验证续期与超时矩阵互不干扰：两计数独立、判定顺序（取消→超时→轮次→poll）不变、`note_run_extension`（超时语义）不被 turn 续期复用（design D3）；既有超时 extend 单测回归通过
- [x] 2.5 `tests/test_turn_limit_lifecycle.py`（新建）：有新提交活性 → extend + `turn_extension` 事件断言；仅 tool_result 流量活性 → extend；双无活性 → kill 且行为与现行一致（error 终态为文件最后一行）；封顶耗尽 → 直接 kill；rev-list 失败 fail-open 不误杀

## 3. 消耗观测口径修正

- [x] 3.1 `core/agent_runner/session.py` `_extract_usage_info`：result 为 None（或非 dict）时返回 dict 增加 `"unobserved": True` 键（正常路径不置位），docstring 补 unobserved 语义说明
- [x] 3.2 `core/agent_runner/runner.py` attempt 循环 catch 分支 DEBUG 文案改写：「tokens counted as 0」→「usage unobserved (no result terminal event; real consumption likely non-zero)」；`_accumulate_token_usage` 对 unobserved dict 跳过累计并 DEBUG 留痕计数（design D4：不新增 STATE 字段、不伪造金额）
- [x] 3.3 `tests/test_turn_limit_lifecycle.py` 补口径测试：`_extract_usage_info(None)` 带 unobserved 标识且四数值键全零；正常 result 路径无 unobserved 键；`_accumulate_token_usage` 对 unobserved 输入零增量

## 4. 回归与收尾

- [x] 4.1 全量回归：`pytest tests/test_impl_wip_checkpoint.py tests/test_turn_limit_lifecycle.py tests/test_agent_runner_gate.py`（含既有终态次序钉点：error 行是文件最后一行）通过
- [ ] 4.2 tasks.md 全部勾选 + 声明交付物对账（5 个声明路径全部有真实变更）+ `.fenix-run-result.json` 收尾
