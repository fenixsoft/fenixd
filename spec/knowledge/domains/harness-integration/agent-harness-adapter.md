# HarnessAdapter 进程边界协议与 claude 平移

<!-- knowledge: capability=agent-harness-adapter rev=1
     sources=spec/archive/2026-10-30-add-harness-adapter-layer -->

「换 harness 只换 adapter」的接缝契约：在 `core/agent_runner/harness/` 包内把「怎么起进程、怎么读事件、怎么认进程」收敛为单一协议，claude 现状整体平移其中且行为逐字节不变（ADR-271）。

## 规则

- **协议七成员**：`HarnessAdapter` 协议至少含 `name`、`build_spawn_spec(req) -> SpawnSpec`、`normalize_event(raw) -> list | None`、`classify_stderr(line)`、`extract_result(events)`、`process_patterns()`、`capabilities()`；`SpawnRequest`/`SpawnSpec`/`HarnessCapabilities` 为独立数据类，`HarnessCapabilities` 可被 `json.dumps` 序列化（供 Bundle 侧对账）。`SpawnRequest` 携带足以承载车道与一次性 spawn 形态差异的字段（prompt 传输形态 argv/stdin、output-format、model、cwd、timeout、resume 等），使各 spawn 点的 argv/stdin 差异成为 SpawnRequest 数据而非 adapter 分支代码。
- **claude 平移字节级等价**：claude adapter 承接全部现状行为——CLI 参数构造（`claude -p --output-format stream-json --verbose --add-dir … --permission-mode bypassPermissions [--settings][--model][--resume]`）、prompt 经 stdin 传入、隔离 settings 构造与落盘（hooks/skills/plugins symlink/enabledPlugins/子代理模型映射）、`CLAUDE_CONFIG_DIR` 隔离、env 路由与 banned env 清理。对同一 `SpawnRequest`，argv 序列、env 字典（含清除键）、stdin 载荷逐字节相等；等价性由入库金样本 fixture 快照测试对账（覆盖 spec 车道、维护车道、resume、provider 链各至少一例）。claude 的 `normalize_event` 为恒等映射，run jsonl 落盘内容与 claude stream-json 原生事件一致。
- **主通道两段化**：主通道 `_run_agent` 拆为「build_spawn_spec → 通用 Popen + 归一化事件写盘」两段；attempt 环、max_turns 守护、五路监督、终态收口逻辑保持既有语义——任一车道 run 结束时 run jsonl 末行终态事件类型与字段结构不变，`RUN_TERMINAL_EVENT_TYPES` 判定不变。adapter 只移纯函数与配置构造，可变运行态（attempt 环/监督环）留在主通道。
- **一次性 spawn 收编**：监督 judge（liveness）、知识蒸馏（knowledge）、知识回填（knowledge_backfill）、架构图 autodraft（architecture_routes）、项目简介（project_routes）五个一次性 spawn 点统一走 `run_one_shot(adapter, …)`；各调用点 CLI 参数形态（judge 走 `--output-format json` argv 传 prompt、蒸馏走 `--permission-mode bypassPermissions` stdin 传 prompt 等差异）经 claude adapter 保持。告警叙事通道 `adjudication_narrative.default_channel` 经既有 `set_channel` 接缝注入 adapter 化实现，模型显式传递不依赖 CLI 默认档；新增轻量 LLM 生成需求禁再复制 CLI 形态（ADR-055 纪律由 ADR-271 升级承接）。
- **进程识别泛化**：`proc_utils.py`、`event_bus.py`、`admin_monitor.py`、`bin/fenix_dashboard.py` 的 claude 进程名/pgrep pattern 由当前 harness adapter 的 `process_patterns()` 供给，claude 值与现状全等（命中/豁免行为不变，killpg 自保护守卫不受影响）。
- **豁免面**：dashboard 自由会话（session_manager）与 `CLAUDE_PID` watchdog 不经 adapter 化、保持 claude 专用——自由会话恒以 claude CLI 长驻流式形态启动（ADR-139），watchdog 是 claude 专属监视器、随旧 harness 一起退役（ADR-271）。全仓核查命令构造唯一入口时两者不计入。
- **import 单向**：harness 包（protocol/claude_adapter/one_shot/工厂 `_resolve_adapter`）只依赖 stdlib 与既有纯工具模块，禁 import runner/event_bus/admin_monitor；消费侧单向 import 工厂取 `process_patterns()`。

## 关键行为

数据流：车道或一次性调用点构造 `SpawnRequest` → adapter `build_spawn_spec` 产出 argv/env/stdin → 通用 Popen 执行 → 原生事件流经 `normalize_event` 归一写 run jsonl → 终态经 `extract_result` 收口。新 harness 接入面 = 实现 adapter 七成员 + 工厂注册 + 健康检查，不触读侧、不触进程识别消费点、不触 worktree 目录约定。

## 溯源

- 2026-10-30 add-harness-adapter-layer（spec/archive/2026-10-30-add-harness-adapter-layer） — 新增本能力：HarnessAdapter 协议七成员与三数据类冻结、claude 现状字节级平移（金样本快照对账）、主通道两段化、五处一次性 spawn 收编 run_one_shot、进程识别 process_patterns() 泛化、自由会话与 CLAUDE_PID watchdog 豁免、harness 包 import 单向
