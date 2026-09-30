<!-- 知识重建 2026-10-01：原文件为 untracked 产物，随 09-30 夜间工作区清理事故丢失；依 adr/index.md 摘要与归档 2026-09-30-add-code-review-concurrency-and-429-resilience design.md D3 重建。 -->

status: accepted
日期: 2026-09-30

# ADR-201：429 限流走切换类通道独立冷却，禁计入 4xx 熔断双计数

## Context

2026-09-24 manual_full run `code-review-1790204913` 被 bigmodel 网关 429 限流打死（705 turns/43min）。取证发现 429 不在 `ProviderCircuit.classify_switch_error()` 的切换类错误集（unrecognized_model/5xx/网络错）中，也不在 `PROVIDER_CIRCUIT_4XX`（400/401/403/404）里，CLI 内部重试耗尽后整 run `terminal_reason=api_error` 终态失败，无冷却、无重派。需要裁决 429 在错误分类体系中的归属与冷却语义。

## Decision

- 429 限流纳入切换类通道：分类签名保守三选——HTTP 429、错误码 `[1302]`、error type `rate_limit`，**任一**命中即判定（签名集收敛于显式限流形态，不做宽泛子串匹配；判定先于瞬断与 4xx 解析）。未知文本维持既有失败路径零行为变化。
- 独立限流冷却：复用 switch 冷却机制（同字段、同候选跳过语义），但用独立常量 `PROVIDER_RATELIMIT_COOLDOWN_SECONDS`（缺省 300s），不与 switch 冷却共用键；本期不做配置键，调参改常量。
- MUST NOT 计入 `PROVIDER_CIRCUIT_4XX` 熔断双计数：限流是暂时性配额压力，与配额/鉴权故障的 30min 熔断语义不同，双重计数会放大冷却。配额/鉴权类 HTTP 4xx 维持既有 provider 熔断语义、不纳入链前进。
- 全链同冷却：链上所有候选均处冷却期时 attempt 直接失败带 `chain_exhausted` 标记，不创建进程、不计入 spec 重试消耗。

## Consequences

- 429 命中后 provider 进入 300s 独立冷却，链选择自动跳过冷却期候选，不再整 run 直接终态失败。
- 新增错误类别时须显式声明所属通道与判定次序（防止未来类别撞车宽泛匹配）。
- 分类测试覆盖 2026-09-24 真实网关错误文本 fixture（当时文本不含全部三种签名，验证了「任一命中」口径的必要性）。
