## ADDED Requirements

### Requirement: DshAdapter spawn 契约

`DshAdapter.build_spawn_spec` MUST 产出：argv 形如 `dsh headless --json [--session-id <id>]`；prompt 全文经 stdin 载荷传入；cwd 为 worktree 路径；env 段清除 ANTHROPIC_* 等防串扰键（banned env 扩充集）；模型经 Bundle 配置显式渲染（provider 链 name/baseurl/apikey/model），MUST NOT 依赖 dsh 默认档。

#### Scenario: spawn 契约快照

- **WHEN** 以代表 lane 的 SpawnRequest 驱动 DshAdapter.build_spawn_spec
- **THEN** argv 含 `headless` 与 `--json`、stdin 为完整 prompt、cwd 为 worktree、env 无 ANTHROPIC_* 残留、Bundle 模型配置含显式 model

### Requirement: 事件投影到 canon 形状

`normalize_event` MUST 将 dsh 事件流投影为 claude stream-json 形状写入 run jsonl：session→init（session_id+tools）、text→assistant text block、tool_call/tool_result→tool_use/user block、final→result（output/num_turns/session_id/usage 形状）、error→error 事件；`truncated` 标记 MUST 透传；num_turns 由 turn_end 计数；未知事件类型 MUST 忽略并计数，MUST NOT 中断流。投影层 MUST 以 SPEC-2 探针 fixtures 为契约测试源，读侧现有测试（run_task_track/liveness/result_gate）MUST 原样复用全绿。

#### Scenario: fixtures 回放接通成对契约

- **WHEN** 回放 SPEC-2 的 headless-events.jsonl 经投影写入临时 run jsonl
- **THEN** run_task_track 能解析出 TaskCreate/TaskUpdate 进度（1 基 taskId），liveness 终态判定与 result_gate 读侧逻辑不受影响

#### Scenario: 失败语义可终判

- **WHEN** 流以「exit 1 + turn_end（aborted）」结束或以「error 事件且无 final」结束
- **THEN** 两种形态投影后 run jsonl 末行均为 `RUN_TERMINAL_EVENT_TYPES` 可判定的终态，不产生悬挂在飞

### Requirement: stderr 分类接口化

provider_circuit MUST 按 harness adapter 分派 stderr 分类器：claude 实现为现有文本模式平移（行为不变）；dsh 实现按 SPEC-2 错误码表把 `dsh: <code>: <message>` 映射到现有分类枚举（ratelimit/unrecognized_model/transient 等）。分类枚举、熔断、瞬断、记账治理 MUST 零改动。

#### Scenario: dsh 429 归因到 ratelimit

- **WHEN** dsh 通道 stderr 出现探针记录的限流类错误行
- **THEN** 分类为 ratelimit 并进入与 claude 通道一致的熔断/退避治理路径

#### Scenario: claude 分类行为不变

- **WHEN** 以 claude 通道既有 stderr 用例回放分类器
- **THEN** 分类结果与现状全等（快照）

### Requirement: session 绑定与续跑

dsh 通道 session id MUST 使用 `fenix-<run_id>` 命名空间；resume MUST 经 `--session-id` 传入；跨 provider resume MUST 被禁止（session 元数据绑定 provider 指纹）；dsh 采纳失败（未知 id/被持有/cwd 不符）MUST 回退为新 session 重跑路径并留痕，MUST NOT 悬挂。

#### Scenario: resume 失败回退不悬挂

- **WHEN** resume 传入的 session id 在 dsh 侧不存在（fail-loud）
- **THEN** 该 attempt 以新 session 重跑，run 记录含回退留痕，无假在飞

### Requirement: 健康检查与工厂注册

harness 工厂 MUST 注册 dsh；dispatch 前置健康检查 MUST 验证 `dsh --version` 在白名单（钉 SPEC-2 Bundle 兼容表的 release）且 Bundle 可挂载；不满足 MUST fail-fast 且错误信息含修复指引。`agent.harness: dsh` 在检查通过后 MUST 全链走 DshAdapter，MUST NOT 静默回退 claude。

#### Scenario: 未装 dsh 时 fail-fast

- **WHEN** `agent.harness: dsh` 且 `dsh --version` 不可用或不在白名单
- **THEN** dispatch 以含「版本」与修复指引的错误失败，无 run 被代跑

#### Scenario: 就绪后全链走 dsh

- **WHEN** 健康检查通过且 `agent.harness: dsh`，触发任一车道 dispatch
- **THEN** spawn 的是 dsh 进程（DshAdapter.spec），attempt 环/监督/终态收口全链按归一化事件正常运转

### Requirement: prompt harness 注记参数化

`_noninteractive_contract_section` 与 agents 静态主体的 harness 行为描述 MUST 收敛为 `{harness_notes}` 占位符由 adapter 注入：claude 注入现状文本（与改造前逐字节一致），dsh 注入 headless 行为模型（无交互、stdin 喂入、产物以 result gate 为准）。Task 工具族契约段 MUST 一字不改。

#### Scenario: claude prompt 零差异

- **WHEN** 以 claude adapter 组装任一车道 prompt
- **THEN** 与改造前快照逐字节一致（仅占位符替换为原文）

#### Scenario: dsh prompt 差异仅限 harness_notes

- **WHEN** 对比 claude 与 dsh 通道组装的同车道 prompt
- **THEN** 差异全部落在 harness_notes 段，TaskCreate/TaskUpdate 契约段内容一致

### Requirement: usage 降级标记

当探针结论为 dsh final 不携带 usage 时，metrics MUST 标 `usage_source: unavailable` 并使成本统计降级显示（零值+来源标记），MUST NOT 伪造数值；若探针结论为可得，则按 claude 同形状解析。

#### Scenario: 降级标记落 metrics

- **WHEN** dsh 通道 run 收口且 usage 不可得
- **THEN** run metrics 含 `usage_source: unavailable`，成本聚合不产生假数据

### Requirement: 新采集链路可观测性

dsh 事件流作为首个新采集链路，投影管线 MUST 与功能交付同批含可观测性交付项：原始 dsh 事件 dump（采集输入原样落盘 run 目录旁路文件）、投影管线逐级计数（各事件类型 收到/投影/忽略 计数）、坏事件分类统计（JSON 解析失败/未知类型/超限截断三类）。计数与统计 MUST 落结构化日志（run_metrics 同通道），MUST NOT 仅散落 print。

#### Scenario: 可观测性三件套随首个采集交付

- **WHEN** dsh 通道完成一次含工具调用的真实 run 并检查其取证产物
- **THEN** 原始事件 dump 文件存在，run_metrics 日志含三类事件计数与坏事件分类统计，可与投影后 run jsonl 对账
