# 验证报告：evo-wrapup-push-branch-guard

> ⚠️ 本报告由框架于 2026-11-17T01:02:23Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。
> 报告时效标记（判定本报告是否属上一轮）：合成源轮次指纹：report.json@2026-11-17T01:02:18.052224+00:00+run-result@mtime1794877342569292126

## 结论：✅ 通过（verified）

**状态：verified — 4/4 场景通过，0 失败，0 错误（全部场景通过）**

全绿快道: 4/4 场景通过、0 失败 0 警告——无分类对象，跳过 judge 机械 verified

| 指标 | 数量 |
| --- | --- |
| 通过 | 4 |
| 失败 | 0 |
| 错误 | 0 |
| 产品 Bug | 0 |
| 本链增量 Token（输入） | 0.49M |
| 本链增量 Token（输出） | 0.01M |


## 场景结果

| 场景 | 描述 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- | --- |
| master-checkout-pushes-master | master 检出项目（无本地 main 工作流）收尾推送目标为 master：推送后 origin/master tip 前进至本地 SHA、远端无 main、日志表达解析目标分支（分支解析回归守护） | pass | 0/6 | - |
| uptodate-no-tip-advance-not-pushed | 推送返回成功但远端 tip 未前进（Everything up-to-date 空转）：不计成功、不标 pushed 终态、单条告警（含本地/远端 tip）、零 error、零退避记账、零 push_failed 升级 | pass | 0/7 | - |
| tip-advance-normal-closeout | 推送后远端 tip 前进：按现有流程标记 pushed 收口（含远端分支新建 None→SHA 形态），零空转告警 | pass | 0/6 | - |
| startup-ahead-reconcile-exposed | 本地基分支领先远端 2 提交时 daemon 启动对账即暴露：WARNING 输出领先数与分支名、_base_branch_ahead=2、get_health_summary 聚合面消费领先数；领先 0 对照 INFO 留痕不告警 | pass | 0/6 | - |

## 本轮场景集变更

当前稳定场景集共 4 个（第 1 轮）。

- 首轮写入 4 个场景

