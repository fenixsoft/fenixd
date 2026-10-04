# ADR-235：CLI stderr 噪声判别单源，与瞬态分类、error 归因降噪三源分离

date: 2026-10-05
status: accepted

## Context

claude CLI 对非 Anthropic 模型名在启动期固定打一条 stderr 诊断（`[claude-code:unrecognized_model]`），每 run 恰 1 条、成功与失败 run 同样在场、与失败/停滞零区分度。它随非 Anthropic 模型链成为常态后在两处证据位造成系统性污染：回填 run 失败归因取 stderr 尾部窗口恰被该行填满（真实死因如 429 限流文本被淹没），自省中途信号深扫的首条 stderr 摘要恒被其占位（连续自省窗口被同一噪声带偏）。与此同时，unrecognized_model 已被裁定从瞬态中收窄（确定性 failover，不进原地退避与瞬断熔断），run 终态 error 拼装另有宽口径降噪（裸前缀过滤、过滤后为空回退退出码）——同一 CLI 诊断族已存在三套各司其职的消费语义，各自内联判据会随消费端增加而漂移。

## Decision

噪声判别收口为单一常量与单一入口（`CLI_STDERR_NOISE_TEXT_PATTERNS` + `is_cli_stderr_noise`），按具体 pattern 枚举、行首锚定、逐行判别，全部消费端统一经此判别；新噪声形态逐个确认后追加，不做裸 `[claude-code:` 前缀一刀切。该常量与既有两套判据严格分离：`UNRECOGNIZED_MODEL_TEXT_PATTERNS`（裸子串形态，驱动拒模型确定性 failover 分类）保持独立、不收窄为结构化形态；`_denoise_stderr` 的宽口径 error 拼装降噪行为不变——三源语义有意不同、互不替代，噪声常量不得反向喂给瞬态分类。留证层（run 产物 jsonl、回填 stdout/stderr 双留档、admin stderr_tail 证据字段）一律不过滤，降噪只作用于摘要与归因消息。

## Consequences

消费端新增判噪需求零成本接入（导入判别入口即可），新噪声形态单点追加生效；代价是三套相似 pattern 并存，改动者须理解分工——排除前缀一刀切意味着新诊断形态须逐个登记，漏登时该行暂按真实证据放行（宁可多留证据，不可误删信号）。裸 `[claude-code:` 前缀同时是瞬断判定的既有信号源，前缀级过滤会静默摧毁该信号，此约束对任何后续降噪需求永久有效。
