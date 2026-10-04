# 验证报告：evo-reduce-cli-stderr-noise-attribution

> ⚠️ 本报告由框架于 2026-09-27T18:42:07Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。
> 报告时效标记（判定本报告是否属上一轮）：合成源轮次指纹：report.json@2026-09-27T18:42:07.760053+00:00

## 结论：✅ 通过（verified）

**状态：verified — 10/10 场景通过，0 失败，0 错误（全部场景通过）**

全绿快道: 10/10 场景通过、0 失败 0 警告——无分类对象，跳过 judge 机械 verified

| 指标 | 数量 |
| --- | --- |
| 通过 | 10 |
| 失败 | 0 |
| 错误 | 0 |
| 产品 Bug | 0 |
| 本链增量 Token（输入） | 2.62M |
| 本链增量 Token（输出） | 0.05M |


## 场景结果

| 场景 | 描述 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- | --- |
| noise-constant-unified-entry-semantics | 正向路径·CLI stderr 噪声常量收口与统一判别（spec AC1①「任一消费端用同一 pattern 常量判定」）：CLI_STDERR_NOISE_TEXT_PATTERNS 为非空元组（按具体 pattern 枚举 [claude-code:*] 启动期诊断行）；is_cli_stderr_noise 对 [claude-code:unrecognized_model] 行首结构化形态命中，对真实诊断行/空串/裸子串 error 文本（Model unrecognized_model rejected…）/行中前缀均不命中（^ 行首锚定、窄枚举，不得吞掉瞬断通道依赖的裸前缀信号）；既有 UNRECOGNIZED_MODEL_TEXT_PATTERNS 裸子串二元组原样保留；消费端 knowledge_backfill._failure_attribution_tail 与 self_review._scan_run_midflight 源码均引用同一判别入口 is_cli_stderr_noise（经进程内装配探针验证）。出处：core/agent_runner/provider_circuit.py:80-98,157-169；core/knowledge_backfill.py:401-419；core/self_review.py:854-913。 | pass | 0/11 | - |
| transient-classification-invariants-unchanged | 回归守卫·provider_circuit 瞬态分类行为不变（spec AC1②「unrecognized_model 不算瞬态保持不变」+ design 非目标「:405-479 分类判据与瞬断判定一行不动」）：classify_unrecognized_model_error 对结构化噪声行与裸文本形态均仍命中（UNRECOGNIZED_MODEL_TEXT_PATTERNS 仍是判据源）、对 429 文本不误判；classify_transient_error 前置豁免（exit=0+有 result → 非瞬断，即使 stderr 含噪声行）与通道 2（exit≠0+无 result+[claude-code: 前缀 → 瞬断）均保持——新常量未被反向喂给瞬态分类、未过滤瞬断判定入参；429 仍走 classify_ratelimit_error 限流分类。经静态方法直接探针验证。出处：core/agent_runner/provider_circuit.py:406-472,474-514；core/agent_runner/runner.py:3066-3067。 | pass | 0/7 | - |
| midflight-first-stderr-skips-noise-keeps-count | 正向路径·深扫 first_stderr 降噪（spec AC2「噪声不占位」）：进程内装配 run 事件流 jsonl（首条 stderr 为 [claude-code:unrecognized_model] 噪声行、后续存在真实诊断行 real diagnostic: ECONNRESET），_scan_run_midflight 的 first_stderr 取首条非噪声行，stderr_count 仍保留全量计数（噪声行也计）。出处：core/self_review.py:899-914；tests/test_self_review_midflight.py:269-285。 | pass | 0/5 | - |
| midflight-all-noise-first-stderr-blank | 空状态·stderr 全为噪声行时 first_stderr 置空（spec AC3「全噪声置空」）：进程内装配两条 [claude-code:unrecognized_model] 噪声行（glm / deepseek 两模型形态）的事件流，深扫结果first_stderr 为 null（不回填噪声行），stderr_count 仍统计全部行。出处：core/self_review.py:905-913；tests/test_self_review_midflight.py:287-299。 | pass | 0/5 | - |
| midflight-boundary-malformed-special-inputs | 异常路径·深扫边界输入（空输入/超长输入/坏行/特殊字符/文件缺失）：超长 stderr 行（500 字符）摘要截断到 140 字符上限；坏 JSON 行与非 dict 行跳过不阻断（其后合法 stderr 行正常入选、计数不含坏行）；中文+引号+尖括号特殊字符行原样保留、噪声行照常跳过；空文件与文件不存在均返回零值扫描（stderr_count=0、first_stderr 为 null、不抛异常）。出处：core/self_review.py:840-852,862-871,898-901,932-934。 | pass | 0/8 | - |
| self-review-midflight-regression-suite | 回归点·self_review 深扫交付测试套件全绿（tasks 3.1）：TestScanRunMidflight 8 条用例通过，关键降噪用例 test_first_stderr_skips_cli_noise_line / test_all_noise_stderr_left_blank 与既有真实流形态回归用例 test_stall_and_stderr_collected_real_stream_json_shape 均 PASSED（用例名照抄实测 -v 输出，仅 -v 不带 -q 以保 PASSED 行可见）。出处：tests/test_self_review_midflight.py:255-356；pytest.ini 全局配置。 | pass | 0/5 | - |
| attribution-tail-filter-and-fallback | 正向路径·失败归因文本降噪（spec AC4「真实死因不被淹没」）：_failure_attribution_tail 对「噪声行+真实死因」混合 stderr 先逐行过滤再取尾部——归因含 API Error: Request rejected (429) 与Traceback 行、不含 unrecognized_model；stderr 全噪声时回退 stdout 尾部（stdout 不过滤，loading… 前缀保留）；全噪声且 stdout 为空、两者皆空、None 入参均返回空串（归因仅保留调用方拼装的退出码前缀）。出处：core/knowledge_backfill.py:401-419；tests/test_knowledge_backfill.py:742-766。 | pass | 0/10 | - |
| attribution-spawn-e2e-noise-free-evidence-kept | 交互流程·spawn 失败归因端到端（多步：起 spawn → 落盘留证 → 文件断言）：default_spawn 子进程（桩化）exit 1、stderr 全噪声、stdout 含 429 真实死因时，抛出的 RuntimeError 归因消息含退出码前缀「退出码 1」与 stdout 中的 429 死因、不含噪声行；同时 .out 留档完整保留原始 stderr 噪声行（design D3 非目标「留证不过滤」——降噪只作用于归因消息）。中间落盘文件经 file_exists/file_content 断言。出处：core/knowledge_backfill.py:421-452；tests/test_knowledge_backfill.py:767-800。 | pass | 0/9 | - |
| knowledge-backfill-attribution-regression-suite | 回归点·knowledge_backfill 归因交付测试套件全绿（tasks 3.2）：-k attribution 选中 4 条用例通过——单元级 test_failure_attribution_tail_filters_noise_lines / test_failure_attribution_tail_falls_back_to_stdout_tail 与端到端 test_spawn_failure_attribution_uses_filtered_tail / test_spawn_failure_attribution_falls_back_to_stdout 均 PASSED（用例名照抄实测 -v 输出，无 parametrize 后缀；仅 -v 不带 -q）。出处：tests/test_knowledge_backfill.py:742-800。 | pass | 0/6 | - |
| both-deliverable-test-files-full-regression | 整卷回归·两交付测试文件合跑全绿（tasks 3.1+3.2 无回归）：tests/test_self_review_midflight.py 与 tests/test_knowledge_backfill.py 合计 45 条用例全部通过（-p no:warnings 抑制仓内既有 DeprecationWarning 刷屏以防 64KB stdout 证据截断吃掉尾部 summary；单用例 10s 硬门由 pytest.ini 全局生效）。出处：tests/test_self_review_midflight.py；tests/test_knowledge_backfill.py；pytest.ini。 | pass | 0/4 | - |

## 本轮场景集变更

当前稳定场景集共 10 个（第 1 轮）。

- 首轮写入 10 个场景

