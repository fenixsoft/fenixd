# fix-spec-review-infra-attribution-bridge

## Why

2026-10-03T19:31Z 上游账户级 429 限流撞上批量评审窗口：8 个 spec 在 4.58 秒内晋升并同时派评审，spec_review 车道虽然早已有 infra/content 失败分类（infra 不计 3 次评审预算、熔断冷却），但「这是限流」的信号在跨层传递时丢失——runner 异常上挂的 api_error_status=429 被 run_spec_review 的 catch-all 降级为纯文本，AgentRunResult 无结构化字段承载，降噪后 stderr 只剩 Exit code: 1，文本分类恒 False，限流被当评审质量失败 18 秒烧光预算、冻结 4 个 spec；冻结文案套「用户指令冻结」前缀又命中有意等待豁免（_INTENTIONAL_PAUSE_MARKERS），压制了自动恢复，最终需一轮人工处置会话解冻。

## What Changes

1. （P0）归因桥接：AgentRunResult 增加 api_error_status / conn_error 结构化字段；run_spec_review 的 catch-all 从异常回填；_handle_review_failure 优先读结构化字段判 infra，文本分类作为回退——命中即走既有 infra 分支（不烧预算 + 熔断 30 分钟冷却自动生效），无需新增车道结构。
2. （P0）评审在飞上限：评审车道增加在飞并发上限（_REVIEW_INFLIGHT_CAP，建议 2-3、可配），命中时条目保留队列不 pop，削掉批量晋升的并发峰值（风暴源头振幅）。
3. （P1）content 重试短退避：评审质量类失败重派前加一档短延迟（判重 Timer），infra 分支语义不动（其节奏已由熔断负责）。
4. （P1）冻结文案区分：评审自动冻结换用与「用户指令冻结」可区分的评审专用前缀（按根因分档）；硬约束——保留「原状态 reviewing」子串供 parse_orig_status 解冻还原、新前缀不得命中 _INTENTIONAL_PAUSE_MARKERS 短语或以 "frozen:" 开头（不得挪用有意等待豁免）、不得修改 FREEZE_ERROR_PREFIX 常量（freeze_spec 人工冻结的豁免语义依赖它）、仍走 freeze_for_human 成对入口。供给瞬态的自动恢复由第 1 条归因桥接 + 既有熔断冷却承载（infra 分类不冻结、不递增尝试），本条属冻结文案归因准确化，不改变冻结转人工语义。

## Impact

- Affected specs: 无（新增能力 spec-review-infra-attribution；与 evo-add-code-review-ratelimit-resume、evo-add-codefix-conn-error-cooldown 互补——本 SPEC 把同型归因桥接进 spec_review 车道的既有分类骨架）
- Affected code:
  - core/agent_runner/result_gate.py（AgentRunResult 字段）
  - core/agent_runner/runner.py（catch-all 回填）
  - core/pm_engine/spec_review.py（归因消费 + content 短退避）
  - core/pm_engine/dispatch/queue.py（评审在飞上限）
  - core/state_machine.py（冻结前缀区分）
  - tests/test_spec_review_infra_attribution.py（新增测试）

不改变评审预算 3 次、冻结/告警成对契约与回写门 fail-closed 语义；不改动 code_review / code_fix 车道。