# 验证报告：evo-add-judge-result-predispatch-rename

> ⚠️ 本报告由框架于 2026-10-05T23:13:14Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。
> 报告时效标记（判定本报告是否属上一轮）：合成源轮次指纹：report.json@2026-10-05T23:13:14.134309+00:00+run-result@mtime1791241994169696815

## 结论：✅ 通过（verified）

**状态：verified — 9/9 场景通过，0 失败，0 错误（全部场景通过）**

全绿快道: 9/9 场景通过、0 失败 0 警告——无分类对象，跳过 judge 机械 verified

| 指标 | 数量 |
| --- | --- |
| 通过 | 9 |
| 失败 | 0 |
| 错误 | 0 |
| 产品 Bug | 0 |
| 本链增量 Token（输入） | 1.50M |
| 本链增量 Token（输出） | 0.02M |


## 场景结果

| 场景 | 描述 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- | --- |
| judge-predispatch-stale-archived-gate-passes | 正向路径：预置上轮遗留 judge 结果文件后，run_planner(mode=judge) 派发前文件已原子改名 prev-judge-result.json 留档、本轮产物硬门放行、留档内容可回溯（出处：core/agent_runner/runner.py:1194-1201 run_planner judge 分支留档、runner.py:1238-1297 _archive_prev_judge_result；tests/test_agent_runner_gate.py:845 用例） | pass | 0/2 | - |
| judge-predispatch-no-leftover-zero-impact | 空状态：无遗留结果文件时 judge 派发行为零变化——不产生 prev-judge-result.json、run 正常成功（出处：core/agent_runner/runner.py:1267-1268 FileNotFoundError 常态路径；tests/test_agent_runner_gate.py:880 用例） | pass | 0/2 | - |
| judge-predispatch-rename-failure-no-block | 异常路径：改名失败（OSError）仅 WARNING 留痕、派发照常不被阻断、无留档产物、agent 覆写原路径（出处：core/agent_runner/runner.py:1269-1276 OSError 分支 fallback_unlink=False 不删原文件；tests/test_agent_runner_gate.py:903 用例） | pass | 0/2 | - |
| judge-plan-mode-dispatch-no-archive | 交互流程/分支区分：mode=plan 派发不触发留档，mode=judge 派发触发留档——改名仅挂在 judge 分支（出处：core/agent_runner/runner.py:1194 if mode == "judge" 门控；tests/test_agent_runner_gate.py:932 用例） | pass | 0/2 | - |
| judge-archive-helper-fallback-unlink | 异常路径：_archive_prev_judge_result 双语义单实现——清理路径（fallback_unlink=True）改名失败退化为删除原文件；留档路径（缺省）改名失败保留原文件不删（出处：core/agent_runner/runner.py:1275-1291；tests/test_agent_runner_gate.py:948 用例） | pass | 0/2 | - |
| judge-stale-retry-no-repeat-hit | 回归/防护：硬门命中陈旧残留进入原地重试前陈旧文件已被改名留档，重试不再重复命中同一陈旧文件、再败归因退化为「结果文件缺失」、终态归因不含「陈旧」；跨 spec 共享根文件 .fenix/.fenix-run-result.json 不被触碰（出处：core/agent_runner/runner.py:4355-4369 planner-judge 限定清理、result_gate.py:515-519 新鲜度硬门；tests/test_agent_runner_gate.py:966 用例） | pass | 0/2 | - |
| judge-stale-rejection-disposition-upgraded | 存量契约升级回归：主树残留上一轮合法文件 + 本轮零产出仍被新鲜度硬门拦截（首次门禁失败归因「早于本轮启动」），但拦截后处置升级——陈旧文件改名留档、终态归因退化为「结果文件缺失」且不含「早于本轮启动」（出处：tests/test_agent_runner_gate.py:444 存量用例按新契约更新；result_gate.py:489-520 硬门 fail-closed 语义不变） | pass | 0/2 | - |
| judge-archive-independent-probe | 独立行为探针（不经仓库测试自证，直接驱动 _archive_prev_judge_result）：有遗留改名留档且内容可回溯 / 无遗留返回 False / 跨 spec 共享根文件不触碰 / 留档语义改名失败保留原文件 / 清理语义改名失败退化删除 / 留档路径形态 per-spec 目录（出处：core/agent_runner/runner.py:1238-1297 单一实现；core/agent_runner/prompt_builder.py:184-196 planner_result_path 路径形态） | pass | 0/5 | - |
| judge-gate-file-full-regression | 回归点：tests/test_agent_runner_gate.py 整文件回归（含 6 个本 spec 新增用例与全部存量硬门/verdict/终态事件用例）全部通过，确认新增改名逻辑未破坏既有产物硬门行为（出处：tasks.md 2.1；tests/test_agent_runner_gate.py 全文件，本地实测 35 passed） | pass | 0/2 | - |

## 本轮场景集变更

当前稳定场景集共 9 个（第 1 轮）。

- 首轮写入 9 个场景

