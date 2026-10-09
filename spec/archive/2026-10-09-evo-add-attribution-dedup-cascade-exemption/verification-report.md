# 验证报告：evo-add-attribution-dedup-cascade-exemption

> ⚠️ 本报告由框架于 2026-10-03T20:49:26Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。
> 报告时效标记（判定本报告是否属上一轮）：合成源轮次指纹：report.json@2026-10-03T20:49:25.978180+00:00+run-result@mtime1791060566011179708

## 结论：✅ 通过（verified）

**状态：verified — 8/8 场景通过，0 失败，0 错误（全部场景通过）**

全绿快道: 8/8 场景通过、0 失败 0 警告——无分类对象，跳过 judge 机械 verified

| 指标 | 数量 |
| --- | --- |
| 通过 | 8 |
| 失败 | 0 |
| 错误 | 0 |
| 产品 Bug | 0 |
| 本链增量 Token（输入） | 2.66M |
| 本链增量 Token（输出） | 0.04M |


## 场景结果

| 场景 | 描述 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- | --- |
| cascade-pure-group-not-rejected | 纯依赖级联同因组豁免（正向核心）：5 个引擎合成 dependency_skipped 同文场景（宿主缺 Gradle 形态，条目形状取自 core/verify_engine/engine.py:409-426）经 merge_engine_cascade_markers 透传后，场景级与整批级查重均不判拒、无 violations、豁免场景全部置 accept 不进回炉清单、counts 记账正确。出处 core/verdict_check.py:1380-1448（级联豁免分支与 accept 合并） | pass | 0/13 | - |
| cascade-exemption-trail-gate-log | 豁免决策留痕（Requirement 2）：查重返回结构 exemptions 段含精确 reason「同因级联组豁免（N 场景，dependency_skipped）」与场景清单（整批+场景级两入口）；统一入口 _run_attribution_gate 命中豁免时记 info 日志「批量归因查重豁免…同因级联组豁免…场景 s1, s2, s3」可事后审计；豁免=violations 空列表（不触发拒绝收口链 _rejection_closure 的结构前提）；透传落点=合并后场景条目携带 gate-owned 键 _engine_dependency_skipped。出处 core/verdict_check.py:1255/1424-1437、core/pm_engine/verification/verdict_evidence.py:89-101 | pass | 0/13 | - |
| cascade-mixed-group-still-rejected | 混合组判拒语义不变（防模板套用能力回退）：同文组含 3 个真实 failed 场景（非依赖跳过）+ 2 个级联场景时仅对非级联子集计阈值——3 个真实 failed 同文照拒，违规 reason 维持既有文案（「归因文本完全相同」「疑似批量套用硬编码归因」），场景级回炉清单只含真实 failed 子集，级联子集豁免与判拒并存单独留痕。出处 core/verdict_check.py:1406-1422（违规 reason 拼接）、1446-1448（豁免场景并入 accept） | pass | 0/10 | - |
| cascade-judge-self-declared-not-trusted | 伪标不豁免（防实现 run 伪标逃逸，多步序列）：judge 报告自申报 dependency_skipped=True 但无引擎三要素签名（status=fail 矛盾）不豁免照拒；伪造 gate-owned 键 _engine_dependency_skipped=True 被透传全量重算物理清除——第一步 merge 后把 report 落盘为中间态文件，第二步从盘载入复核伪造键已被清除（forged_key_present_count=0）且复跑 merge 幂等、复判仍拒；与引擎跳过文案逐字相同但无结构化标记的同文照拒且 exemptions 空；is_engine_cascade_scenario 三要素签名矩阵（缺标记/空 deps/缺 deps/status 矛盾/deps 非列表均不成立）。出处 core/verdict_check.py:1260-1306 | pass | 0/17 | - |
| cascade-boundary-pass-exclusion-nonregression | 边界阈值与既有语义回归：2 个真实 failed 同文（<3 阈值）不拒；pass 场景排除逻辑不变（不进 accept 参与计数、级联子集照常豁免留痕）；「步骤/断言各异」D3 归一化拆分豁免行为不回退（4 个各异步骤/断言的真实 failed 放行）；无归因文本场景不参与查重且场景级视为保留（不进回炉）。出处 core/verdict_check.py:1391-1401（pass 排除与归一化分组）、1449-1458（无归因文本保留） | pass | 0/13 | - |
| cascade-degenerate-inputs-shape-stable | 退化输入形状稳定（异常路径）：report=None、空 dict、scenarios 非列表、scenarios 含非 dict 元素四形态下，透传与两级查重均不抛异常，返回形状与 docstring 承诺一致（ok=True、violations/exemptions 空列表、场景级 requeue_ids/accept_ids/counts 键齐备全零），调用方按下标访问不 KeyError。出处 core/verdict_check.py:1361-1377（退化输入早退分支） | pass | 0/13 | - |
| cascade-delivered-test-file-all-green | 交付测试文件全绿（tasks 2.1）：tests/test_attribution_dedup_cascade_exempt.py 20 用例全过（纯级联豁免/混合组仍拒/伪标防御/门级透传与日志/D3 不回退五组，用例名与数量经本地实测 20 passed 照抄，无 parametrize 后缀）。出处 tests/test_attribution_dedup_cascade_exempt.py:75-423（交付物清单第 3 项） | pass | 0/7 | - |
| cascade-existing-dedup-regression-green | 既有查重回归不回退（tasks 2.2）：tests/test_verdict_credibility_gate.py 的 TestDedupNormalizationCascadeExemption / TestBatchAttributionDedup 按「纯级联组豁免、混合组保持拒绝」新语义更新后 15 用例全绿（用例名与数量经本地实测 15 passed 照抄，-k 按类名筛选）。出处 tests/test_verdict_credibility_gate.py:291-530 | pass | 0/7 | - |
