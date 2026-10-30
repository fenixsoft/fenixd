## Why

add-command-center 监视期实证（2026-10-27 17:58）：judge 修复预算耗尽排程了 18:22:58 重验，但三个治理 SPEC pushed 触发 restart_request → daemon 重启，新 daemon 全扫恢复路径见「testing + tester_run=null + 在飞 run 已归档」，把**合法等待排程重验的 testing 态**误判为中断孤儿态，重置成 implemented（error="Recovered from interrupted state: testing"），排程重验被作废——验证链输入被静默替换，还额外烧了一轮 stage2。

## What Changes

- 排程重验补齐来源标记结构化字段（`_reverify_pending`/`_reverify_reason`），与既有截止字段 `_dispatch_backoff_until`（排程动作已写 STATE，escalation.py `_schedule_scenario_repair_reverify`）同一原子写落盘；截止时刻单源复用 `_dispatch_backoff_until`，MUST NOT 另立第二截止字段
- daemon 恢复路径（"Recovered from interrupted state" 产生点）识别「存在未到期排程重验」的 testing 态为**合法等待态**：不重置、保持 testing，到期由周期扫描触发重验；重启后调度到点仍可执行（调度读 STATE 字段，不依赖内存定时器）
- 恢复路径的孤儿态判定提示文案同步：排程等待态不再落入「Recovered from interrupted state」

## Capabilities

### New Capabilities
- `scheduled-reverify-restart-durability`: 排程重验状态持久化且跨 daemon 重启存活——恢复路径不吞等待态，到点重验不依赖内存调度

### Modified Capabilities

## Impact

- `core/pm_engine/verification/escalation.py`：`_schedule_scenario_repair_reverify`（escalation.py:2554 起，由 pipeline.py 首次耗尽分支调用；注意不是 `_escalate_scenario_repair_exhausted`——那是二次耗尽升级人工通道，不排程）同原子写补 `_reverify_pending`/`_reverify_reason`；现状截止时刻已有 `_dispatch_backoff_until` 落 STATE（escalation.py:2667-2676），缺的是来源标记与恢复路径识别
- `core/state_machine.py` 全扫恢复路径（"Recovered from interrupted state: testing" 产生点，TESTING 分支重置 implemented 处，约 3329-3342 行）：孤儿态判定前置排程等待检查（同型先例：event_bus `_ready_hold_blocks` 已对 ready 恢复做「有意等待早退」）
- 排程消费点零新增：复用既有 `event_bus._recover_testing` 周期扫描兜底（escalation.py:43-48 头注明示该设计；到期经 `spec_is_undriven` 条件③ 出窗拾起），预期该文件零改动
- 新增 `tests/test_scheduled_reverify_restart.py`
