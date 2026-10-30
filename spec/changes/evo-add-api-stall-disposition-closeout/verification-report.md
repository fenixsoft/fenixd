# 验证报告：evo-add-api-stall-disposition-closeout

> ⚠️ 本报告由框架于 2026-10-30T13:34:47Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。
> 报告时效标记（判定本报告是否属上一轮）：合成源轮次指纹：report.json@2026-10-30T13:30:25.180556+00:00+run-result@mtime1793367275670138713

## 结论：❌ 未通过（Bug Found）

**状态：bug-found — 14/15 场景通过，1 失败，0 错误（1 个真实产品 Bug）**

15 场景：14 pass / 1 fail。唯一失败 monitor-escalated-signal-negative-controls 为产品缺陷（product-bug，major）：AdminMonitor 升级信号检测面缺 success 终态门控，曾停滞但正常完成的 run 被误落 api_round_stall_escalated major 信号，违反验收「无信号、无重试意图」。与上轮裁决同指纹、同根因（本轮独立复核 admin_monitor.py:3258-3310 确认仍无终态判据），分类不变；上轮两处场景文件缺陷修复后本轮复跑均转 pass。走 bug-found 派修复链：检测面补 result 终态行读取与 success 豁免，并建议同步补单测负控 success 终态用例。

| 指标 | 数量 |
| --- | --- |
| 通过 | 14 |
| 失败 | 1 |
| 错误 | 0 |
| 产品 Bug | 1 |
| 本链增量 Token（输入） | 0.45M |
| 本链增量 Token（输出） | 0.11M |


## 真实产品 Bug

### BUG-01（severity=major）· exit_code/output_match（信号负控）

- 关联场景：monitor-escalated-signal-negative-controls
- 描述：AdminMonitor api_round_stall_escalated 升级信号检测面缺 success 终态门控：曾停滞但正常完成（success 终态）且 latency_max=400s 的 run 被误落 major 升级信号并触发 Administrator 处置留痕，违反 tasks.md 验收「曾停滞但正常完成：无信号、无重试意图」，会对健康收尾 run 持续产生误报人工升级噪音
- 根因：core/admin_monitor.py:3258-3310 _check_api_round_stall_escalated 仅校验 latency_max 类型与 >STALL_ROUND_ESCALATE_SECONDS 阈值（:3306-3310），不读 run jsonl 的 result 终态行，success/error 形态对检测面不可见；重试意图面（maintenance_runs 车道收尾）已正确门控（lane-escalated-success-no-retry pass），仅信号面缺门控
- 证据（场景 monitor-escalated-signal-negative-controls 结构化证据，引用）：
  - failed_assertions: [{"type": "exit_code", "selector": "负控(a) ok-escalated（success 终态+latency_max=400）", "expected": 0, "actual": 1}, {"type": "output_match", "selector": "combined contains ESC-SIGNAL-NEGATIVES-OK", "expected": "ESC-SIGNAL-NEGATIVES-OK", "actual": "AssertionError: ok-escalated: 不应落升级信号，实际落 kind=signal（escalated=True，run_id=code-review-1790006001）与 kind=escalation 留痕各 1 条，脚本中止"}]
  - screenshots: []
  - first_failed_step: 步骤1 run：负控(a) ok-escalated 断言失败——AdminMonitor 对 success 终态 run（latency_max=400）仍落 api_round_stall_escalated 升级信号


## 场景结果

| 场景 | 描述 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- | --- |
| envelope-stall-redispatch-field-default | 信封字段：CodeReviewResult 增 stall_redispatch 重派意图字段且缺省 None，形态对齐 ratelimit_redispatch 先例，非重派路径消费侧零感知（tasks 2.2；出处 core/agent_runner/result_gate.py:367-403） | pass | 0/2 | - |
| lane-metrics-latency-kwarg-contract | 车道收尾指标契约：_log_lane_run_metrics 签名增 latency 参数（缺省 None）并透传 _log_run_metrics；缺省调用零样本语义向后兼容；真实 _log_run_metrics 零样本回退保持 0/0/None、带 latency 时如实入行（tasks 1.1；出处 core/agent_runner/maintenance_runs.py:1308-1364、core/agent_runner/runner.py:9132-9200） | pass | 0/2 | - |
| lane-call-sites-latency-wiring | 车道接线结构：五个车道收尾调用点逐一传 latency，各车道 try 前预初始化 _stall_latency = None（_run_agent 抛出路径零样本语义、防 NameError）（tasks 1.1；出处 core/agent_runner/maintenance_runs.py 五处调用点 :566/:929/:1831/:2600/:3499 及 :387/:856/:1611/:2243/:3408 五处解包） | pass | 0/2 | - |
| lane-error-terminal-latency-and-stall-intent | error 终态透传与意图登记：run_code_review 收到 warning-escalated 过程 stats（max 726.284 > 300）但被产物硬门拒绝时，终态 run_metrics 的 latency_* 与过程指标一致（非 0/0/null），且登记 stall_redispatch 意图（run_id 指向本 run）、ratelimit 意图恒缺位（tasks 1.1+2.3、验收 1/3；出处 core/agent_runner/maintenance_runs.py:2243-2624、core/agent_runner/latency.py:43） | pass | 0/2 | - |
| lane-raise-path-zero-sample-no-nameerror | 抛出路径收尾：_run_agent 抛 RuntimeError 时车道收尾 latency 走零样本（None）、不抛 NameError、不登记 stall 意图，run 以 error 信封返回（tasks 1.1、验收 1；出处 core/agent_runner/maintenance_runs.py 车道 try 前预初始化约定） | pass | 0/2 | - |
| lane-double-condition-ratelimit-priority | 意图互斥与优先级：同 run 双条件（429 归因且停滞升级语义位）时 ratelimit 意图优先，stall_redispatch 必须缺位——429 有明确 provider 归因，停滞归因仍是假设（tasks 2.3、验收 3；出处 core/agent_runner/maintenance_runs.py:2575-2624、design.md 决策 3） | pass | 0/2 | - |
| lane-escalated-success-no-retry | 曾停滞但正常完成：escalated 过程 stats（max 350 > 300）但成功收尾时，终态 latency 照常透传（成功路径不回归）且 MUST NOT 登记 stall 重试意图（验收 4；出处 core/agent_runner/maintenance_runs.py run_code_review 收尾、specs/api-stall-disposition/spec.md 需求 3） | pass | 0/2 | - |
| stall-ctx-input-tokens-provider | 留痕富化：api_round_stall 事件 context（_stall_ctx）在 warning-escalated 档补当轮上下文规模（input tokens）与 provider 字段，供跨日归因积累（tasks 3.1；出处 core/agent_runner/runner.py:6492-6540、proposal.md 目标 4） | pass | 0/2 | - |
| runner-stall-comment-consistency | 注释一致性：runner.py 发射点（不 kill、不重派）与延迟铁律两处注释按新行为更新——运行中路径不触发约束不变，指向收尾后 AdminMonitor 检测面/信号面，不再绝对化宣称不写 admin_alerts（spec 需求 5；出处 core/agent_runner/runner.py:6491、:7065） | pass | 0/2 | - |
| monitor-escalated-signal-dedup | 升级信号与去重：error 终态 run jsonl 终态 run_metrics 行 latency_max=726.284（>300）→ AdminMonitor 巡检（run_once，节拍镜像 _check_code_review_stall）落 1 条 api_round_stall_escalated 信号（spec=null、run_id 进 hash 位）；同进程二轮与跨 monitor 实例均不新增（tasks 2.1、验收 2；出处 core/admin_monitor.py:1714/:2427、core/admin_store.py:694-720） | pass | 0/2 | - |
| monitor-escalated-signal-negative-controls | 信号负控：曾停滞但正常完成（success 终态 + latency_max 400）、未达升级线（error + latency_max 200）、零样本投影（error + latency_max None）三类 run 均不落升级信号（tasks 2.1、验收 2/4；出处 core/agent_runner/latency.py:43 STALL_ROUND_ESCALATE_SECONDS 严格大于比较） | failed（已修正） | 2/2 | product-bug |
| monitor-stall-redispatch-consume-cap-cooldown | 受控重试消费：AdminMonitor 对 stall_redispatch 意图按冷却+单飞骨架消费——冷却到期前不重派、到期后以原 manifest 重派恰一次且 redispatch_of 指向原 run、同生命周期第二个意图不再重派（上限 1 次）（tasks 2.4、验收 3；出处 core/admin_monitor.py:2177-2262 冷却/上限/单 Timer 守卫骨架、:2264 起消费链） | pass | 0/2 | - |
| deliverable-tests-api-stall-disposition-pass | 交付测试文件全绿：tests/test_api_stall_disposition.py 覆盖 error 终态 latency 一致、成功终态不回归、无停滞零变化、抛出路径零样本不 NameError、信号去重、意图互斥/上限/redispatch_of 链（tasks 4.1+4.2；出处 spec/changes/evo-add-api-stall-disposition-closeout/tasks.md 第 4 节） | pass | 0/2 | - |
| regression-grading-and-persistence-tests | 回归：既有停滞分级与 run metrics 持久化测试不回归——成功终态透传、分级纯函数、发射点级别、终态行契约均保持（验收 1 成功终态透传不回归；出处 tests/test_api_stall_signal_grading.py、tests/test_run_metrics_persistence.py） | pass | 0/2 | - |
| regression-ratelimit-redispatch-tests | 回归：既有 429 重派登记/归因/消费与手动 worker 意图上交测试不回归——stall 意图复用同骨架不得破坏 ratelimit 通道（tasks 2.3/2.4 互斥前提；出处 tests/test_provider_failover.py、tests/test_code_review.py） | pass | 0/2 | - |


## 断言级豁免清单

以下失败断言被归类为非产品缺陷（不记产品 Bug），逐条列出供人工复核豁免是否掩盖真实缺陷（场景级一句话归因不足以复核）。

无非 product-bug 的被豁免失败断言。

## 本轮场景集变更

当前稳定场景集共 15 个（第 1 轮）。

- 首轮写入 15 个场景

