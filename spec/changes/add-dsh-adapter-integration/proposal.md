## Why

SPEC-1 已交付 harness 抽象层与 claude 平移，SPEC-2 已交付 fenix-dsh Bundle 与真机探针结论。本 SPEC（依赖链第三环）实现 `DshAdapter` 并接入 fenixd：事件投影、stderr 分类、session 绑定、健康检查、prompt harness 注记参数化——使 `agent.harness: dsh` 从 fail-fast 变为可用的第二通道，为 SPEC-4 的全链验收铺路。母设计：`docs/superpowers/specs/2026-10-13-multi-harness-adapter-design.md` §4.3/§6/§7。

## What Changes

- 新增 `core/agent_runner/harness/dsh_adapter.py`：build_spawn_spec（`dsh headless --json [--session-id fenix-<run_id>]`、stdin 喂 prompt、cwd=worktree、banned env 扩充清理）、normalize_event 投影层（dsh 事件 → claude stream-json 形状，含 truncated 透传与 turn_end 计数 num_turns）、classify_stderr（探针错误码表 → 现有分类枚举）、extract_result（session_id/num_turns/usage 按探针结论降级标记）、process_patterns、capabilities（依 Bundle 探针判定）。
- provider_circuit stderr 分类器接口化：现有 claude 文本模式成为 claude 实现，dsh 按探针错误码表实现，分类枚举与熔断/瞬断治理不变。
- session 体系：dsh 通道 session id 用 `fenix-<run_id>` 命名空间；resume 经 `--session-id`；跨 provider resume 禁令同样适用。
- harness 工厂注册 dsh + dispatch 前置健康检查（`dsh --version` 白名单钉 0.2.0-rc.2 + Bundle 挂载探测），解除 SPEC-1 的 dsh fail-fast。
- prompt 参数化：`_noninteractive_contract_section` 与 agents/*.md 静态主体的 claude 行为模型段改为 `{harness_notes}` 占位符由 adapter 注入；Task 工具族契约段一字不改。
- usage 缺口降级：探针结论不可得时 metrics 标 `usage_source: unavailable`，成本统计降级不阻塞。
- **BREAKING：无**（claude 通道行为零变化；dsh 通道为新增）。

## Capabilities

### New Capabilities
- `dsh-harness-integration`: DshAdapter 的 spawn/投影/分类/session/健康检查契约与 prompt harness 注记参数化。

### Modified Capabilities

（无——harness-config（SPEC-1）的需求不变：dsh 值从「fail-fast 拦截」自然进入「可用」状态是该需求既有语义的兑现，非需求变更。）

## Impact

- 受影响代码：`core/agent_runner/harness/`（dsh_adapter 新增、工厂注册）、`runner.py`、`session.py`、`provider_circuit.py`、`prompt_builder.py`、`agent_env_keys.py`、`agents/implementer.md`。
- 测试输入：SPEC-2 的 `dsh-bundle/tests/fixtures/headless-events.jsonl` 与错误码表（投影与分类的契约源）。
- 不受影响：run jsonl schema 与全部读侧模块、claude 通道行为、dashboard 前端（usage 降级经既有 metrics 字段流转）。
- 对下游：SPEC-4 全链验收以本 SPEC 为前提。
