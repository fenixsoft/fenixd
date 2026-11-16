<!-- knowledge: capability=push-retry-recovery rev=2 sources=spec/changes/fix-push-credential-env-and-retry-rearm,spec/changes/evo-add-push-git-env-precheck -->

# done 态推送退避续推

done 态推送失败进入退避后的自动续推：event_bus 周期扫描的 done 分支即退避到期重试的消费通道，跨 daemon 重启天然存活。推送引用与退避级数语义见 [推送引用生命周期卫生](push-ref-hygiene.md)，N/A 终局门与审批门语义见 [推送 git 环境预检与 N/A 短路](push-git-env-precheck.md)。

## 现行规则

- 周期扫描即消费通道：`_recover_one` 的 done 分支对 status==done 的 spec，先过预检 N/A 终局门与审批门（见六重门条，前置短路），再当且仅当同时满足①不在推送退避期（`_is_push_backoffed` 为 False）②连续失败计数 < `pm.push.max_retries`（默认 3）③未处于耗尽升级终局（push_failed 困境信号已发）时，投递 `approve_push` 续推；退避期内记 debug 级跳过、下一轮扫描重判。不引入推送专用内存定时器——周期扫描即通道，退避字段已持久化 STATE，daemon 重启后首轮扫描照常拾取（最坏延迟一个扫描周期，退避窗分钟级可接受）。
- 六重门防误推（N/A 终局门与审批门置于既有门序之前短路，省无效投递）：①N/A 终局门——entry 已含 push=N/A 专用持久字段即终局跳过（跨重启幂等：零重投递、不推进重试计数、零新失败记录）②审批门——`get_approve_mode` 生效 manual（含配置缺省回退）且零推送记账（push_attempts / 退避字段双源皆缺，即未经人工批准）则不自动补投；有记账的 manual spec 放行（有记账=人工已批准推送的退避重试，与人工批准后的续推兼容）③status==done（pushed 不进分支）④退避门⑤重试计数门⑥耗尽升级门；`approve_push` 内部再有单飞锁、pushed 幂等跳过、远端 SHA 去重兜底。耗尽终局判定落在 spec STATE 可读面——error 文本含 `[push_failed` 升级标记或计数 ≥ `max_retries`，任一命中即跳过，不查询 admin store。耗尽后维持人工收敛出口（/fenix-approve 或修凭证后手动重推），不自动死循环。
- 语义复用边界：退避级数 `pm.push.retry_backoff_seconds` 与升级阈值语义不变；退避/计数读侧复用 `ReportBuilder._is_push_backoffed` / `_get_push_retry_count` 单点，不裸解析 error 文本；续推不新增任何推送语义。
- 非阻塞投递：续推经既有 admin executor（`_admin_executor`，fenixd 启动序列事后挂载到 event_bus）异步投递，形态对齐 `_check_approve_push_requests`（submit + submitted 计数 + RuntimeError 回滚）；executor 为 None（未挂载 / `admin.workers=0`）时 fail-open——当轮 WARNING 跳过、下一轮重判，不内联同步调用（扫描主循环不承担 120s git 超时）；投递失败不中断整轮扫描。

## 代码锚点

- 主实现：`core/event_bus.py` `_recover_one` done 分支 + `_recover_done_push_retry`
- 复用面：`core/pm_engine/engine.py` `approve_push`（单飞锁 / pushed 幂等 / SHA 去重）；`core/pm_engine/reporting.py` `_is_push_backoffed` / `_get_push_retry_count`（读侧单点）；`fenixd.py` 启动序列 executor 挂载与 `_check_approve_push_requests`（投递形态参照）

## 溯源

- 2026-11-09 fix-push-credential-env-and-retry-rearm（spec/changes/fix-push-credential-env-and-retry-rearm/） — 新增本能力：_recover_one done 分支周期扫描续推（退避门/计数门/耗尽终局门 + admin executor 非阻塞投递）。动因实测：退避字段写盘后无消费通道，gaming-uplink-1080p 滞留 done 4 小时需人工 /fenix-approve 救回
- 2026-11-16 evo-add-push-git-env-precheck（spec/changes/evo-add-push-git-env-precheck/） — 门序由四重扩为六重：前置 N/A 终局门（push=N/A 持久字段即终局跳过）与审批门（approve_mode=manual 且零推送记账不自动补投，防续推绕过人工审批），门语义细节随新增能力页 push-git-env-precheck
