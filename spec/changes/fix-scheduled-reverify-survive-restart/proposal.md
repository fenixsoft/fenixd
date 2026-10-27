## Why

add-command-center 监视期实证（2026-10-27 17:58）：judge 修复预算耗尽排程了 18:22:58 重验，但三个治理 SPEC pushed 触发 restart_request → daemon 重启，新 daemon 全扫恢复路径见「testing + tester_run=null + 在飞 run 已归档」，把**合法等待排程重验的 testing 态**误判为中断孤儿态，重置成 implemented（error="Recovered from interrupted state: testing"），排程重验被作废——验证链输入被静默替换，还额外烧了一轮 stage2。

## What Changes

- 排程重验的结构化状态落 STATE 持久字段（排程时间戳 + 来源信号），不再只存在于 error 文本与进程内存
- daemon 恢复路径（"Recovered from interrupted state" 产生点）识别「存在未到期排程重验」的 testing 态为**合法等待态**：不重置、保持 testing，到期由周期扫描触发重验；重启后调度到点仍可执行（调度读 STATE 字段，不依赖内存定时器）
- 恢复路径的孤儿态判定提示文案同步：排程等待态不再落入「Recovered from interrupted state」

## Capabilities

### New Capabilities
- `scheduled-reverify-restart-durability`: 排程重验状态持久化且跨 daemon 重启存活——恢复路径不吞等待态，到点重验不依赖内存调度

### Modified Capabilities

## Impact

- `core/pm_engine/verification/escalation.py`：排程重验写入结构化字段（`_escalate_scenario_repair_exhausted` 一带，现有排程只进 error 文本与告警）
- 恢复路径产生点（"Recovered from interrupted state: testing" 的实现处，`grep` 定位，pm_engine/daemon 全扫恢复段）：孤儿态判定前置排程等待检查
- 排程消费点（周期扫描触发重验的既有机制，若为内存定时器则改读 STATE 字段）
- 新增 `tests/test_scheduled_reverify_restart.py`
