<!-- knowledge: capability=inconclusive-loop-escalation rev=1 sources=spec/archive/2026-09-15-add-verdict-credibility-gate -->

# 无结论循环升级

连续 blocked-env（inconclusive）达到阈值时主动唤起 Administrator：不依赖 stuck/blocked_stuck/repeated_failures 任一既有检测规则。

## 现行规则

- `_handle_env_blocked_inconclusive` 的连续计数（`_inconclusive_attempts`，含暂停分支触发时刻）达到升级阈值 `verify_engine.inconclusive_escalate_attempts`（默认 4）时，向 admin store 写入待唤起 SIGNAL 记录（kind=SIGNAL，type=`inconclusive_loop`，含 spec 名、连续轮数、末轮 blocked_env 数、最近实例端口/探针摘要），由 admin_monitor 摄取后按既有 SIGNAL 通道唤起 Administrator（family_explosion/dispatch_stalled 同款路径）。
- 阈值内不提前唤起：连续轮数 1-3（重验与暂停的正常区间）不写入 SIGNAL，维持既有自动重验→暂停语义，不产生噪音告警。
- 处置建议指向环境核查：Administrator 因 inconclusive_loop 信号被唤起时，处置建议包含验证环境核查清单（实例就绪/资源与并行度/mock+SSE 链路/探针摘要）与恢复路径（人工处置后解冻并清 `_inconclusive_attempts`）。
- 人工处置后计数清零：人工清 `_inconclusive_attempts` 并使 spec 回到可调度态后，后续 blocked-env 轮次从 1 重新计数，不残留旧计数（与 unfreeze 清 verify_redo_count 同语义）。
- 阈值可配置：`verify_engine.inconclusive_escalate_attempts` 设为其他正整数 N 时，第 N 轮全批 blocked-env 触发 SIGNAL 写入。

## 溯源

- 2026-09-15 add-verdict-credibility-gate（spec/archive/2026-09-15-add-verdict-credibility-gate） — 确立连续 blocked-env 达阈值（默认 4）写 SIGNAL 唤起 Administrator、阈值内静默、环境核查处置建议与人工处置后计数清零
