# transient-dispatch-gating — 瞬断终态排程重派与全局熔断

## ADDED Requirements

### Requirement: transient 终态排程等待重派

dispatch 层处理 implementer/fast-track/repair 的失败收场时，若错误带 `[provider-transient]` 标记，MUST 跳过现行「`_retry_count` 递增/清零 + 立即重新入队」路径，改为按 `agents.transient_redispatch_delay_seconds`（缺省 600）排程恢复定时器，到期重新进入派发流程；死亡 run 预算豁免行为保持不变。

#### Scenario: transient 终态延迟重派

- **GIVEN** 某 implementer run 终态 error 带 `[provider-transient]` 标记
- **WHEN** dispatch worker 处理该失败
- **THEN** 不立即入队、不写 `retries exhausted`；600 秒后该 spec 重新进入派发；重派经 worktree 复用通道认领前一轮现场

#### Scenario: 非 transient 终态路径不变

- **GIVEN** 某 run 终态 error 不带 `[provider-transient]` 标记
- **WHEN** dispatch worker 处理该失败
- **THEN** 现行重试计数/清零/重入队行为逐字节不变

### Requirement: 全局同错误指纹熔断

runner 维护全局维度的瞬断错误指纹计数：错误文本经归一化（剥离 model 名等可变字段）生成指纹，在 `agents.transient_break_window_seconds`（缺省 600）滑动窗口内同一指纹出现次数达 `agents.transient_break_threshold`（缺省 3）时触发熔断——冻结全部新 run 派发 `agents.transient_break_cooldown_seconds`（缺省 600），并发出带节流的 major 告警。计数与熔断状态保存在进程内存（与既有 4xx 熔断同构，daemon 重启清零）。

#### Scenario: 风暴触发全局熔断

- **GIVEN** 600 秒窗口内 3 个不同 spec 的 run 均以 unrecognized_model 指纹死亡
- **WHEN** 第 3 次失败被记账
- **THEN** 触发全局熔断：派发闸门拒绝一切新 run 启动 600 秒，发出 major 告警（15 分钟 throttle），在飞 run 不受影响

#### Scenario: 熔断冷却解除

- **GIVEN** 熔断生效中且冷却时长已过
- **WHEN** 派发闸门被查询
- **THEN** 恢复正常派发；窗口内指纹计数清零重新起算
