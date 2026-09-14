# 任务清单 — add-control-plane-silent-failure-guards

## Deliverables

```yaml
- path: core/admin_monitor.py
  kind: modify
- path: core/config.py
  kind: modify
- path: core/event_bus.py
  kind: modify
- path: tests/test_callsite_arity_guard.py
  kind: new
- path: tests/test_fake_double_fidelity.py
  kind: new
- path: tests/test_orphaned_state_signal.py
  kind: new
- path: tests/test_blocked_reverify_gate.py
  kind: modify
- path: tests/test_run_budget_continuity.py
  kind: modify
- path: tests/test_liveness_hang_discrimination.py
  kind: modify
- path: tests/test_spec_review_agent.py
  kind: modify
- path: tests/test_self_evolution.py
  kind: modify
```

## 1. 防线一：生产调用点 arity 静态守卫

- [x] 1.1 新建 `tests/test_callsite_arity_guard.py`：AST 扫描 `core/**/*.py` 与 `fenixd.py`，构建「方法名唯一签名」候选集（唯一、无 `*args`/`**kwargs`），对 `<obj>.<method>(...)` 与 `self.<method>(...)` 判定必填位参不足（排除 `ast.Starred` 与 `**kwargs` 展开），违规即 `self.fail`。
- [x] 1.2 处理误报白名单：以 `(相对路径, 行号, 方法名)` 最小粒度豁免 `logger.*(f"...")` 等同名误报；落地实测白名单外违规数为 0。
- [x] 1.3 加「守卫有牙」自检：断言候选方法集规模高于下限。
- [x] 1.4 单测：注入 arity 违规样例 → 违规被报出；合规样例（关键字补足 / `*args` 展开 / 同名多签名）→ 不报。

## 2. 防线二：测试替身保真守卫

- [x] 2.1 新建 `tests/test_fake_double_fidelity.py`：扫描 `tests/**/*.py` 所有类方法，与 `core/` 候选 seam（方法名唯一签名、非 dunder、非宽泛名黑名单）比对 `(必填位参数, vararg, kwarg)`；替身更宽容或必填更少即 `self.fail`。
- [x] 2.2 收紧既有偏离替身（消灭守卫既有红灯）：`tests/test_run_budget_continuity.py` 与 `tests/test_liveness_hang_discrimination.py` 的 `_send_human_escalation_alert`、`tests/test_spec_review_agent.py` 两处 `_check_agent_result_artifact`、`tests/test_self_evolution.py` 的 `_run_claude` 全部改为与生产一致的显式签名。
- [x] 2.3 加「守卫有牙」自检 + 白名单（最小粒度 `(文件, 类名, 方法名)`，当前为空）。
- [x] 2.4 拔牙验证：临时把某替身改回 `**kwargs` → 守卫失败；恢复 → 通过（以测试固化，防止后续被改坏）。

## 3. 防线三：复位路径编程错误升级

- [x] 3.1 `core/admin_monitor.py:_reset_env_blocked_after_disposition` 前置 `except (TypeError, AttributeError, NameError)` → 调用新增 `_escalate_reset_programming_error`；其余异常保持既有 WARNING。
- [x] 3.2 新增 `_escalate_reset_programming_error`：落 `kind=escalation`、`signal_type=admin_reset_programming_error`、`severity=critical` 告警（经 `attach_trigger`），含 `reset_path`、异常类型/消息、`core/` 内最深栈帧调用点（`文件:行 (函数名)`）；同类未处理告警存在时 `unhandled_for` 去重；绝不重抛，自身失败只记日志。
- [x] 3.3 `SIGNAL_SEVERITY` 增 `admin_reset_programming_error: critical`；`SIGNAL_RECOMMENDATION` 增处置指引（代码缺陷、Administrator 无法修复、须工程侧定位、勿派子 fix 重跑）。
- [x] 3.4 修正事故根因调用点：`handle_event("spec_implemented", spec, spec_entry)`（实参数量与生产签名一致）。
- [x] 3.5 在 `tests/test_blocked_reverify_gate.py` 加 `TestResetProgrammingErrorEscalation`：`TypeError` 注入 → 恰好 1 条 critical 升级告警；`OSError` 注入 → 0 条升级告警；拔牙验证（移除分层 except → 失败）。

## 4. 防线四：状态无驱动探测与恢复

- [x] 4.1 `core/admin_monitor.py` 新增 `_detect_orphaned_state`（或等价）：`status ∈ {implementing, testing}` 且 无活动 run 文件 + 无存活 agent 子进程 + 无待派发（backoff 未到期 / `_cancelled_hold` / `start_after` 未到）三者同时成立且超短阈值 → `orphaned_state` 信号；接入 `_detect` 列表。
- [x] 4.2 `SIGNAL_SEVERITY` / `SIGNAL_RECOMMENDATION` 登记 `orphaned_state`；阈值独立配置键落点为 `core/config.py` admin 段（`get_admin_config` 新增 `admin.orphaned_state_threshold_minutes`，缺省 15 分钟，与 `admin.interval_minutes` 整数倍对齐），admin_monitor 从 `self.admin_cfg` 读取，与 `stuck` 阈值互不影响。
- [x] 4.3 `core/event_bus.py:_recover_one` 补 `testing` 态无驱动出口（发现则触发重派或联动 `orphaned_state`），不破坏 `implementing` 既有语义；若选择自动重派，MUST 复用 `implemented` 分支的 `tester_run` 与 `_inconclusive_attempts` 防重入守卫（event_bus.py:158-175），避免对已验证/暂停中的 spec 造成重验风暴；若选择联动 `orphaned_state`，须与 admin_monitor 检测复用同一"无驱动"判定口径，防止双路径重复触发。
- [x] 4.4 新建 `tests/test_orphaned_state_signal.py`：状态悬置 + 无 run + 无进程 → 产生信号；长 run 在跑 → 不产生；有意等待（`_cancelled_hold`/backoff/`start_after`）→ 不产生；`testing` 无驱动能被 recovery 发现；节流生效。
- [x] 4.5 回归：本事故场景（复位失败致 spec 悬置 `testing` 无 verifier）在新阈值内被 `orphaned_state` 捕获，早于 `stuck`。

## 5. 构建与验收

- [ ] 5.1 跑 `python3 bin/run_full_suite.py --timeout 3600` 全量回归，确认无引入失败（按 `--baseline` 区分存量）。
- [ ] 5.2 落地实证：对当前 `core/` 跑 arity 守卫违规 = 0；对 `tests/` 跑替身保真守卫违规 = 0。
- [ ] 5.3 逐条核对四个能力 spec 的 Scenario 均有对应测试覆盖。
