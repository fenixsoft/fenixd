## 背景

2026-09-17~09-18，fenix-desktop 项目 daemon 因高频提交反复重启。每次重启时启动自检中的 supervisor drain 一致性检查（fenixd.py _check_supervisor_drain_consistency，仅启动时调用一次）都会把同一组 supervisor runtime 告警无条件追加进 .fenix/PROJECT_LOG.md：两天内「supervisor runtime 上报于 2026-09-17T09:23，早于本次 daemon 启动 86400s 以上」一条不差地重复出现 6 次，建议动作「重启 supervisor」始终无人执行。stale_code 告警通道已在 evo-fix-stale-code-alert-window-dedup（09-24 合入，commit 7ee7c59e）中加了 60 分钟跨重启窗口去重，但 supervisor 漂移这条 PROJECT_LOG 追加路径至今无任何去重。

## 目标

给 supervisor 漂移告警的 PROJECT_LOG 追加加一层跨重启窗口去重：窗口内同一 supervisor 异常状态只落一条日志，重复启动不再刷屏；抑制动作留框架日志可对账。

## 方案要点

- 对齐 stale_code 去重先例（fenixd.py:1160-1176）：写入前查 AdminStore.latest_signal，SUPERVISOR_LOG_DEDUP_MINUTES（默认 60 分钟）窗口内已有同键记录则跳过 PROJECT_LOG 追加、降级 logger.info 留痕；未命中则照常追加，并写入一条 warning 级、写入即自动 handled 的去重标记记录（不进人工队列），使去重状态跨重启存活。
- 新增模块常量 SUPERVISOR_LOG_DEDUP_MINUTES = 60，与 STALE_ALERT_DEDUP_MINUTES 同层声明。

## 非目标

- 不改漂移阈值 SUPERVISOR_RUNTIME_DRIFT_SECONDS（fenixd.py:95）与漂移判定本身。
- 不动 stale_code 通道既有去重与 supervisor_missing 路径既有的 unhandled_for 去重。
- 告警治理参数（多处模块常量）统一入 config 属另一方向（代码注释已预留），不在本 SPEC 展开。
- 不做 PROJECT_LOG 轮转机制。

## 验收

- 窗口内连续重启 daemon，PROJECT_LOG 只出现一条同因 supervisor 告警；超窗后新周期照常成条。
- admin_store 不可用时降级为照常追加（保持现状行为，不因去重机制引入静默丢日志）。
- 单元测试覆盖窗口命中跳过、超窗成条、降级追加三例。