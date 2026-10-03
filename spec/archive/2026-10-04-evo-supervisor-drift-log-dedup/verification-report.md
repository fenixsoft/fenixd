# 验证报告：evo-supervisor-drift-log-dedup

> ⚠️ 本报告由框架于 2026-09-26T04:15:27Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。
> 报告时效标记（判定本报告是否属上一轮）：合成源轮次指纹：report.json@2026-09-26T04:15:27.207987+00:00

## 结论：✅ 通过（verified）

**状态：verified — 10/10 场景通过，0 失败，0 错误（全部场景通过）**

全绿快道: 10/10 场景通过、0 失败 0 警告——无分类对象，跳过 judge 机械 verified

| 指标 | 数量 |
| --- | --- |
| 通过 | 10 |
| 失败 | 0 |
| 错误 | 0 |
| 产品 Bug | 0 |
| 本链增量 Token（输入） | 1.46M |
| 本链增量 Token（输出） | 0.04M |


## 场景结果

| 场景 | 描述 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- | --- |
| dedup-constant-declared | 常量声明：fenixd.py 模块常量区新增 SUPERVISOR_LOG_DEDUP_MINUTES=60（与 STALE_ALERT_DEDUP_MINUTES 同层声明，tasks 1.1，落点参照 fenixd.py:157 附近） | pass | 0/2 | - |
| dedup-unit-tests-green | 单元测试三例全绿：tests/test_supervisor_drift_log_dedup.py 覆盖窗口命中跳过、超窗成条并写入去重标记、admin_store 缺失降级追加（tasks 2.1） | pass | 0/2 | - |
| dedup-stale-dedup-regression | 范围限定回归：stale_code 通道既有去重行为不变（R5），既有测试 tests/test_stale_code_selfheal.py（覆盖含 STALE_ALERT_DEDUP_MINUTES 窗口去重的通道）仍全绿 | pass | 0/2 | - |
| dedup-first-cycle-appends-and-marker | 首次成条：空去重状态下触发 supervisor 漂移警告，PROJECT_LOG 照常成条一条，且同步写入 kind=escalation、signal_type=supervisor_runtime_drift、severity=warning 的去重标记并写入即 mark_handled（不进人工队列）（R3；检查方法 fenixd.py:3698，追加循环 fenixd.py:3826 附近）。探针在临时目录装配真实 AdminStore 与真实 _append_project_log 落盘验证。 | pass | 0/6 | - |
| dedup-window-hit-skips-append | 窗口命中跳过：admin_alerts.json 已有窗口内（<60 分钟）supervisor_runtime_drift 标记时再次执行检查，跳过 PROJECT_LOG 追加（漂移告警不重复成条），并以 logger.info 留痕抑制说明不静默（R1+R2；判定复用 latest_signal 冷却查询 core/admin_store.py:485） | pass | 0/3 | - |
| dedup-expired-window-appends-again | 超窗成条：预置去重标记的 created 改为 2 小时前（超出 60 分钟窗口）后再次检查，PROJECT_LOG 照常成条新一条漂移告警，并刷新写入窗口内的新去重标记（proposal 验收：超窗后新周期照常成条；窗口锚点语义见 core/admin_store.py:485 latest_signal） | pass | 0/3 | - |
| dedup-consecutive-restarts-one-entry | 连续重启只落一条：模拟窗口内连续 3 次 daemon 重启（共享持久 admin_alerts.json 状态反复执行启动自检），PROJECT_LOG 只出现一条同因 supervisor 漂移告警（proposal 验收主场景） | pass | 0/3 | - |
| dedup-no-admin-store-degraded | 降级路径一：admin_store 为 None 时执行检查不崩溃，supervisor 漂移告警照常追加 PROJECT_LOG（等价现状行为，不因去重机制丢日志）（R4；design 机制 3） | pass | 0/2 | - |
| dedup-admin-store-error-degraded | 降级路径二：admin_store.latest_signal 读取抛异常时执行检查不崩溃，漂移告警照常追加 PROJECT_LOG（读写异常降级，不因去重机制引入启动失败或静默丢日志）（R4；design 机制 3） | pass | 0/2 | - |
| dedup-scope-supervisor-missing-untouched | 范围限定：supervisor_missing 路径不受新窗口去重影响（R5）——预置窗口内 supervisor_runtime_drift 标记且 supervisor 进程缺失时，A 分支「未受 supervisor 托管」告警仍照常落 PROJECT_LOG 并写入 supervisor_missing escalation（既有 unhandled_for 去重不变，源码 fenixd.py:3717-3756 附近），B 分支漂移告警被窗口去重跳过 | pass | 0/4 | - |
