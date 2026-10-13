# ADR-271：可插拔 agent harness 抽象层，命令构造收口 adapter，豁免面与既有约定冻结

date: 2026-10-13
status: accepted

取代：ADR-055（LLM 能力借道 claude CLI，框架不实现独立 LLM 客户端）。

## Context

全部 spec 车道与维护车道的主通道 `_run_claude` 命令构造内联在 runner（约百行参数拼装），另有 5 个一次性 spawn 点（监督 judge、知识蒸馏、知识回填、架构图 autodraft、项目简介）与叙事通道各自复制 CLI 形态；stream-json 事件 schema 被 8+ 读侧模块消费；进程识别（`claude` argv 形态、worktree pgrep patterns）硬编码在 4 处消费点。引入第二种 harness（dsh）需要把这些散落的「怎么起进程、怎么读事件、怎么认进程」收敛成单一进程边界契约；但框架里还有两处 claude 直连不在车道语义内（dashboard 自由会话、CLAUDE_PID watchdog），ADR-055 的「一切 LLM 借道 claude CLI」承诺在 adapter 化后如何延续、run jsonl 事件形状与 worktree 目录约定是否随抽象层松动，需要裁定。

## Decision

- **进程边界协议化**：`core/agent_runner/harness/` 定义 HarnessAdapter 协议（name/build_spawn_spec/normalize_event/classify_stderr/extract_result/process_patterns/capabilities），协议边界在进程边界——SpawnSpec（argv/env/stdin）进、归一化事件出。车道与一次性 spawn 的命令构造唯一入口收口 `harness/claude_adapter.py`；claude adapter 对现状做字节级平移（快照金样本护航），行为零变化。依赖单向（harness 只依赖 stdlib 与纯工具模块），消费侧延迟解析 import 避开重链。
- **run jsonl 事件 canon 冻结**：run jsonl 保持 claude stream-json 形状为唯一 canon（claude normalize_event 为恒等映射），读侧零改动；后续任何 harness 的 normalize_event 必须归一到同一 canon，禁为第二 harness 扩事件 schema。
- **豁免面冻结**：dashboard 自由会话（session_manager）与 CLAUDE_PID watchdog 不纳入 harness 抽象、继续直连 claude——前者是用户交互面（非框架派发车道），后者是「盯 claude 进程存活」的 claude 专属监视器（harness 换代时随旧 harness 一起退役，抽象它没有第二实现）。全仓 grep 核查命令构造唯一入口时两者不计入。
- **worktree 目录约定冻结**：`worktrees/{impl,verify,repair,planner}-<spec>-` 字面量被 6+ 处在飞判定依赖，与 harness 无关，不随 adapter 层泛化；worktree pgrep patterns 经 adapter 提供（`{impl,verify,repair}-<re.escape(spec)>-`），但目录命名约定本身保持字面冻结。
- **配置与 fail-fast**：`agent.harness`（claude|dsh，缺省 claude，非法值回退+告警）为 harness 选型唯一开关，每次 dispatch 前置健康检查现读现配（热更新对下次 dispatch 生效、在飞 run 不受影响）；dsh 在 adapter 部署前 fail-fast（「dsh adapter 未部署」），MUST NOT 静默回退 claude 代跑。
- **取代 ADR-055 的部分**：「不实现独立 LLM 客户端」的纪律保留，但「统一 headless `claude -p`」的措辞升级为「统一经 harness adapter spawn」——一次性 spawn 收编 `run_one_shot(adapter, …)`，新增轻量 LLM 生成需求禁再复制 CLI 形态，走同一收编入口。

## Consequences

- 新 harness 接入面收窄为「实现 adapter + 部署注册」，不触读侧、不触进程识别消费点、不触 worktree 约定；但 adapter 协议七成员成为冻结契约，成员语义漂移即破坏全部消费侧。
- canon 冻结使读侧零改动成立，代价是事件 schema 演进被锁死在 claude stream-json 形态；需要新事件类型时必须先扩 canon 并同步全部读侧，禁 harness 私自加行。
- 豁免面是显式债务：自由会话与 watchdog 保持 claude 直连，harness 切换后它们仍是 claude 形态；watchdog 随旧 harness 自然退役，自由会话若未来要跨 harness 需另立 ADR。
- 非法值回退+告警让配置面容错，但 dsh fail-fast 与之分层：配置读侧容错、工厂与 dispatch 拒绝静默代跑——错误配置在派发边界显性爆炸而非悄悄走错 harness。
