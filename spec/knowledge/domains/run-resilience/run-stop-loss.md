# run 级止损
<!-- knowledge: capability=run-stop-loss rev=1
     sources=spec/archive/2026-10-04-evo-add-run-stop-loss -->

agent run 生命周期内的成本止损三件套：attempt 间隙取消、in-place retry 让位隔离标记与停滞预算判停——让已被仲裁或管理面叫停、或注定无产出的 run 不再空耗 30 分钟级墙钟与美元级 provider 成本。取消原语本体（终止序列、hold-state、文件信号与界面入口）见 [run 取消](run-cancel.md)。

## 规则

- 取消旗标跨 attempt 生效：`cancel_run` 未命中活跃 attempt（not_running）时仍按归一化 base_run_id 登记取消旗标（幂等，含 reason/by 元数据），返回 `{"status": "not_running", "base_run_id", "flag_registered": true}`；随后由复活机制或 in-place retry 重派的 attempt 在启动守卫（`_attempt_top_guards`，逐 attempt 复查）命中旗标即有序终止、不再执行任何 provider 轮次。旗标键含 epoch、只拦本 run 的复活 attempt，run 收尾幂等清理不产生跨 run 泄漏。命中活跃 attempt 时沿用登记旗标加属主线程终止的既有路径，语义不变。
- in-place retry 让位隔离标记：产物硬门与瞬态重试共用的 in-place retry 重派前，对 planner-plan run 增查并行出题标记 `.fenix/verify-progress/<spec>/parallel_plan.json`，`status` 为 `discarded` 即放弃重派，run 以 cancelled 或 failure 收尾、串行转道不受影响。标记实际枚举 dispatched/failed/discarded/completed（无 quarantined 值）；消费侧产物隔离（重命名 `.parallel-discarded`）与 discarded 标记写入在同一收尾路径伴生发生，锚定 discarded 单值即同时覆盖「已隔离」与「已转串行」两类终态。
- 隔离标记读取走装配注入：runner 经构造注入的读取回调（PMEngine 装配侧注入，沿 result_gate 注入约定）取标记，agent_runner MUST NOT 引入对 pm_engine 的模块依赖；未注入（缺省 None）、读取异常、标记缺失或损坏一律按无标记处理（fail-open），不阻断正常重试。让位 gating 仅对 planner-plan 生效，其它 agent 类型不受 discarded 影响。
- 停滞预算复合判停（缺省关闭）：run 内停滞判停必须复合判据，MUST NOT 以绝对停滞次数为单一阈值——慢 provider 下正常成功的 run 本身可含多次超过 60 秒的往返。两条判据任一命中即判停：判据一 `consecutive_slow_rounds`，run 内连续 ≥N 次达到 120 秒的 API 往返；判据二 `stall_ratio_no_progress`，完成样本 ≥2 且 stall 占比达到一半，且超过 M 分钟无产物（run 转录）mtime 进展。
- 停滞预算配置三键：`agents.run_stall_budget_enabled`（缺省 false）、`agents.run_stall_budget_stalls`（N，缺省 5，正整数）、`agents.run_stall_budget_window_minutes`（M，缺省 10 分钟，正数，换算秒生效）。归一化单点 `ConfigLoader.get_run_stall_budget_config`，判停消费与设置展示同源；非法值回退缺省，配置读取异常 fail-open 为关闭（读失败不构成杀 run 的理由）。
- 判停统计 run 级累积：样本计数与判停状态的键为归一化 base_run_id（含 epoch），跨 attempt 与 in-place retry 重派的新 attempt 不重置预算；run 终态外口幂等摘除，建态时顺带淘汰超 24 小时的陈旧条目。采样旁挂流式循环既有 latency 采样点（reader 线程单写者），产物 mtime 进展由轮询环单写者更新。
- 命中处置终止整个重试链：强杀在飞 attempt（杀前先做 WIP checkpoint 保全），经 `RunStallBudgetExceededError` 专用通道收场——不重试、不计秒挂、不触发 provider 链切换，MUST NOT 再触发瞬态重试或 in-place retry 重派（止损被自动重派放大即失去意义）；run 以 `[run-stall-budget]` 前缀失败终态，终态日志记录命中判据与统计。不新增 admin 告警，止损事件沿既有 run 级日志与自省日汇总浮现。

## 溯源

- 2026-10-04 evo-add-run-stop-loss（spec/archive/2026-10-04-evo-add-run-stop-loss） — 新增 run 级止损三件套：cancel_run not_running 分支登记取消旗标拦复活 attempt、in-place retry 让位并行出题 discarded 标记（回调注入）、agents.run_stall_budget_* 复合判停缺省关闭
