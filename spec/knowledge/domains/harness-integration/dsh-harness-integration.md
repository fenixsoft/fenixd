# DshAdapter 接入

<!-- knowledge: capability=dsh-harness-integration rev=1
     sources=spec/archive/2026-10-30-add-dsh-adapter-integration -->

第二 harness 通道（dsh）的 fenixd 侧接入：spawn、事件投影、stderr 分类、session、健康检查、prompt 注记——使 `agent.harness: dsh` 成为可用的第二通道，claude 通道行为零变化。

## 规则

- **spawn 契约**：argv 形如 `dsh headless --json [--session-id <id>]`；prompt 全文经 stdin 载荷传入；cwd 为 worktree 路径；env 段清除 ANTHROPIC_* 等防串扰键（AGENT_RUN_BANNED_ENV_KEYS 机制复用并扩充 dsh 专属键集）；模型经 Bundle 配置显式渲染（provider 链 name/baseurl/apikey/model），MUST NOT 依赖 dsh 默认档。
- **事件投影到 canon**：`normalize_event` 将 dsh 事件流投影为 claude stream-json 形状写入 run jsonl——session→init（session_id+tools）、text→assistant text block、tool_call/tool_result→tool_use/user block、final→result（output/num_turns/session_id/usage 形状）、error→error 事件；`truncated` 标记透传；num_turns 由 turn_end 计数（max_turns 为 daemon 侧强制、超限 kill 进程组，与 claude 通道语义一致）；未知事件类型忽略并计数、不中断流。投影正确性以 Bundle 探针 fixtures 为契约测试源，读侧现有测试（run_task_track/liveness/result_gate）原样复用。失败语义可终判：「exit 1 + turn_end（aborted）」与「error 事件且无 final」两形态投影后 run jsonl 末行均为 `RUN_TERMINAL_EVENT_TYPES` 可判定终态，不产生悬挂在飞。
- **stderr 分类接口化**：provider_circuit 按 harness adapter 分派 stderr 分类器——claude 实现为现有文本模式（行为不变），dsh 实现按探针错误码表把 `dsh: <code>: <message>` 映射到现有分类枚举（ratelimit/unrecognized_model/transient 等）；分类枚举、熔断、瞬断、记账治理零改动（dsh 429 与 claude 通道同走熔断/退避路径）。
- **session 绑定与续跑**：dsh 通道 session id 使用 `fenix-<run_id>` 命名空间；resume 经 `--session-id` 传入；跨 provider resume 禁止（session 元数据绑定 provider 指纹）；dsh 采纳失败（未知 id/被持有/cwd 不符，fail-loud）回退为新 session 重跑路径并留痕，MUST NOT 悬挂。
- **健康检查与工厂注册**：harness 工厂注册 dsh；dispatch 前置健康检查验证 `dsh --version` 在白名单（钉 Bundle 兼容表的 release，随版本表走代码常量、不做配置键）且 Bundle 可挂载（DSH 隔离 profile 探测）；不满足 fail-fast 且错误信息含修复指引；检查通过后 `agent.harness: dsh` 全链走 DshAdapter，MUST NOT 静默回退 claude。
- **prompt harness 注记参数化**：`_noninteractive_contract_section` 与 agents 静态主体的 harness 行为描述收敛为 `{harness_notes}` 占位符由 adapter 注入——claude 注入 claude 行为模型文本（快照测试锚定为逐字节恒等替换），dsh 注入 headless 行为模型（无交互、stdin 喂入、产物以 result gate 为准）；Task 工具族契约段一字不改（claude 与 dsh 通道的同车道 prompt 差异全部落在 harness_notes 段）。
- **usage 降级标记**：探针结论为 dsh final 不携带 usage 时，metrics 标 `usage_source: unavailable` 并使成本统计降级显示（零值+来源标记），MUST NOT 伪造数值；结论为可得时按 claude 同形状解析。
- **新采集链路可观测性**：dsh 事件流作为首个新采集链路，投影管线与功能交付同批含三件——原始 dsh 事件 dump（采集输入原样落盘 run 目录旁路文件）、投影管线逐级计数（各事件类型收到/投影/忽略计数）、坏事件分类统计（JSON 解析失败/未知类型/超限截断三类）；落 run_metrics 同通道结构化日志，MUST NOT 仅散落 print；可与投影后 run jsonl 对账。

## 溯源

- 2026-10-30 add-dsh-adapter-integration（spec/archive/2026-10-30-add-dsh-adapter-integration） — 新增本能力：DshAdapter spawn/投影/分类/session/健康检查契约、{harness_notes} prompt 参数化（解除 harness-config 的 dsh fail-fast）、usage 降级标记、采集链路可观测性三件套
