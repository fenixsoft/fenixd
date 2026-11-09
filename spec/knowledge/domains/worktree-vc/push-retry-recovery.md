<!-- knowledge: capability=push-retry-recovery rev=1 sources=spec/changes/fix-push-credential-env-and-retry-rearm -->

# done 态推送退避续推

done 态推送失败进入退避后的自动续推：event_bus 周期扫描的 done 分支即退避到期重试的消费通道，跨 daemon 重启天然存活。推送引用与退避级数语义见 [推送引用生命周期卫生](push-ref-hygiene.md)。

## 现行规则

- 周期扫描即消费通道：`_recover_one` 的 done 分支对 status==done 的 spec，当且仅当同时满足①不在推送退避期（`_is_push_backoffed` 为 False）②连续失败计数 < `pm.push.max_retries`（默认 3）③未处于耗尽升级终局（push_failed 困境信号已发）时，投递 `approve_push` 续推；退避期内记 debug 级跳过、下一轮扫描重判。不引入推送专用内存定时器——周期扫描即通道，退避字段已持久化 STATE，daemon 重启后首轮扫描照常拾取（最坏延迟一个扫描周期，退避窗分钟级可接受）。
- 四重门防误推：status==done（pushed 不进分支）+ 退避门 + 重试计数门 + 耗尽升级门；`approve_push` 内部再有单飞锁、pushed 幂等跳过、远端 SHA 去重兜底。耗尽终局判定落在 spec STATE 可读面——error 文本含 `[push_failed` 升级标记或计数 ≥ `max_retries`，任一命中即跳过，不查询 admin store。耗尽后维持人工收敛出口（/fenix-approve 或修凭证后手动重推），不自动死循环。
- 语义复用边界：退避级数 `pm.push.retry_backoff_seconds` 与升级阈值语义不变；退避/计数读侧复用 `ReportBuilder._is_push_backoffed` / `_get_push_retry_count` 单点，不裸解析 error 文本；续推不新增任何推送语义。
- 非阻塞投递：续推经既有 admin executor（`_admin_executor`，fenixd 启动序列事后挂载到 event_bus）异步投递，形态对齐 `_check_approve_push_requests`（submit + submitted 计数 + RuntimeError 回滚）；executor 为 None（未挂载 / `admin.workers=0`）时 fail-open——当轮 WARNING 跳过、下一轮重判，不内联同步调用（扫描主循环不承担 120s git 超时）；投递失败不中断整轮扫描。

## 代码锚点

- 主实现：`core/event_bus.py` `_recover_one` done 分支 + `_recover_done_push_retry`
- 复用面：`core/pm_engine/engine.py` `approve_push`（单飞锁 / pushed 幂等 / SHA 去重）；`core/pm_engine/reporting.py` `_is_push_backoffed` / `_get_push_retry_count`（读侧单点）；`fenixd.py` 启动序列 executor 挂载与 `_check_approve_push_requests`（投递形态参照）

## 溯源

- 2026-11-09 fix-push-credential-env-and-retry-rearm（spec/changes/fix-push-credential-env-and-retry-rearm/） — 新增本能力：_recover_one done 分支周期扫描续推（退避门/计数门/耗尽终局门 + admin executor 非阻塞投递）。动因实测：退避字段写盘后无消费通道，gaming-uplink-1080p 滞留 done 4 小时需人工 /fenix-approve 救回
