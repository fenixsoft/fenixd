## ADDED Requirements

### Requirement: HarnessAdapter 协议

系统 MUST 在 `core/agent_runner/harness/` 包内定义 `HarnessAdapter` 协议，至少包含：`name`、`build_spawn_spec(req) -> SpawnSpec`、`normalize_event(raw) -> list | None`、`classify_stderr(line)`、`extract_result(events)`、`process_patterns() -> list[str]`、`capabilities() -> HarnessCapabilities`。`SpawnRequest`/`SpawnSpec`/`HarnessCapabilities` MUST 为独立数据类，`HarnessCapabilities` MUST 可序列化（供 SPEC-2 的 Bundle 侧对账）。

#### Scenario: 协议完整性

- **WHEN** 对 `claude_adapter` 实例检查协议成员
- **THEN** 上述七个成员全部存在且可调用，`HarnessCapabilities` 可被 `json.dumps` 序列化

### Requirement: claude 平移字节级等价

`claude_adapter.build_spawn_spec` MUST 复现 `_run_claude` 现状的全部行为：CLI 参数构造（`claude -p --output-format stream-json --verbose --add-dir … --permission-mode bypassPermissions [--settings][--model][--resume]`）、prompt 经 stdin 传入、隔离 settings 构造与落盘（hooks/skills/plugins symlink/enabledPlugins/子代理模型映射）、`CLAUDE_CONFIG_DIR` 隔离、env 路由与 banned env 清理。对同一 `SpawnRequest`，平移前后的 argv 序列、env 字典、stdin 载荷 MUST 逐字节相等。

#### Scenario: 快照测试逐字节对账

- **WHEN** 以同一组代表性 SpawnRequest（覆盖 spec 车道、维护车道、resume、provider 链各至少一例）分别驱动平移前命令构造函数与 `claude_adapter.build_spawn_spec`
- **THEN** 每例的 argv 列表、env 字典（含清除键）、stdin 载荷全部相等，快照测试通过

#### Scenario: 事件归一化为恒等映射

- **WHEN** claude_adapter.normalize_event 消费 claude stream-json 原生事件
- **THEN** 输出与输入等价（恒等），run jsonl 落盘内容与现状一致

### Requirement: 主通道两段化不改行为

`_run_claude` MUST 改名 `_run_agent` 并拆为「build_spawn_spec → 通用 Popen + 归一化事件写盘」两段；attempt 环、max_turns 守护、五路监督、终态收口逻辑 MUST 保持现状语义。

#### Scenario: 终态事件语义不变

- **WHEN** 任一车道 run 结束（result/error/interrupted/cancelled/frozen-terminated/gate-blocked 任一终态）
- **THEN** run jsonl 末行终态事件类型与字段结构与现状一致，`RUN_TERMINAL_EVENT_TYPES` 判定不变

### Requirement: 一次性 spawn 收编

监督 judge（liveness.py）、知识蒸馏（knowledge.py）、知识回填（knowledge_backfill.py）、架构图 autodraft（architecture_routes.py）、项目简介（project_routes.py）五个一次性 spawn 点 MUST 收编进 `run_one_shot(adapter, …)`，各自的 CLI 参数形态（含 argv/stdin 传 prompt 的差异）经 claude_adapter 保持不变。

#### Scenario: 收编后参数形态保持

- **WHEN** 分别触发监督 judge 与知识蒸馏各一次（测试替身 spawn）
- **THEN** 捕获的 argv 与收编前该调用点的形态一致（judge 走 `--output-format json` argv 传 prompt；蒸馏走 `--permission-mode bypassPermissions` stdin 传 prompt）

### Requirement: 告警叙事通道走 adapter

`adjudication_narrative.default_channel` MUST 改为经 `set_channel` 注入的 adapter 化实现（ADR-242/243 接缝），spawn 行为与现状一致。

#### Scenario: 叙事通道行为保持

- **WHEN** 触发一次告警叙事（测试替身 spawn）
- **THEN** CLI 参数、模型显式传递（不依赖 CLI 默认档）与现状一致

### Requirement: 进程识别泛化

`proc_utils.py`、`event_bus.py`、`admin_monitor.py`、`bin/fenix_dashboard.py` 中的 `claude` 进程名/pgrep pattern MUST 改由当前 harness adapter 的 `process_patterns()` 供给；claude 值与现状全等。

#### Scenario: 识别结果与现状一致

- **WHEN** 以 claude adapter 的 process_patterns 驱动进程归属判定，并构造一个 `claude -p` 测试进程
- **THEN** 识别结果与硬编码现状一致（命中/豁免行为不变，killpg 自保护守卫不受影响）

### Requirement: dashboard 自由会话豁免

dashboard 自由会话（session_manager）与 `CLAUDE_PID` watchdog MUST 保持 claude 专用，不经 adapter 化；ADR-271 MUST 记录该豁免。

#### Scenario: 自由会话不受 agent.harness 影响

- **WHEN** `agent.harness` 为任意合法值
- **THEN** 自由会话仍以 claude CLI 长驻流式形态启动（ADR-139）
