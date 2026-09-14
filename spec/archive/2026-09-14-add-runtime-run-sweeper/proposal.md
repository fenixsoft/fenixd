# add-runtime-run-sweeper

## Why

2026-09-06 三个 run（impl-add-verify-multi-kind-runner-1788647311-a1、admin-…-1788647392/1788649824）无终态悬空 11.6–12.3 小时直至重启清扫：daemon 在重启排水期间被 supervisor SIGKILL，in-flight run 的监督线程随进程死亡，run jsonl 永久失去终态写入者。现有的收口机制——启动终态清扫（sweep_runs_without_terminal_state）——只在 daemon 启动期执行一次，悬空 run 在整个 daemon 存活期间无任何机制收口，期间 run 统计失真、孤儿 claude 持锁阻断重派、多烧一次实现预算。需要运行期清扫器补齐「daemon 存活期间悬空」这一缺口。

## What Changes

- `core/agent_runner/liveness.py` 新增 `LivenessSupervisor.sweep_dangling_runs()`：周期性扫描 runs 目录，对满足三重判据（不在 `_running_agents` 注册表 + mtime 停更 ≥ 阈值常量 + 尾部无终态事件）的 run 补写 `{"type": "interrupted", "reason": "runtime terminal-state sweep", "idle_seconds": …}` 终态；抽 `_file_has_terminal_event` helper 与启动清扫共享终态判定口径；新增模块常量 `RUNTIME_SWEEP_IDLE_SECONDS = 1800`
- `core/agent_runner/runner.py` 源头修复：`_run_claude` 轮询环加 `except Exception` → `append_run_error` → 原样 re-raise，run 线程未预期异常即刻落显式 error 终态（含异常归因），不再依赖清扫器 30 分钟后兜底
- `core/event_bus.py` `_periodic_scan_loop` 每轮 `full_scan()` 前调用 `self.pm_engine.agent_runner.sweep_dangling_runs()`，异常降级 WARNING 不阻断扫描
- AgentRunner 门面为 LivenessSupervisor 新方法补委托行（防组件/门面漏改）

## Capabilities

### New Capabilities
- `runtime-run-sweep`: daemon 存活期间的 run 终态运行期清扫——判定判据、补写产物格式、与在飞保护/超时监督/启动清扫的职责边界、event_bus 挂载点的异常降级语义

### Modified Capabilities
<!-- 无：spec/specs/ 当前无活跃能力集，启动清扫属 fix-daemon-lifecycle-races 变更内实现细节，无独立 spec 需修改 -->

## Impact

- 代码：`core/agent_runner/liveness.py`、`core/agent_runner/runner.py`、`core/event_bus.py`（均为修改既有文件，无新文件、无前端、无配置项）
- 行为：run jsonl 可能新增 `runtime terminal-state sweep` 来源的 interrupted 终态行（时间轴可见）；run 线程崩溃时 jsonl 新增带异常归因的 error 终态行
- 已知交互：补写会刷新文件 mtime，短暂（≤120s）影响 `_stream_recent` 流新鲜度回退与既有「清扫抬僵尸 mtime」读侧残留（find_impl_run_file mtime 排序），不阻塞本变更、治本在读者侧修复方向
- 测试：`tests/test_daemon_lifecycle_races.py` 扩展约 9 条
