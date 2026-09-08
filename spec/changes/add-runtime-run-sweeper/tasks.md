## Deliverables

```yaml
- path: core/agent_runner/liveness.py
  kind: modify
- path: core/agent_runner/runner.py
  kind: modify
- path: core/event_bus.py
  kind: modify
- path: tests/test_daemon_lifecycle_races.py
  kind: modify
```

## 1. liveness.py 运行期清扫器

- [x] 1.1 从 `sweep_runs_without_terminal_state` 抽取 `_file_has_terminal_event(run_file) -> bool` helper（读文件逐行判 `RUN_TERMINAL_EVENT_TYPES`），启动清扫改为调用该 helper，行为不变
- [x] 1.2 liveness.py 常量区新增 `RUNTIME_SWEEP_IDLE_SECONDS = 1800`（含注释：三重判据之流停阈值、与 judge_window 的倍数关系、最坏检测延迟口径）
- [x] 1.3 `LivenessSupervisor` 新增 `sweep_dangling_runs() -> list`：遍历 runs_dir 顶层 `*.jsonl`，按三重判据（① `run_id not in self._pm._running_agents` ② mtime 停更 ≥ RUNTIME_SWEEP_IDLE_SECONDS 先行短路免读 ③ `_file_has_terminal_event` 为 False）补写 `{"type": "interrupted", "reason": "runtime terminal-state sweep", "idle_seconds": <int>, "timestamp": <UTC ISO8601>}`（经 `append_run_line`）
- [x] 1.4 实现进程内缓存 `self._terminal_verified: set[str]`（__init__ 初始化）：确认终态或已补写的 stem 入缓存，命中即跳过；注册表命中的在飞文件不入缓存
- [x] 1.5 补写动作输出 WARNING 日志（component=agent_runner，消息含全部被补写 run_id，格式对齐启动清扫告警）
- [x] 1.6 AgentRunner 门面补委托方法 `sweep_dangling_runs`（一行委托到 LivenessSupervisor，防组件/门面漏改）

## 2. runner.py 源头修复

- [x] 2.1 `_run_claude` 轮询环 try 块加 `except Exception as e:`：先 `append_run_error(run_file, f"run thread crashed: {e!r}", returncode)` 再原样 `raise`；确认 except 先于 finally 执行、error 行为崩溃场景文件末行
- [x] 2.2 确认 re-raise 后 attempt 循环既有失败处理（预算计数/STATE 转换/异常通道）语义不变

## 3. event_bus 挂载

- [x] 3.1 `_periodic_scan_loop` 每轮 `full_scan()` 前调用 `self.pm_engine.agent_runner.sweep_dangling_runs()`，try/except 包裹：异常降级 WARNING（component=event_bus）不阻断当轮扫描
- [x] 3.2 确认调用顺序为先扫后 scan（当轮 full_scan 消费最新终态事实）

## 4. 测试与回归

- [x] 4.1 tests/test_daemon_lifecycle_races.py 扩展：悬空 run（无终态+冷 mtime+不在注册表）→ 补写 interrupted 且行为文件末行、JSONL 合法、reason/idle_seconds/timestamp 字段正确
- [x] 4.2 在飞保护：注册表命中的 run 不被补写且不被打开读取
- [x] 4.3 流停保护：mtime 停更 < 1800s 的无终态 run 不被补写不被读取；mtime 停更 ≥ 阈值才进入判定
- [x] 4.4 缓存语义：已终态文件第二轮不重复打开；已补写文件不重复追加（幂等）；在飞文件不入缓存
- [x] 4.5 源头修复：轮询环抛非预期异常 → jsonl 即刻出现含 repr 归因的 error 终态行、异常继续上抛、调用方失败处理不受影响；含 error 终态的文件不被清扫器补写
- [x] 4.6 挂载点：sweep_dangling_runs 抛异常 → 当轮 full_scan 仍执行、WARNING 留痕；启动清扫在 helper 重构后行为回归（既有启动清扫测试全绿）
- [x] 4.7 全量 pytest 回归通过（基线外零新增失败）
