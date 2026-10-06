# ADR-243：特性级 LLM 单发调用复用 agent spawn 通道，禁直连网关 HTTP

date: 2026-10-06
status: accepted

## Context

告警叙事等特性需要非交互的一次 LLM 调用。直连网关 HTTP 意味着第二套凭据、UA 与代理面：健康探测直连曾有 UA 遭 CF 1010 误拦的实测教训，且失效转移、熔断、超时等语义都要重复实现一遍；而 agent 车道已有的 spawn 通道（`claude -p` 非交互单发）已承载真实 baseurl/key/model 的 env 路由与配置隔离。

## Decision

特性级 LLM 单发调用（当前为告警叙事生成）一律经既有 agent spawn 通道执行：非交互单发 + 硬超时；模型经回退链解析（特性专属模型键 → `admin.agent_model` → 框架默认网关模型）；禁直连网关 HTTP、禁传 `--max-tokens-budget` 类实测高危旗标；通道经依赖注入（模块级 set_channel 或传参）可替换，测试注入假通道——不真调网关、不落 HOME 敏感配置。

## Consequences

- 凭据/UA/代理/熔断面保持单一复用，无新增维护面；模型路由与配置分级语义天然继承。
- 付出 spawn 进程启动开销，适用低频调用场景；高频批量场景须另立条目评估，不得绕过本裁定为单个特性私开 HTTP 客户端。
- 后续新增 LLM 辅助特性（摘要、命名、翻译类）沿用该通道与注入缝，测试隔离沿用假通道注入先例。
