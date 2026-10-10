# 验证报告：evo-fix-self-review-phantom-running

> ⚠️ 本报告由框架于 2026-10-10T17:59:45Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。
> 报告时效标记（判定本报告是否属上一轮）：合成源轮次指纹：report.json@2026-10-10T17:59:45.155060+00:00+run-result@mtime1791655185197001869

## 结论：✅ 通过（verified）

**状态：verified — 12/12 场景通过，0 失败，0 错误（全部场景通过）**

全绿快道: 12/12 场景通过、0 失败 0 警告——无分类对象，跳过 judge 机械 verified

| 指标 | 数量 |
| --- | --- |
| 通过 | 12 |
| 失败 | 0 |
| 错误 | 0 |
| 产品 Bug | 0 |
| 本链增量 Token（输入） | 4.55M |
| 本链增量 Token（输出） | 0.04M |


## 场景结果

| 场景 | 描述 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- | --- |
| classify-superseded-tail-not-running | 弃置终态不计为在跑：原地重试弃置件（末两行 transient_retry+superseded，2026-10-09T19:01Z 实拍形态）经 _classify_run 判 category=superseded（detail 沿用 type 原词）；8 幻影同构小样本（4×-a1+4×-a1-r1）+1 个 result 成功对照经 collect_runs_stats 统计：superseded=8、running=0、succeeded=1，弃置件不再混入在跑口径。出处 core/self_review.py:461-472、core/dashboard/data/runs.py:326（RUN_TERMINAL_STATUS_MAP）。 | pass | 0/10 | - |
| classify-ended-terminals-not-running | 其他终结终态不计为在跑：interrupted/cancelled/frozen-terminated/gate-blocked 四类末行经 _classify_run 判 category=ended 且 detail 含原 type 词；取消路径产物（末行 type=cancelled，runner.py:6557 最后落盘）计 ended=1、running=0、failed=0，且不进入 collect_failed_run_samples 失败样本。出处 core/self_review.py:467-471、core/self_review.py:671-676（样本口径注释锁定）。 | pass | 0/8 | - |
| classify-vocabulary-single-source-evolution | 终态词表单源：_terminal_status_types() 返回集合与 core.dashboard.data.runs.RUN_TERMINAL_STATUS_MAP 键集全等（非复制定义）；向映射注入新终态词 future-x 后 _classify_run 即判 ended——词表演进单点生效、本侧无需改动；liveness.RUN_TERMINAL_EVENT_TYPES 故意排除 superseded 而本侧仍判 superseded（两套词表差异不被统一口径抹平，未消费 liveness 集）；词表外未知 type 维持 running。出处 core/self_review.py:390-406、core/dashboard/data/runs.py:326、core/agent_runner/liveness.py:132。 | pass | 0/8 | - |
| stale-reconciliation-orphan-render | 陈旧断尾产物单列为 stale：产物末行非任何已知终态、mtime 停更超 RUN_STALE_SECONDS（1800s，os.utime 注入不 sleep）、fenixd.log run_metrics 无该 run 终态（指标索引查无）→ _reconcile_running_run 改计 stale，running=0；日报第 2 节渲染为「无终态残留: 1」且「在跑/无终态: 0」。出处 core/self_review.py:850-879、core/self_review.py:907-912（对账下沉单点）、core/dashboard/data/runs.py:327（RUN_STALE_SECONDS）、core/self_review.py:1693-1696（渲染行）。 | pass | 0/10 | - |
| stale-reconciliation-non-success-terminal-stale | 指标记非 success 终态而产物断尾按 stale 通道处理：两个末行非终态、mtime 停更超 RUN_STALE_SECONDS 的 run，run_metrics 分别记 terminal=failure 与 terminal=frozen（查得非 success 终态，_run_terminal_success 返回 False）→ 均计 stale（stale=2），MUST NOT 改计 failed（failed=0）、MUST NOT 按成功提升计 succeeded（succeeded=0），且不进入失败样本（口径不与计数分叉）。出处 core/self_review.py:856-879、runner.py terminal 值域写入点 :3660/:4649/:4691/:5096。 | pass | 0/7 | - |
| stale-reconciliation-terminal-success-promote | 指标有终态而产物断尾按终态计：产物末行非终态（daemon 崩溃截断收尾形态）、mtime 停更超 RUN_STALE_SECONDS，但 run_metrics 记录 terminal=success → 该 run 计 succeeded（含 attempt 后缀对齐的指标查询），不混入在跑（running=0）也不落 stale（stale=0）。出处 core/self_review.py:877-878、core/self_review.py:504-539（_run_terminal_success）。 | pass | 0/6 | - |
| stale-reconciliation-fresh-stays-running | 新鲜无终态维持在跑判定（宁可不拦不可误伤）：三个末行非终态 run——刚写入（age≈0）、阈值内侧（age=RUN_STALE_SECONDS-30）、阈值外侧（age=RUN_STALE_SECONDS+60）——前两者维持 running 不改判，仅阈值外侧计 stale；running=2、stale=1。出处 core/self_review.py:871-876（age<=阈值维持 running）、core/dashboard/data/runs.py:327。 | pass | 0/6 | - |
| mixed-window-counts-no-keyerror | counts 桶位补键与混合窗口计数：result/superseded/ended/running 四类产物并存时 collect_runs_stats 计数各归其位（total=4、succeeded=1、superseded=1、ended=1、running=1、stale=0、failed=0），counts 初始 dict 含 superseded/ended/stale 三新键——缺键即 counts[category] += 1 KeyError（本条最大回归点）；失败样本列表不含新桶与 running 类 run。出处 core/self_review.py:591-627（counts 初始 dict 与 docstring 桶位清单）、core/self_review.py:671-709（样本口径）。 | pass | 0/13 | - |
| daily-summary-section2-render-phantom-cohort | 日报第 2 节口径透明：12 run 夹具（8 幻影同构 -a1/-a1-r1 superseded + result/cancelled/陈旧断尾/新鲜在跑各一）经 collect_daily_summary 渲染，三新行「弃置/重试件: 8」「其他终态: 1」「无终态残留: 1」存在且插于「丢弃/空」与「在跑/无终态」之间（design D5 增量加行不改既有行文案）；「在跑/无终态: 1」不含 superseded（2026-10-11 日报 8 幻影同构回归：在跑 8→0）；各行计数之和等于总 run 数（聚合无异常无漏计）。出处 core/self_review.py:1676-1696。 | pass | 0/14 | - |
| targeted-test-files-full-regression | 回归点：本 SPEC 两个交付测试文件全量 pytest 通过（46 例，含既有 result/error/marker/timeout/instant_hang/空文件语义不回归 + 新词表/混合夹具/stale 四态/第 2 节渲染全部用例），exit_code=0。output_match 断言文案照抄实测 -v 输出行；命令只带 -v 不带 -q（-q 会吞 PASSED 行致断言恒失败）。出处 tests/test_self_review_result_based_classification.py、tests/test_self_review_terminal_crosscheck.py。 | pass | 0/13 | - |
| legacy-failure-semantics-byte-stable | 异常路径与既有语义回归：_classify_run 的 result/error 分支业务失败语义逐字节不动——result 无标记→succeeded、result 声明窗口内命中业务失败标记→failed(detail=marker=词)、终态邻近独立事件行失败信号→failed(detail=signal=词)、error 超时签名→timeout、error 秒挂签名（unrecognized_model）→instant_hang、error 普通文本→failed(detail=原文)；空文件/无事件→dropped、尾行非 dict 畸形行→running。出处 core/self_review.py:433-478、core/self_review.py:128-131（_INSTANT_FAIL_PATTERNS）、core/self_review.py:134+（_BUSINESS_FAIL_PATTERNS）。 | pass | 0/13 | - |
| vocabulary-import-failure-fallback | 异常路径：终态词表读取失败时分类退回原行为、不因词表导入失败制造改判——毒化 core.dashboard.data.runs 模块缓存使延迟导入抛 ImportError 后，_terminal_status_types() 返回空集，superseded 末行退回 (running, no-terminal)（与既有 running 分支逐字节一致），result/error 分支不依赖词表、语义不受影响。出处 core/self_review.py:398-406（导入失败返回空集的约定 docstring）。 | pass | 0/6 | - |
