## Context

SPEC-1 的 `_run_agent` 两段结构（build_spawn_spec → 通用 Popen + 归一化事件写盘）是本 SPEC 的接入点；SPEC-2 的 Bundle 与探针 fixtures/错误码表是本 SPEC 的对端与契约源。dsh headless 契约（母设计 §2.2）：stdin 喂任务、`--json` NDJSON 事件流（session 开头/final 结尾/error 无 final）、8KiB/32KiB 截断带 `truncated` 标、exit 0=完成 1=中止、`--session-id` 采纳语义 fail-loud。

## Goals / Non-Goals

**Goals**
- DshAdapter 全套协议实现，claude 通道行为零变化。
- 投影层以探针 fixtures 为契约测试源，读侧（run_task_track/liveness/result_gate）现有测试原样复用全绿。
- `agent.harness: dsh` 端到端可用（健康检查通过后 dispatch 全链走 dsh_adapter）。

**Non-Goals**
- Bundle 侧改动（归 SPEC-2 及其后续修订）。
- usage 的 Bundle 统计插件实现（若探针判定不可得，本 SPEC 只落降级标记，插件是独立后续）。
- 批内并行 dsh 实现（capabilities 依探针结论声明，降级串行可接受）。
- 车道级路由与跨 harness 回退。

## Decisions

1. **投影层是 adapter 的职责且以 fixtures 为契约**：normalize_event 把 dsh 的 session/text/thinking/tool_call/tool_result/final/error 投影为 claude 形状（母设计 §4.3 表 + SPEC-2 探针修正）；投影正确性的证据 = 读侧现有测试原样跑绿。备选「改读侧认 dsh 事件」被否：违背 canon 决策与行为零变化约束。
2. **stderr 分类器接口化而非 if-else**：provider_circuit 的 parse 函数族（provider_circuit.py:388-558）收拢为 per-adapter 分类器，claude 实现即现有文本模式原样搬移，dsh 实现按探针错误码表映射到现有分类枚举（ratelimit/unrecognized_model/transient/…）；熔断/瞬断/记账治理零改动。
3. **session id 命名空间 `fenix-<run_id>`**：满足 dsh id 字符规则（字母数字开头结尾），天然去重；resume 原样传 `--session-id`，dsh 的 fail-loud 采纳语义（未知 id 失败/被持有 refuse/cwd 不符拒绝）映射到「新 session 重跑」回退路径；跨 provider 禁令以 provider 指纹绑定 session 元数据实现。
4. **max_turns 用 turn_end 计数**：与 claude 通道同为 daemon 侧强制（CLI 均无此 flag），超限 kill 进程组，语义一致。
5. **健康检查白名单钉版本**：dispatch 前 `dsh --version` ∈ 白名单（当前仅 0.2.0-rc.2，随 Bundle 版本兼容表维护）+ DSH 隔离 profile 内 Bundle 挂载探测；未装/版本不符 fail-fast 且错误信息指向修复动作。白名单不做配置键（避免提前暴露配置面），随 Bundle README 版本表走代码常量。
6. **prompt 差异收敛到 `{harness_notes}` 单一占位符**：`_noninteractive_contract_section`（prompt_builder.py:787）与 agents/implementer.md 长任务等待节的 claude 行为模型描述参数化；claude 注入现状文本（快照对账零差异）、dsh 注入 headless 行为模型（无交互、stdin 喂入、终态以 result gate 为准）。Task 工具族契约段一字不改（Bundle 已补齐写侧）。
7. **banned env 扩充在 dsh 通道内完成**：ANTHROPIC_* 等防串扰键清理属 dsh_adapter.build_spawn_spec 的 env 段（AGENT_RUN_BANNED_ENV_KEYS 机制复用，扩充 dsh 专属键集）。

## Risks / Trade-offs

- [投影遗漏事件类型] → fixtures 覆盖 session/text/thinking/tool_call/tool_result/final/error 全类型 + 未知类型透传为忽略并计数的防御路径；真机冒烟兜底。
- [截断事件破坏 JSON 解析] → dsh 保证单行完整（32KiB 行上限内截断字段而非截断行）；解析器仍按行解析，truncated 标记透传。
- [dsh 版本漂移破坏投影] → 健康检查白名单拦截未钉版本；fixtures 契约测试在升级 SPEC 中重录。
- [usage 不可得影响成本可见性] → `usage_source: unavailable` 显式降级标记，dashboard 成本页显示缺口而非假数据。
- [judge 等一次性通道在 dsh 下的模型能力不足] → run_one_shot 已收编（SPEC-1），dsh 通道模型由 provider 链显式配置；验收归 SPEC-4 全链观察。

## Migration Plan

仓内新增 adapter + 少量 modify；`agent.harness` 缺省仍 claude，合并后无运行时切换；回滚 = revert（dsh 通道未被任何缺省路径依赖）。

## Open Questions

（无——usage 形态与 subagent 判定由 SPEC-2 探针证据关闭，本 SPEC 按结论分支实现。）
