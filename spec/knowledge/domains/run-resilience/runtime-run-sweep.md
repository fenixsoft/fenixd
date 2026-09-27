<!-- knowledge: capability=runtime-run-sweep rev=1 sources=spec/archive/2026-09-14-add-runtime-run-sweeper -->

# 运行期悬空 run 清扫

daemon 存活期间周期性为悬空 run 补写 interrupted 终态，并在源头保证 run 线程崩溃即刻留终态：runs 目录不再产生无终态尸体。

## 现行规则

- 悬空判定三重判据 AND，任一不满足即跳过且不打开读取：① run_id 不在 AgentRunner `_running_agents` 注册表（键 = 文件 stem，直接成员判定）；② 文件 mtime 距今 ≥ `RUNTIME_SWEEP_IDLE_SECONDS`（1800 秒，模块常量，判据 1 通过后先行短路）；③ 尾部扫描无任何终态事件（终态口径 = `RUN_TERMINAL_EVENT_TYPES`：result/interrupted/error/cancelled）。最坏检测延迟 = 阈值 + 扫描周期。
- 补写产物：单行 JSON——`type="interrupted"`、`reason="runtime terminal-state sweep"`、`idle_seconds`（补写时刻距文件 mtime 的秒数）、`timestamp`（UTC ISO8601）；经 `append_run_line` 的 O_APPEND 单行原子追加。reason 与启动清扫的 `"startup terminal-state sweep"` 构成同族可辨识命名，时间轴可区分运行期清扫、daemon 关闭与启动清扫三种来源。
- 终态缓存：进程内已验证终态文件集合 `_terminal_verified`（键 = 文件 stem）——文件确认含终态事件或已被本清扫器补写后加入，后续轮次不再打开读取（零重复读取、补写幂等单次）；在飞文件（注册表命中）不加入缓存。
- 挂载与异常降级：`event_bus._periodic_scan_loop` 每轮 `full_scan()` 之前调用 `sweep_dangling_runs()`（经既有 pm_engine → agent_runner 引用）；清扫器抛出的任何异常被捕获并降级 WARNING 日志（component=event_bus），不阻断当轮 full_scan；实际补写时输出 WARNING（component=agent_runner，含被补写 run_id 列表）。
- run 线程崩溃显式终态（源头修复）：`_run_claude` 轮询环捕获 `Exception` 时，先经 `append_run_error` 追加含异常归因（repr 形式）的 error 终态行、再原样 re-raise——attempt 循环的预算计数与 STATE 处理语义不变；崩溃 run 因已有终态行不被清扫器重复补写。
- 与启动清扫口径一致：共享同一终态判定 helper（`_file_has_terminal_event`）与终态类型常量，不各自实现解析逻辑；`RUN_TERMINAL_EVENT_TYPES` 增删终态类型时两侧同步生效。启动清扫既有行为（daemon 启动期一次性、孤儿进程存活不阻塞补写）保持不变。

## 溯源

- 2026-09-14 add-runtime-run-sweeper — 确立运行期三重判据清扫与补写产物格式、终态缓存、event_bus 挂载与异常降级、run 线程崩溃源头终态、与启动清扫共用终态口径
