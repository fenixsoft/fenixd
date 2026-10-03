# verify-dispatch-single-flight 规格

## ADDED Requirements

### Requirement: verify 车道同 spec 单飞
验证车道 SHALL 按 spec 单键维护在飞集合，重复入队 SHALL 被拒绝并留痕；守卫 SHALL 覆盖全部入队路径。

#### Scenario: 双路入队被拒
- **WHEN** 同一 spec 已有在飞验证 run，第二路经任一路径（spec_implemented 事件、repair 链尾段、admin 复位直通道）入队
- **THEN** 拒绝并记录留痕，不产生第二个并发验证 run

#### Scenario: 在飞结束后放行
- **WHEN** 在飞验证 run 收工（成功或失败）后同 spec 再次入队
- **THEN** 正常派发，单飞守卫不阻塞合法重验

### Requirement: prepare 并发护栏
验证契约 prepare 步骤 SHALL 对共享构建目录的并发执行具备互斥或隔离。

#### Scenario: 并发 prepare 不互踩
- **WHEN** 两个验证 run 对同一主树并发执行 prepare（构建/clean 类步骤）
- **THEN** 经主机级锁串行化或使用隔离构建目录，不出现并发擦除导致的伪失败

### Requirement: 碰撞退避预算自适应
worktree 锁碰撞退避 SHALL 参考锁持有时长自适应预算，不再固定序列耗尽即放弃。

#### Scenario: 锁龄超固定预算
- **WHEN** 碰撞时锁已持有远超固定退避总预算（如 peer run 预计数百秒）
- **THEN** 在自适应上限内继续等待或超封顶快速放弃并结构化留痕

### Requirement: 碰撞不直接降级 legacy
新验证流程 SHALL 对 worktree 竞争类失败先重试新流程一次，仍失败才降级旧版 verifier。

#### Scenario: 竞争类异常处置
- **WHEN** 验证管线因 worktree 竞争（gave up: parallel run or manual freeze）失败
- **THEN** 先重试新流程一次；仍失败才降级 legacy，并保留降级计数与 degrade_context