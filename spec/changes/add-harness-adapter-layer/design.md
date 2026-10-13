## Context

母设计文档 `docs/superpowers/specs/2026-10-13-multi-harness-adapter-design.md` 已定稿四决策（全局切换 / 能力等价映射只做 dsh / dsh 目标为主 harness / 拆 4 SPEC 自举实施）与耦合地图 C1-C12。本 SPEC 承接其中「SPEC-1 harness 抽象层与 claude 平移」一节。

现状：`_run_claude`（core/agent_runner/runner.py:5607，命令构造 :5719-5746）是所有 spec 车道与维护车道的主通道，另有 7 个表亲 spawn 点各自复制 CLI 形态；stream-json 事件 schema 被 8+ 读侧模块消费；进程识别硬编码 `claude`（proc_utils.py:47 等 4 处）；ADR-055 承诺「一切 LLM 借道 claude CLI」。

关键约束：
- **行为零变化**：本 SPEC 完成后，所有车道在 claude 通道上的行为与现状逐字节一致（argv/env/stdin/事件流/终态判定）。
- daemon 自举：实现分支在 worktree 内开发、回归护航后 merge-back，框架日常模式。
- run jsonl 保持 claude stream-json 形状为唯一 canon（读侧零改动）。

## Goals / Non-Goals

**Goals**
- HarnessAdapter 协议接口冻结（SPEC-2 依赖其 `HarnessCapabilities`）。
- claude_adapter 承接 C1/C5/C8/C10 全部现状行为，快照测试护航。
- 5 个一次性 spawn 点收编 `run_one_shot`；告警叙事经 `set_channel` 走 adapter。
- `agent.harness` 配置落地（claude|dsh，缺省 claude；dsh 在本 SPEC 阶段 fail-fast）。
- 进程识别泛化到 `process_patterns()`。
- ADR-271 取代 ADR-055。

**Non-Goals**
- dsh_adapter 实现（SPEC-3）；fenix-dsh Bundle（SPEC-2）；验收切换（SPEC-4）。
- run jsonl schema 中性化（母设计 §1.2，留作可选还债 SPEC）。
- dashboard 自由会话与 `CLAUDE_PID` watchdog 的 harness 化（豁免，ADR-271 记录）。
- 车道级 harness 路由、跨 harness 回退（第二阶段候选）。

## Decisions

1. **协议边界放在进程边界（SpawnSpec 进、归一化事件出）**，而非放在 LLM 调用层。理由：fenixd 与 harness 的全部交互已经收敛在「spawn 子进程 + 读 stdout 事件流 + 读 stderr」；ADR-242/243 的 `set_channel` 与 ADR-221 回调注入是已验证的接缝先例。备选「在 provider/LLM 层抽象」被否：那会把 harness 的会话/工具/沙箱语义错误地压进 provider 模型（C3/C4 的语义耦合无法安放）。
2. **run jsonl 不改形状，normalize_event 以 claude stream-json 为目标形状**。理由：读侧 8+ 模块零改动是对「行为零变化」约束的最大保障；中性化是 dsh 验收后的可选还债项。备选「新中性 schema + 读侧迁移」被否：blast radius 与自举风险叠加，且不阻塞 dsh 接入。
3. **claude_adapter 是平移不是重写**：命令构造、`_build_isolated_settings`（runner.py:2000-2059）、`_ensure_agent_config_dir`（:2067-2143）、env 路由（:1454-1456/1667-1669/3318-3320、maintenance_runs.py:148-157）、banned env 清理（agent_env_keys.py）整体搬入；`_run_claude` 的「有意单体」注记（:5659-5664）解除并以快照测试替代其防回归职能。
4. **`agent.harness` 本期枚举 claude|dsh，dsh 值 fail-fast**：config 校验接受两个值（schema 前瞻，避免 SPEC-3 再改校验），但 `_resolve_adapter('dsh')` 在 SPEC-1 阶段抛出明确错误「dsh adapter 未部署（add-dsh-adapter-integration 交付）」，dispatch 前置健康检查拦截。理由：避免「接受但静默走 claude」的假配置。
5. **进程识别走 `adapter.process_patterns()`**：proc_utils.py:47 的 basename 集合、event_bus.py:810 / admin_monitor.py:868 / bin/fenix_dashboard.py:151-154 的 pgrep pattern 改为从当前 harness adapter 获取，claude 值与现状全等。
6. **一次性 spawn 收编为 `run_one_shot(adapter, prompt, *, model, timeout, …)`**：五处调用点的 argv 形态差异（argv 传 prompt vs stdin 传 prompt）由 adapter 内的 lane 语义保持，收编后以「同参数运行」测试钉住。备选「各处保留只改命令构造」被否：复制面不收敛，SPEC-3 要再改 5 处。
7. **ADR-271 决策集**：取代 ADR-055；豁免自由会话/CLAUDE_PID watchdog；冻结 run jsonl canon 与 worktree 目录约定（`worktrees/{impl,verify,repair,planner}-<spec>-` 字面量被 6+ 处在飞判定依赖，与 harness 无关，不动）。

## Risks / Trade-offs

- [平移引入行为漂移（参数顺序/env 残留/默认值差异）] → 快照测试逐字节对账平移前后 SpawnSpec；跑既有回归网（agent_runner 相关测试全量）+ junit 定向子集。
- [8438 行 runner.py 的抽取误伤共享状态] → claude_adapter 只移纯函数与配置构造，不移动可变运行态（attempt 环/监督环仍在 `_run_agent`）；每次抽取独立 commit 便于回溯。
- [配置热重载遇到 agent.harness 变更] → 热重载沿用 30s mtime 机制；harness 切换生效语义 = 下次 dispatch 起（在飞 run 不受影响），写入 settings_routes 响应与 SystemPanel 提示文案。
- [dsh 枚举值被提前配置导致车道假死] → fail-fast 明确报错而非静默回退；健康检查在 dispatch 与 Dashboard 设置保存两处都拦截。

## Migration Plan

实现分支在 worktree 内完成 → 回归绿 → merge-back。merge-back 后 daemon 继续以 claude 通道运行（缺省值），无运行时切换动作；旧代码路径随 `_run_claude` 改名一并消失，回滚 = revert merge commit。

## Open Questions

（无——开放项已归属：usage 形态与 subagent 机制探明归 SPEC-2/3 的真机探针任务。）
