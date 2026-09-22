# 验证报告：fix-observability-gaps

> ⚠️ 本报告由框架于 2026-09-17T08:17:28Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。
> 报告时效标记（判定本报告是否属上一轮）：合成源轮次指纹：report.json@2026-09-17T08:17:28.282862+00:00

## 结论：✅ 通过（verified）

**状态：verified — 14/14 场景通过，0 失败，0 错误（全部场景通过）**

全绿快道: 14/14 场景通过、0 失败 0 警告——无分类对象，跳过 judge 机械 verified

| 指标 | 数量 |
| --- | --- |
| 通过 | 14 |
| 失败 | 0 |
| 错误 | 0 |
| 产品 Bug | 0 |
| 本链增量 Token（输入） | 4.88M |
| 本链增量 Token（输出） | 0.05M |


## 场景结果

| 场景 | 描述 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- | --- |
| run-metrics-success | 正向路径·成功 run 记录耗时（spec 场景「成功 run 记录耗时」）：_execute_agent 成功收尾产生一条 metric_type=run_metrics 结构化指标，含 run_id/spec/agent_type/duration_seconds/turns/usage 四分项/cost_usd/terminal=success/provider。duration_seconds 为真实耗时（time.time()-start_time 落盘），MUST NOT 仅靠 run 文件 mtime 推算。出处：core/agent_runner/runner.py 收尾日志点（tasks.md 1.1）。 | pass | 0/2 | - |
| run-metrics-failure | 异常路径·失败 run 亦记录（spec 场景「失败 run 亦记录」）：_run_claude 抛异常 + max_retries=1 重试耗尽 → terminal=failure 仍产生指标，duration_seconds>0，失败路径 usage 按 0 计、cost_usd=None（不伪造金额）。出处：core/agent_runner/runner.py 失败收尾分支（tasks.md 1.1/1.3）。 | pass | 0/2 | - |
| run-metrics-consumer | 回归点·指标可被消费（spec 场景「指标可被消费」落地口径 + tasks.md 1.5 消费点验收）：消费点 _run_meta_cached 优先读结构化指标的 duration_seconds（42s）而非 run 产物 mtime 推算（mtime 故意放大 → 推算值会很大）；无指标日志时（旧日志/未触发）回退 mtime 推算不丢历史。出处：core/dashboard/data/runs.py _run_meta_cached（tasks.md 1.5）。 | pass | 0/3 | - |
| transition-context-auto | 功能·自动转换携带来源（spec 场景「自动转换携带来源」）：transition() 显式转换携带 channel=auto + trigger_run_id + agent_type 落入日志 context。出处：core/state_machine.py transition（tasks.md 2.1）。 | pass | 0/2 | - |
| transition-context-manual | 功能·人工转换可区分（spec 场景「人工转换可区分」）：Dashboard/CLI 触发的人工转换 channel=manual，trigger_run_id 为 None（人工来源无可绑定 run）。出处：core/state_machine.py transition manual 通道（tasks.md 2.1）。 | pass | 0/2 | - |
| transition-context-gate-recovery | 功能·transition_gate 门禁逃生门携带 context（spec「每次状态转换 MUST 携带结构化 context」）：Gate transition（小写 t，verified→testing）日志前缀不被旧 `Transition: ` 正则命中，必须同样携带 channel=recovery + trigger_run_id + agent_type 结构化 context。出处：core/state_machine.py transition_gate（tasks.md 2.1；spec.md 2.1 评审澄清）。 | pass | 0/2 | - |
| transition-idempotent-no-log | 排除项·幂等短路不产生 Transition 日志（spec.md 2.1a 评审澄清）：old_status==new_status 状态未发生改变，transition() 返回 True 但 MUST NOT 产生带 context 的 Transition: 日志行（幂等分支不落盘）。调用方传 context 参数无害。出处：core/state_machine.py 幂等分支（tasks.md 2.1a）。 | pass | 0/2 | - |
| timeline-structured-consumption | 功能·新事件走结构化（spec 场景「新事件走结构化」）：带 channel context 的 Transition 行 → get_spec_timeline 结构化解析（不依赖 message 文本正则），状态节点含 from/to/channel/trigger_run_id/agent_type；Gate transition 同样被结构化路径覆盖。出处：core/dashboard/data/timeline.py get_spec_timeline（tasks.md 3.1）。 | pass | 0/3 | - |
| timeline-regex-fallback | 功能·历史事件走兜底（spec 场景「历史事件走兜底」）：无 context 的旧格式 Transition 行 → 正则兜底正确解析 from/to，channel 为 None；历史日志不因缺 context 丢事件（双轨读侧保证）。出处：core/dashboard/data/timeline.py 正则兜底（tasks.md 3.1）。 | pass | 0/2 | - |
| timeline-mixed-window | 交互流程·混合窗口无重复无丢失（tasks.md 3.1a/3.2）：同一日志文件新旧格式共存 → 所有节点重建、连续前向转换折叠为单节点且 chain 完整保留中间状态、channel 随折叠保留；transition() 成对写的 Updated SPEC 行去重跳过，同一次转换不出现两个状态节点。出处：core/dashboard/data/timeline.py 去重与折叠（tasks.md 3.1a）。 | pass | 0/2 | - |
| admin-retention-24h | 功能·跨日状态历史可见（spec 场景「跨日状态历史可见」）：admin_state_history 保留窗口 ≥24h —— 24h 内 ready/implementing 状态变化历史条目保留不被裁掉；超过 24h 的旧条目被裁剪；changes 无条数上限（只按时间裁剪）；flapping 检测（FLAPPING_WINDOW_MINUTES=10）输出不受保留窗提升影响。出处：core/admin_monitor.py _update_history HISTORY_RETENTION_SECONDS=24*60*60（tasks.md 4.1/4.1a）。 | pass | 0/5 | - |
| supervisor-single-write | 功能·日志不得双写（spec 场景「单行单事件」）：supervisor.log() 在 stdout 被重定向到 LOG_FILE（实际启动命令 `>> supervisor.log 2>&1`）时，每条消息只写一次（文件为唯一 sink，去掉 print）；stdout 未重定向时既写文件又 print 保留控制台可见性。出处：bin/fenixd_supervisor.py log()（tasks.md 4.2）。 | pass | 0/5 | - |
| cost-no-double-count | 回归护栏·run 指标 cost_usd 不与 dashboard 计价表现算叠加（tasks.md 1.6）：新增落盘的 cost_usd 只做事件留痕，页面成本口径维持既有计价表。出处：core/dashboard/data/timeline.py _cost_summary_from_timeline（tasks.md 1.6）。 | pass | 0/5 | - |
| timeline-web-render | 页面/交互·dashboard 详情页时间轴区域渲染（spec「时间轴优先消费结构化转换事件」UI 可观测面）：导航到 spec 详情页 → div.spec-detail-timeline 渲染「状态转移」Tag 与状态序列（from→to），channel 上下文已由后端结构化消费落地至 timeline 数组（前端直接展示后端产出，不再做 message 正则）；该场景承担前端渲染契约验收，后端消费逻辑已由 cli 场景覆盖（铁律：后端验证用 cli，前端交互用 web）。导航出处：core/dashboard/static/src/app.tsx:103,107（hash 路由 #/projects/fenixd/<spec>）；时间轴渲染：core/dashboard/static/src/pages/projects/detail.tsx:855-894。 | pass | 0/6 | - |

## 本轮场景集变更

当前稳定场景集共 14 个（第 1 轮）。

- 首轮写入 14 个场景

