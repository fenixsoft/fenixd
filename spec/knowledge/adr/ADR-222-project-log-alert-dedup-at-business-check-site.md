# ADR-222：PROJECT_LOG 告警去重落在业务检查点、状态承载 AdminStore

date: 2026-10-04
status: accepted

## Context

daemon 启动自检类告警（supervisor 排水一致性检查、stale_code 通道等）在生命周期快速轮换（高频提交反复重启 daemon）下，每次启动都重新产出同一组异常并无条件追加 PROJECT_LOG，同一告警可在数日内原样刷屏多次。需要一层跨重启生效的去重；承载与落点有多种可选：扫描 PROJECT_LOG 文本尾部按文案判定、把去重做进共享日志通道 `_append_project_log`、或以持久告警存储为状态源在产生告警的业务检查点判定。

## Decision

- PROJECT_LOG 追加级告警去重是产生告警的业务检查点语义，不是日志通道的通用语义：去重判定放在具体检查点写入前，不下沉进 `pm_engine._append_project_log`——该通道服务全部调用方，通道级去重语义过宽。
- 去重状态一律承载 AdminStore 持久告警存储：复用 `latest_signal` 窗口冷却查询，标记记录持久于 admin_alerts.json、天然跨 daemon 重启存活，不新增存储机制。禁扫描 PROJECT_LOG 文本判定——文案含运行时数值与时间格式、匹配脆弱，且 PROJECT_LOG 无锁并发追加不安全。
- 判定键为 signal_type 族级粗粒度，不逐字匹配告警文案；去重标记记录以 warning 级、写入即 mark_handled 的 escalation 落库，不进人工告警队列。
- 状态源不可用（存储缺失或读写异常）时降级为照常追加，去重机制不得引入静默丢日志或启动失败。

## Consequences

- 各告警路径的去重形态允许不一致（窗口去重、unhandled_for 去重、不去重并存），读者需逐路径确认；族级粗粒度窗口内并存的子类异常不单独成条——框架日志仍逐条可查，被抑制的只是 PROJECT_LOG 追加。
- 换取：高频重启下 PROJECT_LOG 不刷屏；去重零新增存储机制（标记记录同受既有环形裁剪管理）；stale_code 与 supervisor 漂移两条路径同构、后续新告警路径有现成先例可循。
