## 背景

fenix-desktop 项目一条 ui-manual 请求型信号（verify_regression_missing，请求补写 .fenix/verify.yaml 的 regression 段）诉求在 55 分钟后即由提交满足，却因 daemon 停机 7.6 天挂到恢复后才被处置（跨 45 小时，处置 run admin-fenix-desktop-1790392534 于 09-26T03:19Z 判为陈旧信号）。核查确认：daemon 运行时摄取为分钟级（_admin_monitor_loop 周期 5 分钟）、alert_lifecycle 已有周期自动闭环，但存在两个真实缺口：(1) kind=signal 的请求型可探测信号不在自动闭环覆盖面内——daemon 恢复后仍会对诉求已被满足的信号白唤起一次 admin 处置 run（LLM 调用）；(2) 处置完成后无人回写信号 handled，原信号永挂未处理（AdminStore.mark_signal_handled 已实现，但 admin 处置自动链路上无调用方——现存调用仅 dashboard 人工 alert-resolve 闭环端点 core/dashboard/data/admin_alerts.py:57 与 core/dashboard/routes/alert_routes.py:289，属人工通道而非处置 run 的自动回写）。

## 目标

1. 摄取侧前置探测：对白名单内的可探测请求型信号，在升级唤起 Administrator 之前先做只读探测，诉求已满足即闭环（handled=true + resolved 处置留痕），免唤起。
2. 处置闭环回写：admin 处置 run 写入最终处置结果时，同步回写对应信号的 handled 状态。

## 方案要点

- 前置探测落点 core/admin_monitor.py 信号摄取循环 _detect_family_explosion：mark_escalated / 唤起之前对白名单 signal_type 执行只读探测。
- 白名单初始收录三种可探测类型：verify_regression_missing（verify.yaml regression 段存在性）、verify_contract_missing（验证契约存在性）、build_artifact_paths_missing（项目 config 产物路径配置存在性）。
- 探测异常时按原路径继续唤起（fail-open），不静默吞信号。
- 回写落点 core/agent_runner/maintenance_runs.py 处置结果写入处，调用既有 AdminStore.mark_signal_handled。

## 非目标

- 不改 alert_lifecycle 纯函数边界（其 design 约束不读写文件）。
- 不覆盖需语义判断的信号类型（manual-intervention、inconclusive_loop 等不入白名单）。
- 不做 daemon 停机监控/心跳外露（45 小时个案的教训主体，另立议题）。

## 验收

- 白名单信号在诉求已满足时被摄取：不唤起 Administrator、信号 handled=true、留有 result=resolved 的处置留痕注明「探测通过、诉求已满足、免唤起」。
- 诉求未满足或探测异常：照常唤起（现有路径不变）。
- 处置 run 终态写入后对应信号 handled=true。
- 单元测试覆盖上述四态。