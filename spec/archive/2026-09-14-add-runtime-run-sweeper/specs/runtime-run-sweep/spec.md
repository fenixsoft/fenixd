# runtime-run-sweep 能力规格

## ADDED Requirements

### Requirement: 运行期悬空 run 判定与补写

daemon 存活期间，系统 SHALL 周期性（每轮 periodic scan）扫描 runs 目录顶层 `*.jsonl`，对同时满足以下三重判据的 run 文件补写 `interrupted` 终态事件：
1. run_id 不在 AgentRunner `_running_agents` 注册表中（键 = 文件 stem，直接成员判定）；
2. 文件 mtime 距今 ≥ `RUNTIME_SWEEP_IDLE_SECONDS`（1800 秒，模块常量）；
3. 文件尾部扫描无任何终态事件（终态口径 = `RUN_TERMINAL_EVENT_TYPES`：result/interrupted/error/cancelled）。

三重判据为 AND 关系，任一不满足 SHALL 跳过该文件且不打开读取（判据 2 在判据 1 通过后先行短路）。

#### Scenario: 悬空 run 被补写
- **WHEN** 某 run jsonl 无终态事件、mtime 停更 4723 秒、run_id 不在 `_running_agents`
- **THEN** 该文件尾部被追加一行 interrupted 终态事件，JSONL 结构合法且该行为文件末行

#### Scenario: 在飞 run 受注册表保护
- **WHEN** 某 run jsonl 无终态事件但 run_id 在 `_running_agents` 注册表中（在飞）
- **THEN** 该文件不被补写、不被打开读取

#### Scenario: 流停更不足阈值不受清扫
- **WHEN** 某 run jsonl 无终态事件、不在注册表，但 mtime 距今 600 秒（< 1800 秒）
- **THEN** 该文件不被补写、不被打开读取（最坏检测延迟 = 阈值 + 扫描周期）

#### Scenario: 主线程崩溃但读线程仍在写的窗口不误扫
- **WHEN** `_run_claude` 主线程已异常退出（注册表已 pop）但读线程仍持续向 run jsonl 追加事件（mtime 持续刷新）
- **THEN** 清扫器因 mtime 判据不满足而跳过；待子进程退出、读线程 EOF、流停更超阈值后，下一轮补写 interrupted

### Requirement: 补写产物格式

清扫器补写的终态事件 SHALL 为单行 JSON，含字段：`type` = `"interrupted"`、`reason` = `"runtime terminal-state sweep"`、`idle_seconds`（整数，补写时刻距文件 mtime 的秒数）、`timestamp`（UTC ISO8601）。写入 SHALL 经 `append_run_line` 的 O_APPEND 单行原子追加。reason 后缀 `terminal-state sweep` SHALL 与启动清扫的 `"startup terminal-state sweep"` 构成同族可辨识命名。

#### Scenario: 产物字段完整可归因
- **WHEN** 清扫器对停更 4723 秒的悬空 run 补写
- **THEN** 追加行可解析为 JSON，`reason` 为 `"runtime terminal-state sweep"`，`idle_seconds` ≈ 4723（±扫描周期误差），`timestamp` 为 UTC

#### Scenario: 时间轴来源可辨识
- **WHEN** Dashboard 时间轴或日志检索读取该 run 的终态事件
- **THEN** 可通过 reason 区分该 interrupted 来自运行期清扫而非 daemon 关闭（`daemon shutdown`）或启动清扫（`startup terminal-state sweep`）

### Requirement: 终态缓存避免重复扫描

清扫器 SHALL 维护进程内已验证终态文件集合（`_terminal_verified`，键 = 文件 stem）：文件确认含终态事件或已被本清扫器补写后加入集合；后续轮次对集合内文件 SHALL 不再打开读取。在飞文件（注册表命中）SHALL NOT 加入缓存（其终态由运行线程写入，加入会跳过后续验证）。

#### Scenario: 已终态文件零重复读取
- **WHEN** 某 run 的 jsonl 已含 result 终态且已进缓存
- **THEN** 下一轮清扫不打开该文件（缓存命中短路）

#### Scenario: 补写后不再重触
- **WHEN** 清扫器已对某悬空 run 补写 interrupted 并加入缓存
- **THEN** 后续轮次不再向该文件追加任何事件（单次补写幂等）

### Requirement: event_bus 挂载与异常降级

`event_bus._periodic_scan_loop` SHALL 在每轮 `full_scan()` 之前调用 `self.pm_engine.agent_runner.sweep_dangling_runs()`（经既有 pm_engine → agent_runner 引用，不新增构造参数）。清扫器抛出的任何异常 SHALL 被捕获并降级为 WARNING 日志（component=event_bus），SHALL NOT 阻断当轮 full_scan。清扫器实际补写时 SHALL 输出 WARNING 日志（component=agent_runner，含被补写 run_id 列表）。

#### Scenario: 清扫异常不阻断扫描
- **WHEN** 清扫器在扫描中抛出异常（如 runs 目录 IO 错误）
- **THEN** 当轮 full_scan 仍正常执行，日志含 WARNING 级清扫失败记录

#### Scenario: 补写动作留痕
- **WHEN** 清扫器补写了 1 个或多个悬空 run
- **THEN** daemon 日志出现 WARNING（component=agent_runner），消息含全部被补写的 run_id

### Requirement: run 线程崩溃显式终态（源头修复）

`_run_claude` 轮询环 SHALL 捕获 `Exception`：先经 `append_run_error` 向 run jsonl 追加含异常归因（`repr` 形式）的 error 终态行，再原样 re-raise 给调用方（attempt 循环的预算计数与 STATE 处理语义不变）。error 行 SHALL 为文件末行（finally 中 result/cancelled 写入在 except 之后，崩溃场景无 result/cancelled 可写）。

#### Scenario: 线程级异常即刻终态
- **WHEN** 轮询环内抛出非预期异常（如 `TypeError`）
- **THEN** run jsonl 立即获得含 `repr` 归因的 error 终态行，异常继续向上传播，调用方既有失败处理不变

#### Scenario: 崩溃 run 不被清扫器重复补写
- **WHEN** 线程崩溃 run 的 jsonl 已含 error 终态行
- **THEN** 清扫器判据 3（无终态事件）不满足，该文件不被补写 interrupted

### Requirement: 与启动清扫口径一致

运行期清扫与启动清扫 SHALL 共享同一终态判定 helper（`_file_has_terminal_event`）与同一终态类型常量（`RUN_TERMINAL_EVENT_TYPES`），SHALL NOT 各自实现解析逻辑。启动清扫的既有行为（daemon 启动期一次性、对孤儿进程存活不阻塞补写）SHALL 保持不变。

#### Scenario: 终态口径单源
- **WHEN** `RUN_TERMINAL_EVENT_TYPES` 增删终态类型（如新增终态枚举）
- **THEN** 运行期清扫与启动清扫同步生效，无需各自修改

#### Scenario: 启动清扫行为不回归
- **WHEN** daemon 启动且 runs 目录存在无终态遗留文件
- **THEN** 启动清扫仍按原时机（AgentRunner 初始化后、任何派发前）一次性补写，行为与本变更前一致
