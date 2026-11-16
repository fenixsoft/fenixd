# Proposal: unfreeze-retry-counter-reset

## Why

解冻与管理复位路径不清零调度重试计数 _retry_count：unfreeze_spec（core/state_machine.py:2543-2790）清零集清 20+ 计数键但不含该键，dashboard 管理复位集 _RETRY_COUNTER_RESETS（core/dashboard/data/admin_actions.py:1745-1781）同样不含。解冻本意是给 spec 新的完整重试预算，实际却保留旧计数——解冻后首轮失败立即 bump 到 N+1 并因 retries >= max_r 立即再冻结。

后果已量化（2026-11-08~11-10，cloud-phone 项目）：越限形态全日志 8 起（5×4/3、1×5/3、2×6/3），横跨 5 个 spec 与 full/fast-track 双车道，single-app-realdevice-retest 在 50 分钟内 4/3→5/3→6/3 连环冻结；client-ui-redesign 11-10 的第 4 轮为真实 run（约 1h45m），完成后被人工裁决弃用；fast-track 连环冻结烧掉 arbiter 复现配额。同型缺陷已有先例：2026-11-10-fix-unfreeze-judge-counter-reset 修过同一清零集的 judge 两键，_retry_count 是其未覆盖的兄弟键。

附带两处记账缺陷一并修复：①冻结给人工的 error 文案硬编码「{max_r}/{max_r} 轮」，实际计数 4/3 时仍显示 3/3，误导裁决；②m0 push 侧「4/3」实为人工重推（lead-manual-repush-3）被计入与自动重试同一计数器——approve_push 前置门（core/pm_engine/engine.py:3387）只查 status/退避窗、无上限门，且达上限后重复 push_failed 信号触发 daemon_errors 升级噪音（自动重试上限本身在 3/3 正确收敛，未被破坏）。

## What Changes

- **清零集补键（core/state_machine.py）**：unfreeze_spec 清零集补 _retry_count，解冻后重试预算从零起算。
- **管理复位补键（core/dashboard/data/admin_actions.py）**：_RETRY_COUNTER_RESETS 补 _retry_count: 0（同文件已有同键复位先例）。
- **冻结文案取真实计数（core/pm_engine/dispatch/queue.py、core/pm_engine/dispatch/fast_track.py）**：冻结陈述中的 used 取自真实计数而非硬编码上限。
- **人工重推记账（core/pm_engine/engine.py）**：approve_push 人工重推计入 push 重试计数时标注来源；计数达上限后重复 push_failed 信号去重，不再重复触发 daemon_errors 升级。
- **单测**：覆盖解冻后首轮失败计数从 1 起算、复位键集合含 _retry_count、越限文案计数一致性、人工重推去重。

## Capabilities

### dispatch-retry-accounting

见 specs/dispatch-retry-accounting/spec.md。

## Impact

- core/state_machine.py 与 core/dashboard/data/admin_actions.py 各扩一个清零键（对齐 2026-11-10 judge 两键先例的做法）。
- core/pm_engine/dispatch/queue.py、fast_track.py 冻结文案数据来源变更（不改冻结判定逻辑）。
- core/pm_engine/engine.py approve_push 增加来源标注与信号去重（不改人工重推放行语义）。