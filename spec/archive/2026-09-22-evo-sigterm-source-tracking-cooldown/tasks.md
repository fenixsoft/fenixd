## Deliverables

```yaml
- path: core/agent_runner/runner.py
  kind: modify
- path: core/agent_runner/provider_circuit.py
  kind: modify
- path: tests/test_sigterm_source_tracking.py
  kind: new
```

> 交付清单不含 core/agent_runner/result_gate.py：[task-gate] 前缀（result_gate.py:46）已存在且
> 只覆盖任务完成度类失败，本方案在该文件只做核对（只读），归类隔离全部在 runner.py 注入点实施。

## 1. 落地校验

- [x] 1.1 core/agent_runner/runner.py：子进程终结捕获处按**闭集**判定来源——先排除框架自身终止
      （cancel 旗标 / supervision 超时 / 轮次上限强杀：returncode=-9 且错误文本
      `Timeout after …` / `Max turns …`，runner.py:2833/2874/2942-2971，MUST NOT 打信号标签、
      MUST NOT 计信号计数），再判 daemon 关停（shutting_down / 产物 interrupted 标记 →
      既有 [shutdown-interrupted] 守卫），其余 143/负信号 → `[signal-kill: SIGTERM/143]` /
      `[signal-kill: SIGKILL/-9]` 标签注入错误文本，run 产物与告警 evidence 可追溯；
      无判别力时标 unknown 并如实带 returncode，MUST NOT 猜测声称 external-kill
- [x] 1.2 core/agent_runner/provider_circuit.py：新增信号死法（143/-9）计数通道，计数键 = spec 维度，
      阈值 3 + 冷却窗口（沿用既有量级常量/配置键命名），admin/impl/处置 run 路由覆盖，不再无限瞬态重试；
      MUST NOT 写 record_transient_error / _transient_break_until 全局瞬断熔断（不得冻结全项目派发）；
      MUST NOT 与既有 `_record_instant_fail` 秒挂冷却互相覆盖冷却截止（同事件取更晚者）
- [x] 1.3 core/agent_runner/runner.py：产物硬门失败停止全局瞬断**指纹**记账（对齐
      runner.py:2042-2051 `[terminal-no-commit]` carve-out 先例），错误文本补齐可识别归类标签；
      任务完成度类（[task-gate]）不注入 [provider-transient] 标签、走 gate 降级 + attempt 重试；
      结构类（文件缺失/为空/非法 JSON/顶层非对象/status 白名单外，无前缀）MUST 保留既有原地退避重试
      与 [provider-transient] 标签（tests/test_agent_runner_gate.py 契约），不得改为零重试

## 2. 测试

- [x] 2.1 tests/test_sigterm_source_tracking.py：外部信号致死（143/-9）→ 错误含信号来源标签、
      不归 [provider-transient]、不记全局瞬断指纹（2026-09-16 两个 admin run 形态回放夹具；
      信号发出者不可考 → 断言 unknown 形态亦合规）
- [x] 2.2 tests/test_sigterm_source_tracking.py：shutting_down/产物 interrupted → 维持
      [shutdown-interrupted]（不回归既有守卫）
- [x] 2.3 tests/test_sigterm_source_tracking.py：143/-9 连续达阈值 → 该 spec 冷却启动、冷却期不重试、
      到期自动恢复，且全局瞬断熔断未被触发（is_global_transient_break 为假）
- [x] 2.4 tests/test_sigterm_source_tracking.py：provider 网络抖动瞬态 → 既有退避不变
- [x] 2.5 tests/test_sigterm_source_tracking.py：产物硬门失败 → 不记全局瞬断指纹；结构类仍走原地
      退避重试（transient_retry 事件保留），任务完成度类不带 [provider-transient] 标签
- [x] 2.6 tests/test_sigterm_source_tracking.py：框架自身强杀（supervision 超时/轮次上限，returncode=-9
      且错误文本 Timeout/Max turns）→ 不打信号标签、不计信号冷却
- [x] 2.7 回归：tests/test_provider_circuit.py、test_agent_runner.py、test_agent_runner_gate.py、
      test_transient_backoff.py 通过
