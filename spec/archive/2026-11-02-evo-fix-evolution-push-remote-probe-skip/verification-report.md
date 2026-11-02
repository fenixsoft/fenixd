# 验证报告：evo-fix-evolution-push-remote-probe-skip

> ⚠️ 本报告由框架于 2026-10-30T10:19:32Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。
> 报告时效标记（判定本报告是否属上一轮）：合成源轮次指纹：report.json@2026-10-30T10:19:31.331086+00:00+run-result@mtime1793355571379584811

## 结论：✅ 通过（verified）

**状态：verified — 8/8 场景通过，0 失败，0 错误（全部场景通过）**

全绿快道: 8/8 场景通过、0 失败 0 警告——无分类对象，跳过 judge 机械 verified

| 指标 | 数量 |
| --- | --- |
| 通过 | 8 |
| 失败 | 0 |
| 错误 | 0 |
| 产品 Bug | 0 |
| 本链增量 Token（输入） | 0.13M |
| 本链增量 Token（输出） | 0.03M |


## 场景结果

| 场景 | 描述 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- | --- |
| push-probe-contract-suite | 契约测试套件全过：tests/test_evolution_push_remote_probe.py 8 用例覆盖零 remote 双车道跳过、同仓连续失败聚合、有 remote 单次失败文案钉（tasks 3.1/3.2/3.3）。出处 core/evolution.py:1014-1212、core/self_review.py:2662-2758 | pass | 0/10 | - |
| push-probe-zero-remote-evolution-lane | evolution 车道零 remote 仓回写静默跳过：真实 git 仓（tracked .fenix/todo.md、无 remote）调 _commit_todo_marker——push 子进程零调用、commit 照常产生、DEBUG 日志含项目根路径、全程无 WARNING（spec Requirement 零 remote 仓回写跳过 push）。出处 core/evolution.py:1194-1196 | pass | 0/2 | - |
| push-probe-zero-remote-self-review-lane | self_review 车道零 remote 仓同款跳过：_commit_todo 经共用探测助手 _git_has_remote——push 子进程零调用、commit 照常产生、注入 logger DEBUG 含项目根路径、无 WARNING（独立于中央 sink 取证，MERGE-NOTES 验证纪律）。出处 core/self_review.py:2726-2736 | pass | 0/2 | - |
| push-probe-consecutive-failure-aggregation | 同仓同日连续两次 push 失败收敛不刷屏：首败发一条聚合 WARNING（含仓路径、连续第 1 次失败计数、stderr 尾部 fatal 行），次败仅递增计数降级 DEBUG（连续失败计数 2）、不新增 WARNING（spec Requirement push 恒失败聚合告警）。出处 core/evolution.py:1053-1084 | pass | 0/2 | - |
| push-probe-cross-day-reset-and-success-clear | 聚合状态边界双钉：当日已告警标记跨日重置而连续失败计数不清零（次日首败再发含最新计数「连续第 3 次失败」的一条聚合）；push 成功清零连续计数（当日已告警标记不动——同日再失败不新告警、DEBUG 计数自 1 重计）。出处 core/evolution.py:1042-1050、1066-1069 | pass | 0/3 | - |
| push-probe-warning-copy-repo-path-stderr-tail | 有 remote 单次 push 失败记常规 WARNING 且文案可归仓：含项目根路径＋stderr 尾部（超长 remote URL 下尾部切片 [-200:] 保留最终 fatal 行 does not appear to be a git repository——旧 [:200] 头部切片必丢）；commit 仍产生不回滚（task 1.3）。出处 core/evolution.py:1070-1076、1208-1211 | pass | 0/2 | - |
| push-probe-self-review-failure-no-aggregation | self_review 车道 push 失败记常规 WARNING 且不聚合（design 分界：每日至多一次 push 无刷屏面）：连续两次失败各自记 WARNING（共两条，均含仓路径与 stderr 尾部），commit 均产生，且不触碰 evolution 车道聚合状态。出处 core/self_review.py:2745-2757 | pass | 0/2 | - |
| push-probe-shared-probe-wiring | 收口与鲁棒性：两车道共用探测助手 _git_has_remote（self_review.py 延迟导入 core.evolution 单点收口，无实现漂移）；knowledge_backfill 第三链路（append/upsert 写后就地提交）经共享 _commit_todo_marker 自动获得跳过语义（本 SPEC 不改 knowledge_backfill.py，自定义 subject 复用形态实跳验证）；探测函数三态——零 remote False、有 remote True、探测故障（非 git 目录返回非零）保守按有 remote 处理。出处 core/evolution.py:1014-1039、core/self_review.py:2730、core/knowledge_backfill.py:331-333 | pass | 0/4 | - |

## 本轮场景集变更

当前稳定场景集共 8 个（第 1 轮）。

- 首轮写入 8 个场景

