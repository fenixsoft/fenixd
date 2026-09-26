## 能力：supervisor 漂移告警 PROJECT_LOG 追加窗口去重

### R1 窗口去重

daemon 启动自检的 supervisor drain 一致性检查在向 PROJECT_LOG 追加告警（_append_project_log 调用点）前，必须先做窗口去重判定：以 admin 告警存储为去重状态源，窗口时长 SUPERVISOR_LOG_DEDUP_MINUTES（默认 60 分钟）内已存在同键（supervisor runtime 异常族，signal_type=supervisor_runtime_drift）记录时，跳过本次追加。

### R2 抑制留痕

去重命中时不得静默：必须写一条框架日志（logger.info 级）说明「窗口去重命中、跳过 PROJECT_LOG 追加」及命中键。

### R3 去重状态跨重启存活

首次追加告警时同步写入一条去重标记记录（kind=escalation、severity=warning、写入即自动 mark_handled、不进人工告警队列），使后续重启的窗口判定能命中；去重按 signal_type 键判定，不逐字匹配告警文案（文案含运行时数值，跨重启会漂移）。

### R4 降级路径

admin_store 不可用（None 或读写异常）时降级为照常追加（等价现状行为），不得因去重机制本身造成告警丢失或启动失败。

### R5 范围限定

仅覆盖 supervisor drain 一致性检查（drain 一致性警告路径）的 PROJECT_LOG 追加；supervisor_missing 路径已有 unhandled_for 去重、stale_code 通道已有窗口去重，均不变更。