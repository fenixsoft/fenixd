## Deliverables

```yaml
- path: core/self_review.py
  kind: modify
- path: tests/test_self_review_result_based_classification.py
  kind: modify
- path: tests/test_self_review_terminal_crosscheck.py
  kind: modify
```

## 1. 终态词表对齐

- [ ] 1.1 core/self_review.py：_classify_run（self_review.py:390）扩展终态识别——末行 type=superseded 返回新 category superseded（detail 沿用 type 原词）；末行 type ∈ {interrupted, cancelled, frozen-terminated, gate-blocked} 返回新 category ended（detail 含原 type 词）；终态集合经延迟导入引用 core.dashboard.data.runs.RUN_TERMINAL_STATUS_MAP（runs.py:326）单源，MUST NOT 复制定义、MUST NOT 消费 core.agent_runner.liveness.RUN_TERMINAL_EVENT_TYPES；result/error 两分支的 marker/信号/超时/秒挂语义（self_review.py:407-443）逐字节不变，docstring category 枚举（:393）与 :400 running 释义同步更新。
- [ ] 1.2 core/self_review.py：collect_runs_stats（self_review.py:546）counts 初始 dict（:571-579）补 superseded/ended/stale 三键，防 counts[category] += 1 KeyError；docstring 桶位清单同步。
- [ ] 1.3 core/self_review.py：collect_failed_run_samples（self_review.py:605）确认并注释锁定新 category 不入失败样本（仅 category=="failed" 入选的现状保持，不加代码逻辑则只补注释说明）。
- [ ] 1.4 core/self_review.py：collect_daily_summary 第 2 节（:1577-1591）渲染补三行（弃置/重试件、其他终态、无终态残留），「在跑/无终态」行保留；行文案与 design D5 一致。

## 2. 残余无终态的 stale 对账

- [ ] 2.1 core/self_review.py：对 _classify_run 判 running 的 run 在 collect_runs_stats 计数前做对账（或下沉进 _iter_window_classified_runs 单点，二选一，保持与 collect_failed_run_samples 口径一致）——产物 mtime 距 window_end 超 RUN_STALE_SECONDS（延迟导入 core.dashboard.data.runs.RUN_STALE_SECONDS，runs.py:327）且 _run_terminal_success（self_review.py:469，含 attempt 后缀对齐）查无终态 → 改计 stale；查得 terminal=success → 改计 succeeded；mtime 新鲜或查无数据 → 维持 running 不改判（宁可不拦不可误伤）；对账仅触达 running 判定的 run。
- [ ] 2.2 core/self_review.py：stale 桶渲染（1.4 已含）与 docstring 补「无终态残留」释义；确认 collect_failed_run_samples 对 stale 亦不入选。

## 3. 测试

- [ ] 3.1 tests/test_self_review_result_based_classification.py：_classify_run 新词表用例——末行 superseded → superseded（夹具取 2026-10-09T19:01Z 实拍形态：末两行 transient_retry + superseded）；末行分别为 interrupted/cancelled/frozen-terminated/gate-blocked → ended 且 detail 含原 type 词；既有 result/error/marker/timeout/instant_hang/空文件断言全部不回归。
- [ ] 3.2 tests/test_self_review_terminal_crosscheck.py：collect_runs_stats 混合夹具（result/superseded/ended/running 各一）断言各桶计数正确且无 KeyError；失败样本列表不含 superseded/ended/running 类 run。
- [ ] 3.3 tests/test_self_review_terminal_crosscheck.py：stale 对账四态用例——mtime 陈旧 + 无指标终态 → stale；mtime 陈旧 + 指标 terminal=success → succeeded；mtime 新鲜 + 无终态 → 维持 running；指标索引查无该 run → 不改判；mtime 以注入/monkeypatch 控制，测试不 sleep。
- [ ] 3.4 tests/test_self_review_result_based_classification.py：collect_daily_summary 第 2 节渲染用例——五类产物并存时各行计数之和等于总 run 数、新三行存在、「在跑/无终态」不含 superseded（以 2026-10-11 日报 8 幻影同构小样本回归：同形态夹具下在跑计数从 8 → 0、弃置/重试件 = 8）。