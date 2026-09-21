# 验证报告：evo-merge-back-spec-dir-inflight-guard

> ⚠️ 本报告由框架于 2026-09-20T20:21:54Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。
> 报告时效标记（判定本报告是否属上一轮）：合成源轮次指纹：report.json@2026-09-20T20:21:54.645160+00:00

## 结论：✅ 通过（verified）

**状态：verified — 9/9 场景通过，0 失败，0 错误（全部场景通过）**

全绿快道: 9/9 场景通过、0 失败 0 警告——无分类对象，跳过 judge 机械 verified

| 指标 | 数量 |
| --- | --- |
| 通过 | 9 |
| 失败 | 0 |
| 错误 | 0 |
| 产品 Bug | 0 |
| 本链增量 Token（输入） | 0.79M |
| 本链增量 Token（输出） | 0.01M |


## 场景结果

| 场景 | 描述 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- | --- |
| guard-inflight-deferral | spec/changes/<spec>/ 目录有未提交改动（tracked/untracked/specs子目录）时 merge-back 顺延不 merge，主树零污染 (3.1) — 出处：tests/test_merge_back_spec_dir_guard.py::TestSpecDirInflightGuard | pass | 0/2 | - |
| guard-parse-fail-open | spec 名解析失败（非 fenix/<spec>-<ts> 分支名）时 fail-open 放行，不对 spec/changes/ 全目录做检测 (3.5) — 出处：tests/test_merge_back_spec_dir_guard.py::TestSpecParseFailOpen | pass | 0/2 | - |
| guard-gate-ordering | 闸门顺序回归——语义冲突返回 rehearsed、WIP 重叠返回 wip_gate_blocked，二者均不被顺延信号接走 (3.4) — 出处：tests/test_merge_back_spec_dir_guard.py::TestGateOrdering | pass | 0/2 | - |
| guard-retryable-classification | 合并失败分类后可重试路径仅重试合并而非重派实现（run_id 不变），_retry_count/_merge_fp/_merge_streak 均未变化 (3.2) — 出处：tests/test_merge_back_spec_dir_guard.py::TestRetryableClassification | pass | 0/2 | - |
| guard-bounded-deferral | 顺延有界——连续顺延达上限后回落到告警/人工通道（admin 信号写入），不无限顺延 (3.3) — 出处：tests/test_merge_back_spec_dir_guard.py::TestBoundedDeferral | pass | 0/2 | - |
| guard-non-dispatch-deferral | 非派发调用方遇顺延不消费 _repair_awaiting_remerge 标记（repair re-merge / state_machine recovery / fast-track）(1.5) — 出处：tests/test_merge_back_spec_dir_guard.py::TestNonDispatchDeferral | pass | 0/2 | - |
| guard-retry-succeeds | 重试成功时以同一 run_id 收工，且实现预算闸门生效（不绕过 impl_budget_exhausted）(2.x) — 出处：tests/test_merge_back_spec_dir_guard.py::TestRetrySucceeds | pass | 0/2 | - |
| guard-regression-5files | 回归五个既有测试文件全绿，本变更不改变 WIP 重叠闸门/self-heal/repair lane/merge-tree rehearsal 既有语义 (3.6) — 出处：tests/test_worktree_merge_guard.py + 4 files | pass | 0/2 | - |
| guard-all-core-19 | 核心测试文件 test_merge_back_spec_dir_guard.py 全部 19 个用例一次性运行（覆盖收集期导入、fixture 解析等环境依赖） | pass | 0/2 | - |

## 本轮场景集变更

当前稳定场景集共 9 个（第 1 轮）。

- 首轮写入 9 个场景

