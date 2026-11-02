# 验证报告：evo-self-review-phantom-failure-dual-source-veto

> ⚠️ 本报告由框架于 2026-10-30T11:48:31Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。
> 报告时效标记（判定本报告是否属上一轮）：合成源轮次指纹：report.json@2026-10-30T11:48:30.338367+00:00+run-result@mtime1793360910419183111

## 结论：✅ 通过（verified）

**状态：verified — 11/11 场景通过，0 失败，0 错误（全部场景通过）**

全绿快道: 11/11 场景通过、0 失败 0 警告——无分类对象，跳过 judge 机械 verified

| 指标 | 数量 |
| --- | --- |
| 通过 | 11 |
| 失败 | 0 |
| 错误 | 0 |
| 产品 Bug | 0 |
| 本链增量 Token（输入） | 0.13M |
| 本链增量 Token（输出） | 0.03M |


## 场景结果

| 场景 | 描述 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- | --- |
| contract-dual-source-veto-expansion | 契约测试组一（SPEC 3.1/3.2 新增夹具）：error 终态双源否决四用例直跑——「Exit code: 1 × daemon terminal=success → 改计 success 并写 self_review_phantom_failure 告警」「查无账面行保守保持 failed」「daemon terminal=error 反例保持 failed」「任意 error 文本不空泛匹配」。断言文案取自本树实跑输出（pytest -v 形态 PASSED 行逐字核对，未混入 -q）。出处：tests/test_self_review_terminal_crosscheck.py:377-466 （TestDualSourceVetoExpansion）；实现锚 core/self_review.py:614-642 （_is_phantom_signal_failure 三分支） | pass | 0/5 | - |
| contract-marker-veto-pin-flip | 契约测试组二（SPEC 1.2 + 3.2 pin 翻转回归）：marker= 失败词复述否决用例与混合窗口口径一致性用例（原「marker= MUST NOT 纳入守卫」pin 已按新语义同轮翻转），并回归既有 signal= 守卫（排除+告警）、attempt 后缀对齐、轮转日志回退、索引缺失保持 failed、store 缺失降级 logger.warning 共七用例。出处：tests/test_self_review_terminal_crosscheck.py:202-362 （TestTerminalCrossGuard）；实现锚 core/self_review.py:761（计数侧守卫）、:843（样本侧守卫）、:645-688（幻影告警通道） | pass | 0/8 | - |
| contract-salvage-metrics-backfill | 契约测试组三（SPEC 2.1 指标透传）：salvage/产物直读路径分源回填用例（turns←daemon 日志 context metrics 行、cost←档案 result 事件顶层 total_cost_usd；双源查无保持 0/None 并 DEBUG 留痕；正常收尾 run 不触发读盘）与 run_metrics 公共访问器用例（主日志/轮转回退/attempt 后缀对齐）。出处：tests/test_self_review_terminal_crosscheck.py:488-592 （TestSalvageMetricsBackfill）、:595-617（TestLoadRunMetricAccessor）；实现锚 core/agent_runner/maintenance_runs.py:1361-1499 | pass | 0/7 | - |
| contract-full-suite-green | 全量回归底线：契约测试文件整体直跑。命令用 -q 静默形态且不与 -v 并列（pytest 9 中 -q 覆盖 -v 会吞掉 PASSED 行致 output_match 全军覆没），断言退化为 exit_code + passed 计数。24 为本树实跑计数（2026-10-30 实测 24 passed, 6 warnings）。出处：tests/test_self_review_terminal_crosscheck.py（全文） | pass | 0/2 | - |
| probe-error-exitcode-veto-success-alert | 独立探针（第三源 evo-1792692791 形态端到端复验，防实现侧用例被削弱）：tmp 项目自建「error 终态 Exit code: 1 + daemon run_metrics terminal=success」夹具，直调 collect_runs_stats / collect_failed_run_samples——断言 failed=0/succeeded=1、失败样本空、幻影告警恰一条（signal_type=self_review_phantom_failure、severity=warning、evidence 含 run_id 与 detail=Exit code: 1）。出处：specs/self-review-aggregation/spec.md「error 终态样本双源否决 / salvage 成功被误计为失败」；core/self_review.py:614-642、:761、:843-844 | pass | 0/2 | - |
| probe-error-exitcode-missing-ledger | 独立探针（保守性/异常路径）：error 终态 Exit code 形态 + 查无 run_metrics 账面行（不写任何指标日志）→ 保持 failed 分类（failed=1/succeeded=0）、失败样本含 detail=Exit code: 1、不写幻影告警——宁可不拦不可误伤。出处：specs/self-review-aggregation/spec.md「查无账面行保守保持失败」；core/self_review.py:633-642（索引缺失返回 False 维持现状） | pass | 0/2 | - |
| probe-marker-veto-mixed-daemon-error | 独立探针（第二源失败词复述否决 + daemon=error 反例混合窗口）：marker= 命中（result 文本「预算已耗尽」在声明区 100 字符窗口命中 _business_fail_marker）× terminal=success → 改计 success 并写告警（evidence 含 marker=预算已耗尽）；同窗 marker= 命中 × daemon terminal=error → 保持 failed 入样本。断言混合窗口 failed=1/succeeded=1、样本仅含真实失败、告警恰一条。出处：specs/self-review-aggregation/spec.md「marker= 样本纳入双源否决」；core/self_review.py:360-373（_business_fail_marker）、:503-505、:614-642 | pass | 0/2 | - |
| probe-real-failure-arbitrary-error-anchor | 独立探针（真实失败不受守卫影响 + 形态锚定）：daemon terminal=error 的 Exit code 终态样本保持 failed；非 Exit code 前缀的任意 error 文本（provider 429 rate limited）即使 terminal=success 也不改判（MUST NOT 空泛匹配任意 error 文本）。断言 failed=2/succeeded=0、两样本均在列且 detail 逐字相符、零告警。出处：specs/self-review-aggregation/spec.md「真实失败不受守卫影响」；core/self_review.py:636-641（三分支形态锚定） | pass | 0/2 | - |
| probe-backfill-turns-197-targeted-parse | 独立探针（2.1 指标透传正向路径 + MUST NOT 经合并索引负对照）：daemon 日志同 run_id 双行——context metrics 行（先写，turns=197）+ lane 终态行（后写，turns=0），合并索引按同名字段后行刷新（core/dashboard/data/runs.py:107 {**prev, **ctx}）读到的 turns 恒为 0；定向解析实现必须返回 197，机械区分「读 context metrics 行」与「走 load_run_metric 合并索引」两条实现路径。档案 result 事件 total_cost_usd=6.756237（evo-1792692791 实测值）同步回填，双源命中无 DEBUG 留痕。出处：core/agent_runner/maintenance_runs.py:1361-1401（_parse_context_metrics_turns）、:1404-1456（_extract_transcript_total_cost）、:1459-1499（_backfill_salvage_run_metrics）、:1827-1830（run_evolution 消费点） | pass | 0/2 | - |
| probe-backfill-miss-degrade-normal-untouched | 独立探针（2.1 异常路径/空输入）：双源查无（空项目、无日志无转录）→ turns 保持 0、cost 保持 None、DEBUG 留痕恰两条（含 turns 与 total_cost_usd 字样）、不抛异常不阻塞落地主链；正常收尾 run（turns=12、cost_usd=0.5 已归）不触发任何读盘回填（零 DEBUG）。出处：specs/self-review-aggregation/spec.md「salvage 路径指标透传」保守条款；core/agent_runner/maintenance_runs.py:1473-1499 | pass | 0/2 | - |
| probe-daily-summary-mixed-window-veto | 独立探针（日报聚合表面端到端——proposal 背景「日报聚合把已按成功落地的 run 误计为失败」的修复目标表面）：混合窗口四夹具（marker 幻影/signal 幻影/真实失败/干净成功）经 SelfReviewScheduler.collect_daily_summary 全链聚合，断言统计节「总 run 数: 4」「成功: 3」「失败: 1」、失败样本节仅列真实失败 run_id（幻影两 run_id 不入样本行）、幻影两源各产出一条 self_review_phantom_failure 告警且 evidence run_id 集合精确。出处：core/self_review.py:1986-2096（collect_daily_summary）、:2030-2060（runs 统计与失败样本消费点） | pass | 0/2 | - |
