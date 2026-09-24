# 设计：add-code-review-concurrency-and-429-resilience

## Context

2026-09-24 早上 manual_full run `code-review-1790204913` 被 bigmodel 网关 429 限流打死（705 turns/43min，$23.68）。取证结论：① 全仓审查并发不受控——`ocr scan` 不传 `--concurrency` 时走其内部缺省 8（用户确认），子代理扇出波次由主 agent 自由裁量（本 run 派 6+5 两波）；② 429 不在 `ProviderCircuit.classify_switch_error()` 的切换类错误里（unrecognized_model/5xx/网络错），也不在 `PROVIDER_CIRCUIT_4XX`（400/401/403/404）里，CLI 内部重试耗尽后整 run `terminal_reason=api_error` 终态失败。事故的另两缺陷（分片名推导、error 收场无抢救）已由热修 1b83c1c1 落地，不在本 SPEC 范围。

既有可复用机制：switch 冷却（`PROVIDER_SWITCH_COOLDOWN_SECONDS=300`，链选择跳过冷却候选、全链冷却 chain_exhausted 直接失败）、provider_marker 可观测、`impl_code_review_concurrency` 的 fail-open 读取器范式（add-impl-code-review-tuning）、config_admin 设置回写链路与 QualityPanel（verify.* 键的 UI 宿主）。

## Goals / Non-Goals

**Goals**
- 全仓审查并发一个键控住两处并发源（子代理扇出 + ocr scan），缺省 4。
- 429 命中 provider 冷却 + run 自动重派一次，run 不再直接终态失败。
- 设置界面可改、模板同步、可观测（重派留痕）。

**Non-Goals**
- 不改派发器全局并发（`agents.max_concurrent`）语义。
- 不做跨账号流量调度/多账号轮询；failover 仍限于既有 provider 链。
- 不动 `verify.impl_code_review_concurrency`（SPEC 审查并发）既有语义与缺省。

## Decisions

- **D1 配置读取器单点缺省**：新增 `ConfigLoader.get_repo_code_review_concurrency`，判据与 `get_impl_code_review_concurrency` 逐条同款（正整数 int，bool 不算，脏值回退 4）；MUST NOT 进 `resolve_config` 缺省填充列表（先例：impl 并发键的同款约束）。
- **D2 并发注入走提示词与 scan 参数，不做框架侧强拆**：主 agent 保留切批自治权，提示词新增「同时至多 N 个子代理（波内并行），波次滚动推进」硬条款（`{repo_concurrency}` 占位符由 `_build_code_review_prompt` 注入）；scan 命令模板加 `--concurrency {repo_concurrency}`。理由：框架侧代理池化改造动 agent_runner 核心，收益不抵风险；LLM 对显式数值上限的遵从性高（禁 async 收工条款同范式）。
- **D3 429 分类进 `classify_switch_error`，独立限流冷却常量**：签名匹配保守三选——HTTP 429、错误码 `[1302]`、`rate_limit` 文本。复用 switch 冷却通道（同字段/同跳过语义）但用独立常量 `PROVIDER_RATELIMIT_COOLDOWN_SECONDS`（缺省 300s）便于调参；MUST NOT 计入 `PROVIDER_CIRCUIT_4XX`（避免与 30min 熔断双重惩罚）。改动点：`core/agent_runner/provider_circuit.py`（分类+冷却入口）、`core/agent_runner/runner.py`（attempt 失败消费点，≈1891 行区域）、`core/pm_engine/verification/infra_classify.py` 文档串同步。
- **D4 429 重派挂 run 失败分类消费点，上限 1 次**：run 终态归因为 429（复用 D3 分类器）且该 spec/run 未超重派上限（常量 1）时，冷却到期后以原上下文重派；code-review 车道复用原 manifest（幂等：聚合读侧按 file 去重 + 提示词「不重审」纪律，热修 1b83c1c1 的 error 抢救保证死前产物不丢）。重派计一次 attempt，受既有预算/escalation 守卫；运行记录 run jsonl 标注 `ratelimit_redispatch`。重派执行者分工：runner 只负责终态归因与意图登记；意图消费与冷却到期后的延迟重投递落在 `run_code_review` 唯一生产调用方 `core/admin_monitor.py` 的 `_worker` 收场分支（run 已终态死亡，进程内无人续跑，须由调用侧重投递；见 tasks 5.3）。
- **D5 模板示例值=缺省值**：`.fenix/config.template.yaml` 的 `verify.repo_code_review_concurrency` 示例写 4（tracked 文件；add-impl-code-review-tuning 的教训——模板显式值≠缺省值时模板派生配置恒为显式值，缺省调整失效）。
- **D6 UI 与回写链路同批交付**：`config_admin` 的 verify 白名单与 QualityPanel 输入项、`services/dashboard.ts` 类型同步；两键并列展示为「SPEC 审查并发」「全仓审查并发」（新增配置不带 Dashboard 界面是本仓明令禁止项）。

## Risks / Trade-offs

- **重派风暴**（限流期反复重派）：重派上限常量 1 + 既有预算守卫 + provider 冷却期内不派发；MUST NOT 在冷却期内立即重试。
- **分类误判**（错误文本撞车）：签名保守（三选**任一**命中即分类，签名集收敛于 HTTP 429 / `[1302]` / `rate_limit` 三种显式限流形态，不做宽泛子串匹配；与 tasks 4.1「任一签名」同口径——2026-09-24 实测 fixture 文本并不含全部三种签名，若按「全匹配」则 fixture 自身无法分类），未知文本维持既有失败路径；测试覆盖 2026-09-24 真实错误文本 fixture。
- **LLM 不遵从扇出上限**：条款置于「分批/并行审查落盘纪律」段内与其余硬条款并列（违反=run 判失败措辞），验证场景含提示词渲染断言；残余风险接受（实际并发≈min(配置, agent 裁量)，429 韧性由 D3/D4 兜底）。
- **UI 改动回归**：QualityPanel 既有输入项多，遵循 screen-xs 作用域与现有表单模式，验证场景含两键独立保存。

## Migration Plan

纯增量：新配置键缺省 4 即「不配置也生效」；429 分类/重派对既有错误路径是旁路新增（未知错误文本零行为变化）。无数据迁移。

## Open Questions

无（并发语义、缺省值、重派上限均已与用户确认）。
