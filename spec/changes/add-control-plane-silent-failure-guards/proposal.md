# control-plane-silent-failure-guards — 控制平面静默失效防线

## Why

2026-09-14 `evo-item-retention-doc-tracking` 事故暴露一条**贯穿三层、每层单独都不致命、合起来静默失效 11 天**的缺陷链：

1. **生产调用点实参数量不符**：`core/admin_monitor.py:_reset_env_blocked_after_disposition` 调用 `pm_engine.handle_event("spec_implemented", spec)`，而生产签名是 `handle_event(event_kind, spec_name, spec_entry)`（3 必需位参）——必然 `TypeError`。该调用自 2026-09-11 `add-blocked-reverify-lane`（7f8458af）引入起**从未成功执行过**：`transition_gate(testing)` 与清 error 都成了，唯独 verifier 入队那步静默丢失。
2. **测试替身静默吸收**：`tests/test_blocked_reverify_gate.py` 的替身写作 `def handle_event(self, event_kind, spec_name, **kwargs)`，`**kwargs` 把实参数量不符吸收掉，断言 `handle_event_calls == [("spec_implemented", "demo")]` 对 2 参/3 参都成立，CI 全绿。
3. **宽 except 降级编程错误**：`except Exception` 把 `TypeError`（代码缺陷）与 `OSError`（运维失败）一视同仁，降为一行 WARNING，不重抛、不升级告警。

结果：spec 卡在 `testing` **1 小时 12 分钟**，无 verifier 运行，日志里 `直通道成功` 0 次、`复位失败` 1 次。**为什么会悬置这么久**是第二层问题的答案——`testing` 态在 `event_bus._recover_one` 的 recovery 分支中**没有任何出口**（只覆盖 `drafted/reviewing/implemented/ready/bug-found/verified`），`_status_to_event("testing")` 也返回空；运行期落入 `testing` 却无人驱动的 spec，**唯一恢复通道是 daemon 重启**。而 `stuck` 信号阈值 = `run_timeout_seconds(9000s) + 600s` = 160 分钟，远水解不了近渴。

两类缺陷同属一个母题：**控制平面的失效是静默的**——代码坏了 CI 不知道（替身吸收 + 无 arity 守卫），坏了之后状态悬置也没有信号（无"状态无驱动"探测）。本 SPEC 各补一道机械防线。

## What Changes

### 防线一：生产调用点 arity 静态守卫（防线 3）

- 新增静态 AST 测试 `tests/test_callsite_arity_guard.py`：扫描 `core/` + `fenixd.py` 的生产调用点，凡 `self.<method>(...)` 或跨对象 `<obj>.<method>(...)` 的**实参必填位不足**（调用位置参数个数 < 该 method 唯一签名的最小必填数，且非 `*args` 展开）即失败。方法名唯一 + 无 `*args`/`**kwargs` 时才判定（保守起步，避免同名误报）。
- 落地时该扫描已实测 `core/` 违规数 = 0（仅需白名单排除 `logger.warning(f-string)` 等同名误报），是**纯加地板**、不欠债。
- 与防线二同源思路：`tests/test_state_layout_contract.py` 的 AST 静态守卫先例。

### 防线二：测试替身保真守卫（防线 1，已原地落地，纳入版本化）

- 新增 `tests/test_fake_double_fidelity.py`：`tests/` 下任一类的 seam 方法替身，若比生产方法**更宽容**（含 `*args`/`**kwargs`）或**必填参数更少**即失败。
- 同步收紧既有偏离替身：`tests/test_run_budget_continuity.py`、`tests/test_liveness_hang_discrimination.py`（`_send_human_escalation_alert`）、`tests/test_spec_review_agent.py`（`_check_agent_result_artifact`，2 处）、`tests/test_self_evolution.py`（`_run_claude`）——全部改为与生产签名一致的显式签名。

### 防线三：复位路径编程错误必须升级（防线 2）

- `core/admin_monitor.py:_reset_env_blocked_after_disposition` 的 `except Exception` 前置一层 `except (TypeError, AttributeError, NameError)`：编程错误 → 落 `admin_reset_programming_error` ESCALATION 告警（severity=critical，含异常类型与 `core/` 内最深调用点），**不再静默降级**；其他异常（运维失败）保持既有 WARNING 语义。
- 新增 `SIGNAL_SEVERITY` / `SIGNAL_RECOMMENDATION` 表项；同类未处理告警存在时去重（`unhandled_for`）防每轮巡检重复落盘。
- 修复事故根因调用点本身：`handle_event("spec_implemented", spec, spec_entry)`。

### 防线四：状态无驱动信号（防线 4）

- 新增 admin 信号 `orphaned_state`：`status ∈ {implementing, testing}` 且 **无活动 run 文件**（mtime 超宽限）且 **无存活 agent 子进程**且**无待派发**，持续超过短阈值（远短于 `stuck` 的 160 分钟，默认约 10–15 分钟）→ 判定"状态无驱动"，唤起 Administrator 并走复位直通道自动重派。
- 补齐 `testing` 态在运行期的恢复出口：`event_bus` recovery 对 `testing` 且无活动 run 的 spec 不静默留白。
- 把"整类：控制平面某条路径把 spec 留在 `implementing/testing` 却没人驱动"从结构上封死——本事故的悬置 1h12m 正是此类。

## Capabilities

### New Capabilities

- `callsite-arity-guard`：生产调用点实参数量静态守卫——AST 扫描 `core/` + `fenixd.py`，`self.<method>()` / 跨对象调用必填位不足即失败；方法名唯一 + 无变长参数才判定；含误报白名单与"守卫有牙"自检（候选集非空）。
- `test-double-fidelity`：测试替身保真守卫——`tests/` 下 seam 方法替身不得比生产方法更宽容（`*args`/`**kwargs`）或必填更少；含候选集构造规则（方法名唯一、非 dunder、非宽泛名黑名单）与"守卫有牙"自检。
- `admin-reset-error-escalation`：复位路径编程错误升级——编程错误（`TypeError`/`AttributeError`/`NameError`）落 `admin_reset_programming_error` critical ESCALATION（含调用点），其他异常保持 WARNING；同类去重；绝不重抛（处置记录先落盘）。
- `orphaned-state-signal`：状态无驱动探测与恢复——`implementing`/`testing` 无活动 run/进程/待派发超短阈值 → `orphaned_state` 信号 + 自动重派；补齐 `testing` 态运行期恢复出口。

### Modified Capabilities

（无——`spec/specs/` 活跃目录为空。本改动扩展的 `admin-health-monitor` 能力（`add-administrator-agent`）与 `lifecycle-hygiene` 能力（`run-lifecycle-hardening`）均已归档，其既有 Requirement 语义不被修改：`orphaned_state` 是新增检测项、`admin_reset_programming_error` 是新增信号类型，既有 `stuck`/`repeated_failures`/节流/复位语义保持不变。）

## Impact

**生产代码**：
- `core/admin_monitor.py`：`_reset_env_blocked_after_disposition` 异常分层 + 新增 `_escalate_reset_programming_error`；`SIGNAL_SEVERITY`/`SIGNAL_RECOMMENDATION` 增项；新增 `_detect_orphaned_state`（或等价）与 `orphaned_state` 常量。
- `core/event_bus.py`：`_recover_one` 补 `testing` 无驱动出口（或新增扫尾通道）。
- `fenixd.py`：若需新信号落盘/唤起接线（视既有 `_handle_signal` 通用路径是否已覆盖）。

**测试**：
- 新增 `tests/test_callsite_arity_guard.py`、`tests/test_fake_double_fidelity.py`（本 SPEC 已草拟，见 `design.md` 附录）。
- 新增 `tests/test_orphaned_state_signal.py`（或并入既有 `tests/test_admin.py` / `tests/test_blocked_reverify_gate.py`）。
- 收紧 5 处既有替身（见 What Changes 防线二）。

**风险与回退**：`orphaned_state` 阈值过短会误报正常的长 run（验证/实现 run 可达数十分钟）——须以"无活动 run 文件 + 无存活子进程"双条件兜底，而非仅看状态时间戳；守卫类改动零生产行为变更，纯新增测试。

**不涉及**：不改验证裁决稳定性、费控语义、`stuck` 既有阈值与节流、`blocked` 复位路径语义。
