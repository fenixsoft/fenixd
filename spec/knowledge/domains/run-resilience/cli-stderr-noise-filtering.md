# CLI stderr 诊断噪声统一判别与降噪

<!-- knowledge: capability=cli-stderr-noise-filtering rev=2
     sources=spec/archive/2026-10-05-evo-reduce-cli-stderr-noise-attribution,spec/archive/2026-10-08-evo-split-self-review-stderr-noise-count -->

claude CLI 启动期诊断噪声行（`[claude-code:unrecognized_model]` 等，非 Anthropic 模型名 run 每 run 恒 1 条、与失败/停滞零区分度）的框架级判别与降噪：判别收口单源，自省深扫与回填失败归因等消费端共用同一常量，防止无害诊断行挤占真实故障证据。

## 规则

- 判别单源：CLI stderr 噪声判别收口为 `core/agent_runner/provider_circuit.py` 的 `CLI_STDERR_NOISE_TEXT_PATTERNS` 常量与 `is_cli_stderr_noise` 入口，全部消费端统一经此判别，不在各自模块复制 pattern；常量按具体 pattern 枚举，新噪声形态逐个确认后追加，MUST NOT 裸 `[claude-code:` 前缀一刀切（诊断行可能携带真实错误语义，且该前缀是瞬断判定的既有信号源）。
- 逐行判别：pattern 以 `^` 行首锚定，`is_cli_stderr_noise` 只对单行文本有意义，整段多行文本一次匹配只锚首行，禁止整段匹配。
- 与拒模型瞬态分类分离：同模块 `UNRECOGNIZED_MODEL_TEXT_PATTERNS`（裸子串形态）独立保留，是拒模型确定性 failover 分类（unrecognized_model 不算瞬态、不进原地退避与瞬断熔断计数）的唯一 pattern 源；噪声常量 MUST NOT 改写、收窄或替换它，也不得反向喂给瞬态分类——裸子串与结构化行首两种形态语义有意不同、互不替代。
- 与 error 归因降噪分层：runner `_denoise_stderr` 的宽口径降噪（裸前缀过滤、过滤后无剩余回退 `Exit code` 形态）行为不变，噪声常量不重指其 pattern 源；瞬断判定与 dispatch 分类不得读降噪后的 error 文本反推，必须用原始 stderr 或结构化标记。
- 自省深扫降噪：深扫 stderr 分支的首条 stderr 摘要取首条非噪声行（截断 ≤140 字符），stderr 全为噪声行时摘要置空、不回填噪声；stderr 计数按噪声分离——`stderr_count` 只计非噪声行，噪声行单独计入 `stderr_noise_count`。
- 回填失败归因降噪：回填 run 失败归因文本先按噪声常量逐行过滤 stderr，再取过滤后尾部 400 字符；过滤后为空回退 stdout 尾部 400 字符（stdout 不过滤——`[claude-code:*]` 诊断行只写 stderr）；stdout 亦为空时归因仅保留退出码前缀（「claude -p 回填 run {id} 退出码 N」形态）。
- 降噪不触原始留证：过滤只作用于摘要与归因消息，run 产物 jsonl 的 stderr 事件与回填 stdout/stderr 双留档保持全量原始内容，取证现场完整。
- admin 证据字段豁免：admin 通道失败证据字段 `stderr_tail` 不过滤、按原始 stderr 独立留证（admin 通道 unrecognized_model 秒败本身是瘫痪判别信号，滤掉即毁证）。

## 关键行为

噪声行由 CLI 对非 Anthropic 模型名在启动期固定打出，出现与否由模型名唯一决定（glm/deepseek 链 run 全有、claude 链零有），成功与失败 run 同样在场。它高频占据失败证据位却不含死因信息：失败归因取 stderr 尾部窗口时恰被其填满（真实死因如 429 限流文本被淹没），自省深扫的首条 stderr 摘要恒被其占位（连续自省窗口被同一噪声带偏）。判别收口单源后，新噪声形态只需向常量追加一个 pattern。

## 溯源

- 2026-10-05 evo-reduce-cli-stderr-noise-attribution（spec/archive/2026-10-05-evo-reduce-cli-stderr-noise-attribution） — 新增噪声判别单源常量与入口、深扫首条 stderr 摘要跳噪与全噪声置空、回填失败归因过滤回退 stdout、admin 证据字段 stderr_tail 豁免
- 2026-10-08 evo-split-self-review-stderr-noise-count（spec/archive/2026-10-08-evo-split-self-review-stderr-noise-count） — 修订自省深扫消费端的 stderr 计数口径：`stderr_count` 只计非噪声行、噪声行单列 `stderr_noise_count`（取代「stderr 计数保留全量」的计数条款）
