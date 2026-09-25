# proposal: add-run-stop-loss

## Why

2026-09-25 add-regression-auto-fix 出题阶段事故（fenixd.log:23707-23937）：并行 planner run 的 attempt 1 于 12:21:59 退出（exit 0 但 test_scenarios.json 缺失，产物硬门拦截），testing 车道经 run 死检测判「半成品隔离」并调 cancel_run——取消恰好落在 attempt 间隙，cancel_run 走 not_running 分支不登记取消旗标（core/agent_runner/runner.py:733-747），30 秒后产物硬门 in-place retry 重派 -r1，让位判据不查并行出题 discarded 标记，run 复活再跑 36 分钟（101 轮）并与已转道的串行 run 并发双跑，run 级 cost_usd=7.705119 全部沉没（fenixd.log:23880-23881）；串行重出再耗 cost_usd=9.572714（同日 16 条 planner-plan 中位 $2.86 的 3.34 倍）。该竞窗是框架已自认的接受项：core/pm_engine/engine.py:1013-1015 注释明写「attempt 尚未注册时 cancel 落 not_running、停止旗标未登记，run 会照常跑完」，既有缓解（code-review item b4b98c69a4e1）只保状态一致（不写 completed、不误隔离产物），成本空耗被留白；同款「转串行重出」文案 09-22 至 09-25 已出现 5 次以上，属结构性复发路径。

## What Changes

run 级止损三件套，全部落在 run 生命周期内部、不改并行仲裁的隔离加转串行决策：

1. 取消旗标跨 attempt 生效：cancel_run 的 not_running 分支同样登记取消旗标（复用 add-run-cancel 既有 base_id 归一化与幂等基建），随后复活或重试的 attempt 在启动守卫处命中旗标即有序终止。
2. in-place retry 让位：attempt 重派前的让位判据对 planner-plan 增查并行出题标记 status 为 discarded 或 quarantined 即放弃重派（防御纵深，覆盖不经旗标的复活路径）。
3. 停滞预算（缺省关闭、配置灰度）：run 内复合判停判据（连续多次 120 秒级往返，或 stall 占比过高且长时间无产物进展），挂既有 latency 采样点，阈值经 agents.run_stall_budget_* 配置。

## Capabilities

### New Capabilities

- run-stop-loss: agent run 级止损——取消旗标跨 attempt 生效、in-place retry 让位隔离标记、停滞预算复合判停。

## Impact

- core/agent_runner/runner.py：cancel_run not_running 分支、retry 让位判据、latency 采样点旁判停。
- core/pm_engine/engine.py：装配侧注入并行出题标记读取回调。
- core/config.py：agents.run_stall_budget_* 键规范化。
- 并行仲裁（core/pm_engine/verification/pipeline.py）与串行转道派发链零改动；不新增 admin 告警（对齐告警降噪铁律），止损事件沿既有 run 级日志与自省日汇总浮现。
- 预期收益：本类事故每次省 30 分钟级空转与约 2 至 8 美元沉没成本，消除双跑对串行车道的 provider 争抢。
