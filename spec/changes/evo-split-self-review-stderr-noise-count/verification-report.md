# 验证报告：evo-split-self-review-stderr-noise-count

> ⚠️ 本报告由框架于 2026-10-02T21:20:05Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。
> 报告时效标记（判定本报告是否属上一轮）：合成源轮次指纹：report.json@2026-10-02T21:20:04.868223+00:00+run-result@mtime1790976004898541642

## 结论：✅ 通过（verified）

**状态：verified — 12/12 场景通过，0 失败，0 错误（全部场景通过）**

全绿快道: 12/12 场景通过、0 失败 0 警告——无分类对象，跳过 judge 机械 verified

| 指标 | 数量 |
| --- | --- |
| 通过 | 12 |
| 失败 | 0 |
| 错误 | 0 |
| 产品 Bug | 0 |
| 本链增量 Token（输入） | 3.08M |
| 本链增量 Token（输出） | 0.03M |


## 场景结果

| 场景 | 描述 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- | --- |
| scan-mixed-stderr-count-split | 深扫混合行计数分离：run 事件流 stderr 依次为 1 条 [claude-code:unrecognized_model] 噪声行 + 1 条真实诊断行，_scan_run_midflight 产出 stderr_count==1、stderr_noise_count==1，first_stderr 取真实诊断行（既有语义不变）。出处 core/self_review.py:915-925（实现）、spec/changes/evo-split-self-review-stderr-noise-count/specs/self-review-midflight-signals/spec.md「混合行计数分离」 | pass | 0/5 | - |
| scan-all-noise-count-zero | 深扫全噪声计数归零：run 事件流 stderr 全为 3 条噪声行，stderr_count==0、stderr_noise_count==3，first_stderr 置空（既有「全噪声置空」语义不变）。出处 core/self_review.py:915-925、spec「全噪声计数归零」 | pass | 0/4 | - |
| scan-order-and-edge-lines | 深扫顺序与边界行鲁棒：真实诊断行在前、含中文/引号/转义特殊字符的噪声行居中、缺 line 键的 stderr 事件收尾——first_stderr 取首条真实行，缺 line 键事件按非噪声计入 stderr_count（合计 2），特殊字符噪声行仍被行首锚定判别计入噪声。出处 core/self_review.py:916-917（isinstance 判别）、provider_circuit.py:101-103（pattern 行首锚定） | pass | 0/5 | - |
| scan-unreadable-file-zero-scan | 深扫文件不可读零值扫描：目标 jsonl 不存在时 _scan_run_midflight 返回零值 dict 且含 stderr_noise_count==0，不抛异常。出处 core/self_review.py:864-941（OSError 分支）、design.md「文件不可读时返回零值扫描结果」 | pass | 0/5 | - |
| scan-raw-jsonl-preserved | run 产物 jsonl 原始事件不过滤：含噪声行的 jsonl 经 _scan_run_midflight 扫描后，文件字节级保持不变（取证现场完整，MUST NOT 过滤落盘），两条 stderr 原始事件仍在。出处 spec「run 产物 jsonl 的 stderr 原始事件 SHALL 保持不过滤」、design.md D4 | pass | 0/3 | - |
| render-noise-only-annotation | 渲染定噪不再冒充信号：构造 turns=90 离群 run（stderr 仅 1 条已知启动噪声），每日摘要第六节深扫行呈现「中途stderr=0（另 1 条已知 CLI 启动噪声）」，全文不出现「中途stderr=1」，噪声存在性仍可见（stderr=0 仍落段）。出处 core/self_review.py:1477-1495（_collect_midflight_section）、spec「定噪不再冒充信号」 | pass | 0/5 | - |
| render-mixed-annotation | 渲染混合行注记：离群 run stderr 为 1 噪声 + 1 真实行，深扫行呈现「中途stderr=1（另 1 条已知 CLI 启动噪声）」，主计数取非噪声口径（全文不出现「中途stderr=2」）。出处 core/self_review.py:1477-1495、spec Requirement 深扫行渲染注记 | pass | 0/4 | - |
| render-real-only-plain-shape | 渲染无噪声行形态不变：离群 run stderr 仅为 1 条真实诊断行，深扫行「中途stderr=1」且全文不含噪声注记（与既有行为一致）。出处 core/self_review.py:1490-1491（else 分支）、spec「无噪声行形态不变」 | pass | 0/3 | - |
| render-legacy-dict-no-annotation | 渲染旧 scan dict 兼容：mock _collect_midflight_scans 返回缺 stderr_noise_count 键的旧形态 dict（stderr_count==2），深扫行仍「中途stderr=2」且不产生注记（缺省/0 不注记，行形态同现状）。出处 core/self_review.py:1484-1491（has_noise isinstance 门控）、design.md「缺省或为 0（旧 scan dict 兼容）不产生注记」 | pass | 0/3 | - |
| discriminator-single-source | 判别单源复用：core/self_review.py 源码引用 is_cli_stderr_noise 且未复制 pattern 常量（MUST NOT 复制）；is_cli_stderr_noise 对规范噪声行判真、真实诊断行与空串判假。出处 provider_circuit.py:101-103/227-239（单源收口）、spec Requirement 判别单源与分类零扰动 | pass | 0/6 | - |
| provider-circuit-zero-regression | 分类行为零回归：CLI_STDERR_NOISE_TEXT_PATTERNS 仍为单条行首锚定 pattern；classify_unrecognized_model_error 对噪声行判真/真实行判假；classify_transient_error 对 exit=1+无 result+噪声 stderr 判瞬断、exit=0+有 result 判非瞬断（读原始 stderr 信号，与变更前一致）。出处 provider_circuit.py:518-535/557+、spec「分类行为零回归」 | pass | 0/8 | - |
| pytest-midflight-suite-regression | 交付物测试口径全量回归：pytest tests/test_self_review_midflight.py 全套 25 用例通过，含口径更新用例（first_stderr 跳噪声/全噪声置空）与新增渲染注记用例（定噪不再冒充信号/无噪声对照）。出处 tests/test_self_review_midflight.py:263-303/560-602 | pass | 0/6 | - |
