# 验证报告：evo-add-evolution-contract-partial-accept

> ⚠️ 本报告由框架于 2026-10-06T18:48:38Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。
> 报告时效标记（判定本报告是否属上一轮）：合成源轮次指纹：report.json@2026-10-06T18:48:37.559199+00:00+run-result@mtime1791312517592806814

## 结论：✅ 通过（verified）

**状态：verified — 9/9 场景通过，0 失败，0 错误（全部场景通过）**

全绿快道: 9/9 场景通过、0 失败 0 警告——无分类对象，跳过 judge 机械 verified

| 指标 | 数量 |
| --- | --- |
| 通过 | 9 |
| 失败 | 0 |
| 错误 | 0 |
| 产品 Bug | 0 |
| 本链增量 Token（输入） | 3.42M |
| 本链增量 Token（输出） | 0.03M |


## 场景结果

| 场景 | 描述 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- | --- |
| read-contract-lenient-mixed-partial-accept | 宽口径校验：混合产物 9 条（items[4] section=「流程」越界三值枚举）经 read_contract(lenient=True) 返回 8 条合法条目与 1 条 errors 记录（index=4、文案含「三值枚举」），不抛整份拒绝，run_id 透传保留（spec evolution-product-contract「混合产物部分接受」；出处 core/evolution.py:2159-2256 lenient 分支） | pass | 0/7 | - |
| read-contract-all-invalid-still-rejected | 宽口径不放大到全非法：产物 3 条全部契约非法（section 越界 / verdict=None / 缺 title）时 read_contract(lenient=True) 仍抛 ContractError，文案含「全部 3 条条目契约非法」「整份拒绝」并附首条错误（D3 fail-closed；出处 core/evolution.py:2243-2249） | pass | 0/5 | - |
| read-contract-default-strict-behavior-unchanged | 回归点：同一混合产物（2 条含 1 条 section 越界）默认调用（不传 lenient）仍整份拒绝抛 ContractError（文案含 items[1] 与「三值枚举」），而 lenient=True 对同一文件返回 1 条合法条目——新参数不改变既有调用方行为（tasks 2.2 默认调用行为不变；出处 core/evolution.py:2237-2241 elif lenient 分支） | pass | 0/4 | - |
| read-contract-file-level-errors-lenient-not-exempt | 文件级错误不属宽口径豁免面：产物文件缺失、非 JSON、顶层非对象、缺 items 数组四种文件级缺陷在 lenient=True 下均仍抛 ContractError（宽口径只细化单条目错误，文件级归因分级保持现状；出处 core/evolution.py:2190-2207 与 core/agent_runner/maintenance_runs.py:1052-1072 except ContractError 分支） | pass | 0/5 | - |
| read-contract-lenient-per-item-error-kinds | 逐条错误收集形态：4 条产物中 3 条分别缺 verdict、缺 title、id 非字符串，lenient=True 返回仅 1 条合法条目、errors 索引 [1,2,3] 与三类错误一一对应（errors=[{index,message}] 契约形态；出处 core/evolution.py:2209-2241 _validate_item 单条校验） | pass | 0/6 | - |
| run-evolution-partial-accept-ingest-archive | 落库侧部分接受：run_evolution 消费 3 条混合产物（1 条 section 越界）——合法 2 条落库 items.jsonl（title 甲/乙）、run success=False、error 含「部分接受」「items[1]」「三值枚举」「水位不推进」，产物文件改名 .failed 留档且含全部 3 条、原路径已清理，watermarks 文件字节不变（spec「校验拒绝后合法条目落库」+ design D4 留档；出处 core/agent_runner/maintenance_runs.py:1051 lenient 接入、:1133-1142 留档路径入 error、:1220-1236 _archive_failed_evolution_out）。环境依赖：无（stub _run_claude，不触真实 CLI） | pass | 0/12 | - |
| run-evolution-partial-accept-no-pending-still-partial | 部分接受与待分析条目数无关：pending_entries=None（expected 未知）时 2 条混合产物（1 条越界）仍按「有逐条契约错误即 partial」处理——合法 1 条落库、success=False、error 含「部分接受」「水位不推进」、.failed 留档含 2 条、watermarks 不变（出处 core/agent_runner/maintenance_runs.py:1078-1083 partial 判定 bool(item_errors) 短路分支）。环境依赖：无（stub _run_claude） | pass | 0/9 | - |
| run-evolution-all-invalid-fail-closed-no-archive | run 级全非法仍 fail-closed 且不扩大留档面：run_evolution 消费 2 条全非法产物 → success=False、items_ingested=0、error 含「全部 2 条条目契约非法」「整份拒绝」、无 .failed 留档、无 items.jsonl、原产物按既有清理删除、watermarks 不变（design D3/D4「不扩大留档面」；出处 core/agent_runner/maintenance_runs.py:1052-1072 except 分支与 :1177-1186 finally 清理）。环境依赖：无（stub _run_claude） | pass | 0/9 | - |
| repo-tests-partial-accept-regression | 回归点：仓库自身测试套件对本次交付的两个用例类全量通过——tests/test_evolution_product_salvage.py::TestPartialAcceptContract（部分接受/全拒绝/留档，tasks 2.1）与 tests/test_self_evolution.py::TestEvolutionReadContract（read_contract 宽口径返回形态，tasks 2.2），-v 逐用例 PASSED 且汇总 11 passed（出处 tests/test_evolution_product_salvage.py:275、tests/test_self_evolution.py:735；实测输出行照抄，无 parametrize 后缀）。环境依赖：无 | pass | 0/8 | - |
