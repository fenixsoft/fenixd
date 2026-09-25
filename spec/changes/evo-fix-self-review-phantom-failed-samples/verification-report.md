# 验证报告：evo-fix-self-review-phantom-failed-samples

> ⚠️ 本报告由框架于 2026-09-25T01:01:36Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。
> 报告时效标记（判定本报告是否属上一轮）：合成源轮次指纹：report.json@2026-09-25T01:01:36.659217+00:00

## 结论：✅ 通过（verified）

**状态：verified — 8/8 场景通过，0 失败，0 错误（全部场景通过）**

全绿快道: 8/8 场景通过、0 失败 0 警告——无分类对象，跳过 judge 机械 verified

| 指标 | 数量 |
| --- | --- |
| 通过 | 8 |
| 失败 | 0 |
| 错误 | 0 |
| 产品 Bug | 0 |
| 本链增量 Token（输入） | 5.93M |
| 本链增量 Token（输出） | 0.10M |


## 场景结果

| 场景 | 描述 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- | --- |
| phantom-echo-replay-succeeded | 信号护栏主验证（spec phantom-failed-sample-guard R1 场景1）：复刻 proposal 实测幻影 run 形态——尾三行 [assistant 收工叙事回声, run_metrics, result]，业务失败词「预算耗尽」同现于回声行与 result 正文中段（前 100 字符声明区干净），daemon 侧 terminal=success；_classify_run 应剥除回声行判 succeeded（detail 空），collect_runs_stats failed=0/succeeded=1/total=1，collect_failed_run_samples 无样本（出处 core/self_review.py:278 终态邻近窗口、:281 _strip_terminal_echo_lines、:325/:363 _classify_run 信号护栏、:137/:242 marker 声明窗口；core/agent_runner/runner.py:3340 正常收尾记 terminal=success；core/dashboard/data/runs.py:141 load_run_metric 公共访问器） | pass | 0/8 | - |
| independent-signal-evidence-kept | 终态之外的独立失败证据仍可检出（spec R1 场景2）+ 索引缺失不改判之无日志目录变体（spec R2 场景3）：两份夹具的失败信号词（spec_content_missing / budget exhausted）分别位于尾三行视图内的非 assistant 非 result 事件行（夹具A尾三行=[信号system行, step, result]；夹具B尾三行=[assistant, 信号system行, result]，回声行被剥后信号行仍可命中），两例均判 failed 且 detail 以 signal= 开头、入失败样本、failed=2；项目根无 .fenix/logs（metric 索引整体缺失）时维持计入不改判（出处 core/self_review.py:258 _signal_evidence、:363 护栏视图=尾3行、:140 信号词表、:518/:583 守卫仅对 signal= 查 terminal、:400 _run_terminal_success 索引缺失返回 None；夹具形态对齐更新后单测 tests/test_self_review_run_semantics.py impl-sig-999） | pass | 0/10 | - |
| marker-hit-kept-with-success-terminal | marker 命中（D1 假成功抓取）不受交叉守卫影响（spec R2 场景2）：result 开头即失败声明「预算已耗尽，无法继续实现剩余任务」（前 100 字符声明区命中 marker 词表），daemon 侧 terminal=success（正常 result 收尾即记 success，与 result 文本无关）；样本仍计入失败统计与失败样本、detail 以 marker= 开头，且不产生 self_review_phantom_failure 告警（出处 core/self_review.py:121-129 marker 词表、:242 _business_fail_marker、:583 守卫仅限 signal= 前缀；core/agent_runner/runner.py:3340；core/admin_store.py:62 AdminStore 注入、:324 read_all） | pass | 0/7 | - |
| signal-phantom-excluded-and-alerted | 双源交叉守卫正向路径（spec R2 场景1）：样本因信号路径命中分类 failed（detail 前缀 signal=，信号词 budget-exhausted 位于尾三行内 system 事件行）而 run_metrics terminal=success——不计入失败数（stats failed=0、succeeded=1、样本列表空），admin_alerts 恰产出 1 条 self_review_phantom_failure 告警：severity=warning、kind=escalation、未自动 mark_handled、evidence 含 run_id 与 terminal=success（出处 core/self_review.py:518-520 collect_runs_stats 守卫、:583-587 collect_failed_run_samples 守卫+告警、:425 _record_phantom_failure_alert；core/admin_store.py:28 ESCALATION） | pass | 0/13 | - |
| metric-missing-keeps-failed | 索引缺失不改判（spec R2 场景3）：.fenix/logs/fenixd.log 与 .fenixd.log.1 均在场但只含无关 run 的指标，信号路径 failed 样本（信号词「预算耗尽」位于尾三行内 system 事件行、result 干净）查不到自身终态——维持现状计入失败（stats failed=1、样本 detail 以 signal= 开头），不产生 phantom 告警、不因缺数据改判（出处 core/self_review.py:400-409 _run_terminal_success 索引缺失返回 None、:583 守卫仅 terminal=success 才排除；core/dashboard/data/runs.py:141 load_run_metric 双索引未命中返回 None） | pass | 0/7 | - |
| rotated-log-fallback-guard | 轮转回退与 attempt 后缀对齐（2.1 公共访问器）：终态指标只写入轮转日志 .fenixd.log.1、主日志仅含无关指标——load_run_metric 对 -a1 产物 stem 命中轮转索引返回 terminal=success，对 -a1-r1 复合后缀 stem 同样命中，对无记录 stem 返回 None；聚合侧同一夹具（信号词 impl_budget_exhausted 于尾三行 system 行，stem 带 -a1）经轮转源查到 terminal=success → 幻影排除（failed=0、无样本）并产出 1 条 self_review_phantom_failure 告警（出处 core/dashboard/data/runs.py:141 load_run_metric、:113 _load_rotated_run_metric_index、:28 _strip_run_attempt_suffix；core/self_review.py:583 守卫） | pass | 0/9 | - |
| store-absent-phantom-excluded-no-alert | store 未注入时守卫仍排除幻影、仅降级 logger.warning（2.2 降级语义）：信号路径 failed（budget-exhausted 于尾三行 system 行）+ terminal=success，collect_failed_run_samples 不传 store——失败统计与样本仍被排除（stats failed=0、total=1、样本空），.fenix/admin_alerts.json 不落盘（出处 core/self_review.py:526 collect_failed_run_samples store=None 可选注入、:425 _record_phantom_failure_alert store 缺席降级 logger.warning、:460） | pass | 0/6 | - |
| delivered-tests-regression | 交付物单测回归：-q 实跑本 SPEC 交付的三个测试文件（新 tests/test_self_review_terminal_crosscheck.py 11 例 + 更新 tests/test_self_review_run_semantics.py 与 tests/test_self_review_result_based_classification.py 32 例）应全绿（实测汇总行「43 passed」），锁定信号护栏翻转后的语义与交叉守卫（出处 tasks 1.3/3.1/3.2、tests/test_self_review_terminal_crosscheck.py:160 幻影形态用例；本机实测 python3 -m pytest ... -q 输出「43 passed in 0.14s」，故 output_match 用「43 passed」子串） | pass | 0/2 | - |

## 本轮场景集变更

当前稳定场景集共 8 个（第 1 轮）。

- 首轮写入 8 个场景

