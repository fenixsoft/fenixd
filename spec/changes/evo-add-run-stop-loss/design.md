# design: add-run-stop-loss

## D1 事故时间线与根因

2026-09-25 planner-plan-add-regression-auto-fix-1790308587（fenixd.log:23707-23937）：11:56:27 本地派发，attempt 1 于 12:21:59 退出（83 轮、median 6.7s、stalls 4，「exit 0 但结果文件缺失」由 core/agent_runner/result_gate.py:429 产物硬门拦截）；testing 车道 12:13:15 进入并行产物有界等待（core/pm_engine/verification/pipeline.py:2106-2229，_PARALLEL_PLAN_WAIT_TIMEOUT_DEFAULT=900），12:21:59 经 run 死检测分支（非 900 秒到期）判隔离，调 _stop_parallel_planning（core/pm_engine/engine.py:1073 起）执行 cancel_run。取消落在 attempt 间隙：cancel_run 的 not_running 分支（core/agent_runner/runner.py:733-747）不登记旗标直接返回；30 秒 backoff 后产物硬门 in-place retry（runner.py:3151 附近）重派 -r1，让位判据 _should_give_up_before_retry（runner.py:3165 附近）只查 spec 状态迁移、frozen、hold，不查并行出题 discarded 标记，-r1 复活再跑 36 分钟（101 轮），与 12:21:59 已启动的串行 run 并发双跑，run 级 duration 3732 秒、cost_usd=7.705119 全部沉没（fenixd.log:23880-23881）。

框架对该竞窗已有自认：core/pm_engine/engine.py:1013-1015 注释（code-review item b4b98c69a4e1）明写「attempt 尚未注册时 cancel 落 not_running、停止旗标未登记，run 会照常跑完」，既有缓解只覆盖状态一致（marker discarded 时不写 completed、不盲隔离产物），成本与墙钟空耗被留白。本设计即补此留白。

## D2 改动点

- A 取消旗标跨 attempt 生效（runner.py:733-747）：not_running 分支改为按 base_id 登记旗标（复用 add-run-cancel 的 _normalize_run_id 归一化、_cancel_requested 幂等集合与 reason/by 元数据）后返回；返回值保留 status=not_running、附 flag_registered 字段。复活 attempt 的启动守卫（_attempt_top_guards，runner.py:3222 附近）已逐 attempt 查旗标，零新增轮询；run 收尾 _cancel_clear 幂等清理已有，无泄漏风险。
- B retry 让位（runner.py:3151-3165 附近）：in-place retry 重派前对 planner-plan 增查并行出题标记 status 为 discarded 或 quarantined 即放弃。runner 不依赖 pm_engine——沿 result_gate 的注入约定新增标记读取回调（缺省 None 时视为无标记、行为不变），engine 侧装配时注入既有 _read_parallel_plan_marker。
- C 停滞预算（runner.py:4121-4127 采样点旁）：latency_state 已逐轮累积往返时长，采样点旁判停。判据：run 内连续 N 次以上达到 120 秒的往返，或 stall 占比达到一半且超过 M 分钟无产物 mtime 进展（产物路径取 run 既有 results 约定）；开关与 N、M 经 ConfigLoader.get 点号键 agents.run_stall_budget_enabled、agents.run_stall_budget_stalls、agents.run_stall_budget_window_minutes 读取，core/config.py 规范化，缺省关闭。触发走既有 attempt 终止与清理路径，终态日志记录命中判据；不新增 admin 告警，离群沿 add-self-review-midflight-signals 既有日汇总浮现。

## D3 权衡与风险

- 不改仲裁本身：隔离加转串行决策正确（对照 09-24 fix-quality-gates 取消命中活跃 attempt 正常终止，fenixd.log:18319-18322），缺口只在旗标登记与让位判据，修小不修大。
- 绝对次数单一阈值被否决：本次成功的串行 run 本身 stalls=11（fenixd.log:23931），「达到 8 次即 abort」会把慢 provider 下的正常 run 杀掉重跑，把止损变成浪费放大器；故判据必须复合且缺省关闭灰度。
- 兼容性：A 不改 not_running 返回语义、不改活跃 attempt 终止路径；B 仅对 planner-plan 且标记终态为 discarded 或 quarantined 时生效，在途或无标记时零影响；C 缺省关闭，存量测试零感知。
- 验收口径：守卫测试进程内装配，断言两条路径（attempt 间隙取消拦截复活 attempt；discarded 下 retry 让位），加判据单元测试（命中、不命中、缺省关闭、非法配置回退）。
