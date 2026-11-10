# 设计：add-maintenance-lane-provider-failover

## Context

2026-11-09 夜间 glm 周/月额度耗尽事故有两个断点：① dispatch attempt 环的切链闸门只读降噪后的 error 文本，429 证据只在 result 事件的 `api_error_status`/`result` 字段，导致链指针不动（已作为独立修复落地，commit 待定）；② 六条 LLM 维护车道（administrator / arbiter / self-review / evolution / code-review / code-fix）在 `core/agent_runner/maintenance_runs.py` 里各自手写「解析 assignment → 取下标 0 → 设 env → 调一次 `_run_agent`」，**完全没有链 failover**：`_write_lane_provider_marker` 也把 `chain_index=0/chain_len=1` 硬编码。即使 ① 修好，code-review 等车道仍然只会打链首候选，限额期间必然反复 429。

本变更只处理 ②：把 dispatch 环已验证的链选择/切换判定/冷却/归因原语接进六条 LLM 维护车道，保持各车道既有返回结构、降级路径、观测与 429 重派语义不变。

约束：
- ④（周/月额度类 429 的冷却时长）用户明确推迟，`PROVIDER_RATELIMIT_COOLDOWN_SECONDS=300` 本期不改。
- `_run_agent` 是车道唯一进程入口，返回 5 元组 `(output, turns, session_id, usage_info, stall_latency)`；`tests/test_run_agent_call_site_arity.py` 用 AST 校验解包宽度。
- `evolution` 车道的 `CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS="0"` 必须在 `_apply_provider_env` 之后注入（code-review item `4a65f8620c29` 顺序不变量）。
- `code-review` 车道的 429 归因依赖异常属性 `api_error_status` / `result_text` / `stderr_lines`；重派消费以原 manifest 复跑。
- 车道 run 证据读取依赖 provider_marker 行（`_admin_failure_evidence` 等）。

## Goals / Non-Goals

**Goals**
- 六条 LLM 维护车道在单 run 内按链换候选，遇 429/拒模型/5xx/连接类切换错误自动降级到下一未冷却候选。
- provider_marker 记录真实 `chain_index`/`chain_len`，换候选有日志。
- 429 终局重派按链解析，不固定复用链首。
- 复用 dispatch 环原语（`_switch_signal_text`、`classify_*`、`_record_switch_cooldown`、`annotate_model_chain_unavailable`、`PROVIDER_RATELIMIT_COOLDOWN_SECONDS`），单一真源。

**Non-Goals**
- 不改 429 冷却时长/策略（④）。
- 不把 `run_impl_ocr`（外部二进制 `bin/ocr_review.py`）纳入；不改 `run_regression`（不经 LLM）。
- 不改 manifest 格式、terminal-salvage 格式、降级/告警链路、每日派发计数（dispatch-only 现状）。
- 不把维护车道并入 dispatch attempt 环（不动 worktree/spec 重试/result gate 语义）。

## Decisions

### D1 共享助手收敛六处组装，而非逐车道复制
新增 `_run_lane_agent_with_failover(...)` 于 `maintenance_runs.py`，负责：解析链（由调用方传入已按角色回退顺序解析好的 `assignment`）→ 逐候选 `_select_chain_candidate` → `_apply_provider_env`（+`post_provider_env`）→ `_write_lane_provider_marker(..., chain_index, chain_len, attempt)` → `_run_agent` → 失败时用 `_switch_signal_text`/`classify_switch_error` 判定 → `_record_switch_cooldown` / `_record_unrecognized_model` → 换候选；成功即返回 5 元组。

- 备选 A：逐车道复制候选环。否决——六处必然漂移（`_apply_provider_env` 去重、`_write_lane_provider_marker` 抽取都是同因先例）。
- 备选 B：复用 `runner._execute_agent_inner`。否决——那是 dispatch 环，绑定 worktree、spec 重试计数、result gate、dispatch 观察钩子，拖入会改变车道语义并污染 spec accounting。

### D2 单 run 单 jsonl 多 attempt 事件流
不引入 `-aN` 子 run。所有消费面（manifest、terminal-salvage、`_extract_session_id`、`_ratelimit_terminal_hit` 尾部 64KiB、429 重派、admin 证据）都以 run_id 单文件为准；多 attempt 共用同一 jsonl 是既有 resume/重试形态的自然延伸。marker 追加 `attempt` 字段（additive，读侧忽略即兼容）。

- 备选：每候选一个子 run（dispatch 环 `-aN` 形态）。否决——会让 manifest/证据/重派需要跨文件聚合，超出本变更收益。

### D3 判定与冷却复用 dispatch 原语
`_run_lane_agent_with_failover` 内部只调 `runner._switch_signal_text(error, exc)` + `runner.classify_switch_error(...)`，禁止写任何车道本地文本匹配；429 冷却用 `_record_switch_cooldown(provider_name, cooldown_seconds=PROVIDER_RATELIMIT_COOLDOWN_SECONDS)`；拒模型用 `_record_unrecognized_model`；链尾归因用 `annotate_model_chain_unavailable`。①修复已把 `_switch_signal_text` 立为单一真源，这里直接复用，不留「纯文本回退」路径（那正是本次 bug）。

### D4 车道 failover 不续会话
六条车道现状从未向 `_run_agent` 传 `resume_session_id`，且跨 provider session 不可复用（session id 与 provider/模型绑定，dispatch 侧已有 dead-session 教训）。每候选开新会话；不做跨候选上下文接力。

### D5 429 终局 = 全链候选皆败；重派按链解析
- 车道内 429 冷却后换下一候选；全部候选皆 429 → 终局 429（异常保留 `api_error_status=429`、`result_text`、`stderr_lines`），交既有重派/告警路径。
- 重派意图（`ratelimit_redispatch` 事件）增 `chain_len` 与失败候选列表；`_consume_ratelimit_redispatch` 复跑时重新解析链并按当时冷却状态跳过候选（不固定 `assignment[0]`）。
- 300s 冷却时长本期不改（④）。

### D6 全链冷却/耗尽廉价失败
链全部候选处于 circuit/switch/ratelimit 冷却时，不启动进程，抛 `RuntimeError` 且文本含 `[model-chain-unavailable]`（经 `annotate_model_chain_unavailable` 标注最后错误或直接构造），不新增终态字，交各车道既有降级/告警（admin 证据、code-review 停滞告警、evolution 失败记录）。

### D7 车道专属 env 后置注入
helper 接受 `post_provider_env: dict`，在每个候选的 `_apply_provider_env` 之后合并，保持 evolution 的 `CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS=0` 顺序不变量。

## Risks / Trade-offs

- **同一 jsonl 多 attempt 导致指标重复**：读侧取末条 result/metrics 口径不变；新增测试断言唯一终态 metrics，避免重复写 `run_metrics` 之外的多余终态事件。
- **车道总时长随链长线性放大**：候选上限 = 链长、不新增计时器、不新增后台线程；车道级窗口/看门狗沿用既有调度器与 supervisor 语义。
- **桩 runner 缺簿记方法**：helper 对 `_record_daily_provider_attempt` 等可选接线用 `getattr(..., None)` fail-open，保证测试替身不炸。
- **六车道行为漂移**：helper 用显式参数（spec_name、agent_type、max_turns、post_provider_env、fallback_model）承接差异；每车道各补一条回归用例。
- **依赖 ① 修复**：`_switch_signal_text` 必须存在（同 release 已落地）；若在旧代码上单独 cherry-pick 本 SPEC，helper 须 fail-loud（AttributeError）而非静默回退。
- **观测契约变化**：marker 的 `chain_len` 从恒 1 变为真实链长；读侧已有「链长=1 表示单候选」语义，向后兼容；新增换候选日志为 additive。

## Migration

无数据迁移。provider_marker 追加字段为 additive；manifest/terminal-salvage 格式不变；`STATE.md` 无 schema 变化。回滚 = revert 本次 commit；已写 run jsonl 无需改写。

## Open Questions

- `run_impl_ocr` 是否另立 SPEC 纳入链 failover（当前外部二进制，非 `_run_agent`）。
- 车道 failover 是否计入每日 provider 派发计数（现仅 dispatch 环计入，`_record_daily_provider_attempt`）。
- 候选尝试上限是否需要配置键（当前固定 = 链长）。
