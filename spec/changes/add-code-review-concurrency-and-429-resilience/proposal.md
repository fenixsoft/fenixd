# 提案：add-code-review-concurrency-and-429-resilience

## Why

2026-09-24 早上 manual_full 全仓审查 run `code-review-1790204913` 死于 bigmodel 网关 429 限流（烧 $23.68）：主 agent + 6 个 async 子代理 + 后台 ocr scan 并发打同一账号，43 分钟 705 turns。两处治理缺口——① 全仓审查的并发完全不受控（ocr scan 不传 `--concurrency` 走其内部缺省 8；子代理扇出波次由 agent 自由裁量，提示词无上限）；② 网关 429 不在任何容错分类里（`provider_circuit.PROVIDER_CIRCUIT_4XX` 只收 400/401/403/404，switch 冷却只收 unrecognized_model/5xx/网络错），CLI 重试耗尽即整 run 终态失败。事故的另外两个缺陷（分片名推导错位、error 收场无抢救）已在热修 1b83c1c1 落地，本 SPEC 治理剩余的「限流成因」与「限流韧性」。

## What Changes

- 新增配置键 `verify.repo_code_review_concurrency`（正整数，缺省 4，fail-open 语义与 `get_impl_code_review_concurrency` 同款）：控制**全仓审查**（后台定期执行 + 手动按钮触发的 manual_full/manual_window run）的并行审查度——同时注入两处：提示词侧子代理并行扇出上限（波次规模）、`ocr scan --concurrency <n>`。
- Dashboard 设置界面（QualityPanel）新增该键；`config_admin` 读写链路与 `.fenix/config.template.yaml` 示例同步（模板示例值必须等于缺省 4，防止模板派生配置恒为显式旧值）。
- 现有键 `verify.impl_code_review_concurrency`（缺省 4，控制 implement 任务内审查）语义不变，在 UI 上与新增键并列展示为「SPEC 审查并发」与「全仓审查并发」两组。
- **Modified `failover-dispatch`**：429 类限流错误（HTTP 429 / 错误码 [1302] / error type rate_limit）纳入 provider 熔断/切换冷却分类——命中时该 provider 进入冷却期，冷却期内链选择跳过该候选；被 429 打死的 run 按 failover 语义自动重派（受既有预算/重试上限守卫，不无限重试），而非直接终态失败升级人工。

## Capabilities

### New Capabilities
- `repo-review-concurrency`: 全仓审查并发配置化——一个键同时约束全仓审查 run 的子代理扇出与 ocr scan 并行度，缺省 4，带 Dashboard 设置界面。

### Modified Capabilities
- `failover-dispatch`（现规格见 `spec/archive/2026-09-02-add-provider-failover/specs/failover-dispatch/spec.md`）: 429 限流从「无分类、run 直死」改为「provider 冷却 + run 自动重派」，复用既有 switch 冷却与候选跳过机制。

## Impact

- **代码**：`core/config.py`（新读取器）、`core/agent_runner/maintenance_runs.py` + `core/agent_runner/prompt_builder.py` + `agents/code-review.md`（并发注入）、`core/agent_runner/provider_circuit.py`（429 分类/冷却）、provider 链选择与 run 失败分类消费点（429 → 重派路径）
- **Dashboard**：`core/dashboard/data/config_admin.py`、`core/dashboard/static/src/pages/settings/components/QualityPanel.tsx`、`core/dashboard/static/src/services/dashboard.ts`
- **配置**：`.fenix/config.template.yaml`（tracked，示例值同步）
- **测试**：`tests/test_code_review.py`、`tests/test_provider_circuit.py`、`tests/test_provider_failover.py`
- **风险**：并发注入只影响 code-review 车道提示词与 ocr 参数，不改派发器全局并发（`agents.max_concurrent`）语义；429 重派必须与既有预算上限（`agents.impl_run_budget_max` 族）和 escalation 节流协同，防止限流期重派风暴
