# push-retry-recovery Specification

## ADDED Requirements

### Requirement: done 态退避续推消费通道

`event_bus._recover_one` SHALL 增加 done 分支：对 status==done 的 spec，当且仅当**同时**满足①不在推送退避期内（`_is_push_backoffed` 为 False）②连续失败计数 `_get_push_retry_count` < `pm.push.max_retries` ③未处于推送耗尽升级（push_failed 困境信号已发）终局态，周期扫描 SHALL 经既有 admin executor 非阻塞投递 `pm_engine.approve_push(spec_name)` 续推；退避期内记 debug 级跳过日志。续推 MUST 复用 approve_push 既有单飞锁、pushed 幂等跳过、远端 SHA 去重，MUST NOT 新增任何推送语义或内存定时器——周期扫描即消费通道，跨 daemon 重启天然存活。

#### Scenario: 退避到期后自动续推
- **WHEN** spec 处于 done、`_push_backoff_next_retry_at` 已过期、重试计数 1/3
- **THEN** 下一轮周期扫描投递 approve_push 续推，推送成功后状态推进 pushed 并清除 error 残痕，全程无人工介入

#### Scenario: daemon 重启后退避续推恢复
- **WHEN** daemon 在推送退避期内重启（退避字段已持久化 STATE），重启后首轮周期扫描时退避已到期
- **THEN** done 分支照常拾取并续推（退避字段跨重启存活、消费不依赖进程内定时器），spec 不滞留 done

### Requirement: 退避门与耗尽收敛不破坏

done 分支 MUST NOT 绕过既有推送收敛语义：退避期内（`next_retry > now`）MUST 跳过续推等待下一轮扫描；`_get_push_retry_count` 已达 `pm.push.max_retries`（默认 3）且 push_failed 困境信号已发的 spec MUST 停止自动续推（维持人工收敛出口）；`pm.push.retry_backoff_seconds` 级数与升级阈值语义不变。

#### Scenario: 退避期内扫描跳过
- **WHEN** spec 处于 done 且 `_is_push_backoffed` 为 True（next_retry 未到）
- **THEN** 本轮扫描记 debug 级跳过日志，不发 push 命令、不推进状态，下一轮扫描重判

#### Scenario: 耗尽升级后不再自动续推
- **WHEN** spec 连续推送失败 3 次（max_retries=3），push_failed 困境信号已发
- **THEN** 周期扫描不再对该 spec 自动续推（防死循环烧凭证），spec 停留 done 等待人工处置（/fenix-approve 或修凭证后手动重推）

### Requirement: 续推非阻塞投递

done 分支的续推投递 MUST 经既有 admin executor（fenixd `_admin_executor`）异步执行，形态对齐 fenixd.py `_check_approve_push_requests` 既有投递（submit + submitted 计数 + RuntimeError 回滚）；executor 引用由 fenixd.py 启动序列事后挂载到 event_bus（同 `code_fix_orchestrator` 装配契约），event_bus 侧 `getattr(self, "_admin_executor", None)` fail-open——executor 为 None（未挂载 / `admin.workers=0`）时 MUST NOT 内联同步调用，当轮记 WARNING 跳过、下一轮扫描重判。耗尽升级终局（push_failed 已发）的判定 MUST 落在 spec STATE 可读面：error 文本含 `[push_failed` 升级标记或 `_get_push_retry_count >= pm.push.max_retries`，任一命中即跳过，MUST NOT 查询 admin store。退避门与计数门 MUST 复用 `ReportBuilder._is_push_backoffed` / `_get_push_retry_count` 单点读侧，MUST NOT 裸解析 error 文本。MUST NOT 在周期扫描主循环内联等待 git push（120s 超时）阻塞其它信号车道；executor 拒绝（RuntimeError）时按既有车道口径降级（WARNING 留痕），MUST NOT 因投递失败中断整轮扫描。

#### Scenario: 续推不阻塞扫描主循环
- **WHEN** 周期扫描同时命中多个 done 态待续推 spec
- **THEN** 各续推经 executor 异步投递（单飞锁去重并发），扫描主循环当轮完成不等待 git 子进程，其它 spec 的恢复动作不受延迟
