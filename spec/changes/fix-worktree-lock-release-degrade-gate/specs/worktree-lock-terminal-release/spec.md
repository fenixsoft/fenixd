## ADDED Requirements

### Requirement: run 终态释放 worktree spec 锁

worktree spec 锁（`spec:agent_type`）记录 MUST 携带 owner run 归属（run_id）。run 到达终态（superseded、error、failed、frozen-terminated 等非成功终态）收尾时，框架 MUST 释放该 run 持有的对应锁；释放后同 spec 同 agent_type 的派发 MUST 可立即正常 acquire。

#### Scenario: supersede 后锁即时释放
- **WHEN** 一个持有 spec:agent_type 锁的 planner-plan run 被 superseded（终态收尾完成）
- **THEN** 该锁立即释放，同 spec 同 agent_type 的新派发可正常 acquire 并创建 worktree，不出现「already active」早退

#### Scenario: 终态释放不误放他人锁
- **WHEN** 终态 run 请求释放的锁的 owner run 归属与自身不符（锁已被其他 run 持有）
- **THEN** 释放调用为 no-op 并落 DEBUG 留痕，他人持有的锁不受影响

### Requirement: acquire 陈锁存活清扫

acquire 因「already active」早退前，MUST 核对持锁 run 存活性：确认死亡（run 记录含终态行，或派发方进程已不存活）时 MUST 清扫陈锁（discard + WARNING 留痕）并继续本次 acquire，MUST NOT 直接放弃。存活判据不确定时 MUST 保持既有早退行为（宁可慢清扫不可错杀活锁）。

#### Scenario: 死锁主陈锁清扫放行
- **WHEN** 锁龄超过 early give-up 上限且持锁 run 记录已含终态行（或进程不存活）
- **THEN** acquire 清扫陈锁并正常放行本次派发，日志含清扫 WARNING

#### Scenario: 存活持锁主维持早退
- **WHEN** 持锁 run 确认仍在飞（记录无终态且进程存活）
- **THEN** acquire 维持既有 adaptive backoff early give-up 行为，不清扫、不错杀
