# fix-self-review-phantom-running

## Why

2026-10-11 日报数据摘要第 2 节实测：窗口 22 个 run 中 8 个（36%）被计为「在跑/无终态」，而核实时刻机器上无任何在跑 agent——真有 run 卡死时会混在这批幻影里不可分辨，该口径缺口每日复发。取证（2026-10-11 只读核查）定位根因为**读侧分类器终态词表缺口**，非写侧缺终态回写：8 个幻影产物（4× -a1 首试 + 4× -a1-r1 原地重试）末行均为 superseded 终态（fix-retry-orphan-active-runs 1.1 建立的写侧补写不变量，工作正常），但 core/self_review.py 的 _classify_run（self_review.py:390）只认 result/error 两个终态词，superseded 落入「非 error」分支被判 running（self_review.py:436-437）；interrupted/cancelled/frozen-terminated/gate-blocked 同样不认识。框架已有全量词表单源 core/dashboard/data/runs.py 的 RUN_TERMINAL_STATUS_MAP（runs.py:326，含 superseded，注释明言「弃置文件仍需判终态，否则旧产物永远判 running」），dashboard classify_run 与 core/code_review.py read_progress 均已消费全量词表，self_review 是唯一落后消费方。

## What Changes

- 词表对齐：_classify_run 扩展终态识别——superseded 末行判为新 category superseded（弃置重试件，不算 running 也不算成功）；interrupted/cancelled/frozen-terminated/gate-blocked 末行判为新 category ended；result/error 分支的业务失败语义（marker/信号/超时/秒挂）逐字节不变。词表引用 RUN_TERMINAL_STATUS_MAP 单源，不另立第四套词表；MUST NOT 复用 liveness 的 RUN_TERMINAL_EVENT_TYPES（其故意排除 superseded 防退避窗口双派发，读侧统计语义与之不同）。
- 残余在跑的 stale 对账：对仍判 running 的 run 追加双源对账（对齐 _is_phantom_signal_failure 的「宁可不拦不可误伤」）——产物 mtime 超 RUN_STALE_SECONDS（1800s，runs.py:327）且 _run_terminal_success 查无终态 → 改计新 category stale（无终态残留）；查得 terminal=success → 按 succeeded 计（run 实际收尾、产物断尾）；mtime 新鲜或查无数据 → 维持 running 不改判。
- 日报第 2 节渲染新增「弃置/重试件」「其他终态」「无终态残留」三行，「在跑/无终态」收窄为真实在跑/近期无终态，不再被弃置件稀释。

## Impact

- Affected specs: 无既有 capability 覆盖（新建 phantom-running-guard）；与活跃 SPEC evo-add-run-metrics-lane-baseline 互补（其修指标行分组/成本维度，本条修读侧终态分类）。
- Affected code: core/self_review.py——_classify_run 词表、collect_runs_stats 计数桶、collect_failed_run_samples 口径锁定、collect_daily_summary 第 2 节渲染、stale 对账。
- Tests: tests/test_self_review_result_based_classification.py 扩展；tests/test_self_review_terminal_crosscheck.py 扩展。
- 风险：低——新增桶位与对账均为读侧增量；主要回归点是 counts dict 缺新键时 counts[category] += 1 KeyError（任务锁定）；产物写侧零改动。