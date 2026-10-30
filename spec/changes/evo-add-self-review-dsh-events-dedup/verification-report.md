# 验证报告：evo-add-self-review-dsh-events-dedup

> ⚠️ 本报告由框架于 2026-10-30T10:05:31Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。
> 报告时效标记（判定本报告是否属上一轮）：合成源轮次指纹：report.json@2026-10-30T10:05:29.884100+00:00+run-result@mtime1793354729934095182

## 结论：✅ 通过（verified）

**状态：verified — 6/6 场景通过，0 失败，0 错误（全部场景通过）**

全绿快道: 6/6 场景通过、0 失败 0 警告——无分类对象，跳过 judge 机械 verified

| 指标 | 数量 |
| --- | --- |
| 通过 | 6 |
| 失败 | 0 |
| 错误 | 0 |
| 产品 Bug | 0 |
| 本链增量 Token（输入） | 0.13M |
| 本链增量 Token（输出） | 0.02M |


## 场景结果

| 场景 | 描述 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- | --- |
| dsh-companion-contract-tests-pass | 契约测试交付物验证（tasks 2.1/2.2）：-k 过滤运行 tests/test_self_review_archive_stats.py 中本 SPEC 新增的三个契约用例（伴随流计 1 次、孤儿伴随流不入 stale 桶、过滤零误伤），全部 PASSED。出处：tests/test_self_review_archive_stats.py:83-146 | pass | 0/5 | - |
| companion-and-main-counted-once-probe | SPEC 场景「主文件与伴随流并存」直测库函数：归档目录构造同 run 的 impl-dsh-1.jsonl 主文件与 impl-dsh-1.dsh-events.jsonl 伴随流并存，_collect_run_files 收集集仅含主文件、伴随流文件本体不被删改（仍作深扫证据源），collect_runs_stats 统计 total=1/succeeded=1/stale=0/running=0。出处：core/self_review.py:547-586（合并点统一过滤 :586）、core/agent_runner/liveness.py:171-184（同源判式） | pass | 0/2 | - |
| orphan-companion-not-in-stale-probe | SPEC 场景「伴随流不得进入 stale 桶」直测库函数（空状态/修复前事故形态）：孤儿伴随流（无终态事件 + mtime 超 RUN_STALE_SECONDS 注入陈旧戳）经收集面过滤后收集集为空，collect_runs_stats 统计 total=0/stale=0/running=0，不落入 stale（无终态残留）桶。出处：core/self_review.py:585-586、core/dashboard/data/runs.py RUN_STALE_SECONDS | pass | 0/2 | - |
| filter-no-false-positive-probe | SPEC 场景「合法 run 不受影响」直测库函数：run_id 中段含 dsh-events 字样的正常 run（判式锚定 stem 尾部不误伤）与当前目录伴随流并存（当前目录 glob 侧过滤覆盖），收集集恰为两个正常 run，统计 total=2/succeeded=2/stale=0/running=0 与既有行为一致。出处：core/self_review.py:571-586、tests/test_self_review_archive_stats.py:122-146 | pass | 0/2 | - |
| full-file-regression-existing-behavior | 回归点：全量运行 tests/test_self_review_archive_stats.py 全部 18 个既有+新增用例（覆盖归档并集统计、跨窗口归属、同 run_id 去重、review- 前缀排除、失败样本同源），确认过滤不误伤既有统计行为。出处：tests/test_self_review_archive_stats.py:1-337（实测输出 18 passed, 6 warnings） | pass | 0/6 | - |
| combined-dedup-and-filter-both-globs-probe | 组合交互流程（两处 glob 一次覆盖 × 同 run_id 去重）：当前目录与归档目录同时存在同 run_id 的主文件与伴随流（当前目录主文件成功、归档主文件失败，伴随流双侧并存），收集集恰为 1 个（当前目录优先去重）且无任何 .dsh-events 伪 run_id，统计 total=1/succeeded=1/failed=0/stale=0。出处：core/self_review.py:576-586（归档并入+合并点过滤） | pass | 0/2 | - |

## 本轮场景集变更

当前稳定场景集共 6 个（第 1 轮）。

- 首轮写入 6 个场景

