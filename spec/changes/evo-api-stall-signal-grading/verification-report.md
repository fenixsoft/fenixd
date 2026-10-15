# 验证报告：evo-api-stall-signal-grading

> ⚠️ 本报告由框架于 2026-10-15T06:27:00Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。
> 报告时效标记（判定本报告是否属上一轮）：合成源轮次指纹：report.json@2026-10-15T06:26:59.607553+00:00+run-result@mtime1792045619663485984

## 结论：✅ 通过（verified）

**状态：verified — 13/13 场景通过，0 失败，0 错误（全部场景通过）**

全绿快道: 13/13 场景通过、0 失败 0 警告——无分类对象，跳过 judge 机械 verified

| 指标 | 数量 |
| --- | --- |
| 通过 | 13 |
| 失败 | 0 |
| 错误 | 0 |
| 产品 Bug | 0 |
| 本链增量 Token（输入） | 0.18M |
| 本链增量 Token（输出） | 0.07M |


## 场景结果

| 场景 | 描述 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- | --- |
| stall-grading-constants-and-pure-function | 分级常量与纯函数边界：latency.STALL_ROUND_ESCALATE_SECONDS==300.0（runner 命名空间可见），三既有常量 LATENCY_STALL_SECONDS=60/STALL_ROUND_WARN_SECONDS=120/RUN_STALL_ROUND_SECONDS=120 取值不动；classify_round_stall(streak, round_seconds) 真值表：(1,301)→warning-escalated、(2,310)→warning-escalated（超限优先）、(1,300)→info（恰 300 秒不升级）、(1,150)→info、(2,121)→warning（恰连续第 2 轮）、(5,200)→warning；MIDFLIGHT_OUTLIER_DIMS 三维度与 MIDFLIGHT_SCAN_MAX_LINES=20000 不变。出处：spec R1、tasks 1.1、core/agent_runner/latency.py:23-36、core/self_review.py:774-815 | pass | 0/2 | - |
| stall-emission-info-grade-single-round | 发射点分级·info：驱动真实 _run_agent（Popen 替身产 stream-json 事件）造单轮 150.5s API 往返，恰一条 api_round_stall 记录且为 INFO 级（非 WARNING）、context.grade=='info'、latency_round==1，全 run 无 WARNING 级停滞记录；run 末汇总行（format_latency_summary 渲染）附分级计数 warning=0 info=1。出处：tasks 1.2、spec R1、core/agent_runner/runner.py:6184-6198（发射点）、:6697（汇总行） | pass | 0/2 | - |
| stall-emission-warning-grade-streak | 发射点分级·连续停滞：相邻两轮 130.5s+140.5s 均 >120 秒，第 1 条记录 INFO 级 grade='info'、第 2 条记录 WARNING 级 grade='warning'（恰连续第 2 轮触发）；run 末汇总行附分级计数 warning=1 info=1。出处：spec R1（连续 2 轮及以上停滞打 WARNING）、core/agent_runner/runner.py:6184-6198 | pass | 0/2 | - |
| stall-emission-escalated-grade-over-300 | 发射点分级·单轮超限：单轮 305.5s>300 秒，恰一条 WARNING 级 api_round_stall 记录且 grade=='warning-escalated'（无需连续停滞即升级）；run 末汇总行附分级计数 warning=1 info=0（escalated 计入 warning 桶，格式 warning=N info=M）。出处：spec R1（单轮 >300 秒打 WARNING，grade=warning-escalated）、tasks 1.2 | pass | 0/2 | - |
| stall-emission-streak-reset-and-boundaries | 发射点分级·连续重置与边界：130.5/100.0/130.5 相邻序列中 <=120s 样本重置连续计数（两条停滞记录均 INFO 级 grade='info'，无 WARNING）；恰 300.0s 单轮仍 grade='info'（升级线严格 >300）；恰 120.0s 与 119.9s 轮次全静默且样本照常入统计（汇总行 2 rounds）。出处：spec R1（<=300 秒、非连续第 2 轮 → info；遇 <=120s 样本重置计数）、core/agent_runner/runner.py:6184（严格 > 比较） | pass | 0/2 | - |
| run-agent-success-returns-latency-stats | 成功终态数据通路：rc=0 成功 run（stream 含 result success 事件）的 _run_agent 返回 tuple 必须携带本 run latency 统计（样本 4.0s+70.0s → rounds==2、stalls==1、max≈70）；run 档案 jsonl 的 run_metrics 行既有 latency_rounds/latency_stalls/latency_max 字段不回退且值一致；run 末摘要 stalls>60s=1（60s 统计口径不变）。出处：tasks 1.3、design 数据通路（stats 经 _run_agent 返回 tuple 携带）、core/agent_runner/runner.py:7148（现 4 元组返回）、:6819-6847（档案行字段） | pass | 0/2 | - |
| daily-summary-stall-aggregation-lines | 每日自省第 6 节 API 停滞聚合：临时项目夹具三个窗口内 run 转录（无 run_metrics 指标行、非初筛离群——正是旧机制漏掉的停滞 run），collect_daily_summary 输出须逐 run 列「- api-stall: <run_id> stalls=N total=Xs max=Ys」：样本 [100,90,70] → stalls=3、total=260、max=100；样本 [70,30] → stalls=1、total=70、max=70（30s 不计累计，>60s 统计口径）；全快样本 run 不列行；六个节头完整不受影响。出处：tasks 2.1、spec R3、design 方案 3、core/self_review.py:1754-1794（第 6 节） | pass | 0/2 | - |
| daily-summary-stall-aggregation-bounded-scan | 聚合有界流式口径：单 run 转录含 25000 行中性填充 + 行界外（>20000 行）一处 80s 停滞样本，聚合只计入界内 70s 停滞（stalls=1、total=70），不得出现 stalls=2——逐 run 扫描沿用 MIDFLIGHT_SCAN_MAX_LINES 行数上限、逐行解析、不整文件读入内存。出处：design 方案 3（有界流式补约定）、core/self_review.py:815、:1088-1098（深扫同款口径） | pass | 0/2 | - |
| daily-summary-stall-aggregation-degradation | 聚合降级契约：patch latency_samples_from_events 令聚合环节抛异常时，collect_daily_summary 仍正常返回完整摘要——第 6 节渲染占位行「（窗口内无中途信号）」、其余五节头完整，且聚合环节留下 warning 留痕（异常降级空产出 + warning，不阻断摘要与其余各节）。出处：design 方案 3 降级约定、core/self_review.py:1754-1756（第 6 节既有降级契约） | pass | 0/2 | - |
| new-stall-grading-test-file-green | 交付测试 3.1：新建 tests/test_api_stall_signal_grading.py 存在且 pytest 全绿（实现侧用例须覆盖分级函数边界（恰 300 秒、恰连续第 2 轮、120-300 秒单轮）、发射点日志级别断言（info→INFO、escalated→WARNING）、成功终态 run metrics 日志行带非零 stall 统计）。出处：tasks 3.1 | pass | 0/3 | - |
| latency-stats-tests-updated-green | 交付测试 3.2：tests/test_run_latency_stats.py 按新分级语义更新后 pytest 全绿——既有「单轮 >120 秒必打 WARNING」断言已改为分级语义（120-300 秒单轮 INFO、连续第 2 轮/超 300 秒 WARNING），60 秒统计口径与汇总行渲染的既有断言保留。出处：tasks 3.2、design 风险与兼容 | pass | 0/2 | - |
| three-test-files-contract-green | 交付测试 3.3 验收命令：tests/test_api_stall_signal_grading.py + tests/test_run_latency_stats.py + tests/test_agent_runner_modules_contract.py 一起 pytest 全绿——三常量同源契约不破（新常量独立声明，不并入既有同源组）。出处：tasks 3.3、spec 约束 | pass | 0/2 | - |
| self-review-regression-green | 读侧回归守卫：tests/test_self_review_midflight.py + tests/test_daily_self_review.py + tests/test_run_stall_accounting.py pytest 全绿——第 6 节新增聚合不破坏中途信号三小节渲染/占位行/环节降级等既有用例，run-stop-loss 判停预算面（读侧改动禁区）行为不变。出处：design 风险与兼容、spec 约束（纯读侧） | pass | 0/2 | - |
