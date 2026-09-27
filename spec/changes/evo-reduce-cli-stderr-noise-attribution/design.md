# design: reduce-cli-stderr-noise-attribution

## D1 噪声常量收口

core/agent_runner/provider_circuit.py:80 的 UNRECOGNIZED_MODEL_TEXT_PATTERNS 收口导出为可复用的 CLI stderr 诊断噪声常量（按具体 pattern 枚举 unrecognized_model 等 [claude-code:*] 启动期诊断行，新噪声加枚举即可）；:405-423 分类判据与 :443-479 瞬断判定一行不动（add-impl-selfcheck-model-probe 的收窄决策不反向推翻）。

落地形态（评审修补，防歧义）：**新增独立兄弟常量**（如 `CLI_STDERR_NOISE_TEXT_PATTERNS`），既有 `UNRECOGNIZED_MODEL_TEXT_PATTERNS`（:80）元组**原样保留**，继续作为 `classify_unrecognized_model_error` 判据的 pattern 源（:420 是全仓唯一 pattern 引用点）——MUST NOT 原地改写/重命名/被新常量替换：其裸子串形态（`unrecognized_model` / `unrecognized model`）若被收窄为结构化形态，会静默改变瞬态分类行为，违反本 spec「SHALL NOT 改变瞬态分类判据」。

与既有降噪的关系（评审修补）：runner.py:5094 `_denoise_stderr`（error-attribution-denoise D5 已交付）已按裸 `^[claude-code:` 前缀过滤 error 文本、过滤后为空回退 Exit code 形态——其语义（宽、裸前缀）与新常量（窄、具体枚举）**有意不同、互不替换**；本变更不重指 `_denoise_stderr` 的 pattern 源，避免触碰已固化的 error 降噪行为及瞬断判据前置（classify_transient_error docstring 明令不得读降噪后的 error 字符串反推）。

## D2 深扫消费端

core/self_review.py 的 _scan_run_midflight（:854-919）stderr 分支：first_stderr 选取（:902-903）跳过噪声行，stderr_count 保留全量计数，全噪声置空；dashboard 侧已有同题先例（core/dashboard/static/tests/runStreamNoise.test.mjs:122-124，stderr 非错误行静默，fixture 正是 unrecognized_model）可对照。

## D3 归因消费端

core/knowledge_backfill.py:426-430 归因文本构造：先按噪声常量逐行过滤 stderr，取过滤后尾部 400 字符；过滤后为空则回退 stdout 尾部（.out 文件已双留档 stdout+stderr，仅归因消息受影响）。stdout 亦为空时归因仅保留既有退出码前缀（「claude -p 回填 run {id} 退出码 N」形态），与 runner._denoise_stderr「过滤后为空回退 Exit code」惯例一致；回退取 stdout 尾部时**不过滤**（[claude-code:*] 诊断行只写 stderr，stdout 无此噪声）。

## D4 测试

- tests/test_self_review_midflight.py：扩展现有 stderr 采集用例（:256 real_stream_json_shape 用例附近），fixture 用「unrecognized_model 噪声行 + 真实诊断行」断言不占位；补全噪声置空例。
- tests/test_knowledge_backfill.py：断言归因文本无噪声；stderr 全噪声且 stdout 含 429 文本时回退 stdout 尾部。

## 非目标

瞬态判据（runner.py:3058-3066、provider_circuit.py:405-479）、模型链命名与 --model 传参、熔断阈值、admin 告警链（evo-alert-noise-governance）均不动。core/agent_runner/maintenance_runs.py:97-102 的 admin 失败证据字段 stderr_tail 亦**不过滤**（评审修补，点名豁免）：该字段按 error-attribution-denoise D5 语义独立留证（docstring 明令原始 stderr 只进独立证据、不得回填 error 归因文本），且 admin 通道 unrecognized_model 秒败本身是瘫痪判别信号，滤掉即毁证。

## 风险

- 过滤误伤未来出现的真实 [claude-code:*] 错误行：常量按具体 pattern 枚举而非裸前缀一刀切，新噪声入白名单须逐个确认。
- CLI 词表演进致噪声行变化：pattern 集中一处定义，改一处生效。