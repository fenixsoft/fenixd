# 验证报告：evo-fix-stale-code-alert-window-dedup

> ⚠️ 本报告由框架于 2026-09-24T10:26:32Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。
> 报告时效标记（判定本报告是否属上一轮）：合成源轮次指纹：report.json@2026-09-24T10:26:32.468686+00:00

## 结论：✅ 通过（verified）

**状态：verified — 6/6 场景通过，0 失败，0 错误（全部场景通过）**

全绿快道: 6/6 场景通过、0 失败 0 警告——无分类对象，跳过 judge 机械 verified

| 指标 | 数量 |
| --- | --- |
| 通过 | 6 |
| 失败 | 0 |
| 错误 | 0 |
| 产品 Bug | 0 |
| 本链增量 Token（输入） | 0.91M |
| 本链增量 Token（输出） | 0.02M |


## 场景结果

| 场景 | 描述 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- | --- |
| dedup-constant-module-level-no-config | stale_code 告警窗口去重阈值以模块级常量 STALE_ALERT_DEDUP_MINUTES=60 存在于 fenixd 模块顶层，且未新增配置面（core/config.py 的 ConfigLoader 无 stale_alert_dedup 相关键/方法）——tasks 1.1 常量风格约定。出处：fenixd.py:114（常量定义）、core/config.py:110（ConfigLoader 类） | pass | 0/2 | - |
| dedup-within-window-no-duplicate | 窗口内重启不重复成条：daemon 重启后新进程再次假→真检测到陈旧，但持久化存储 60 分钟窗口内已有 stale_code 同信号记录——跳过写入降级为日志，admin_alerts.json 不新增同文条目（SPEC Scenario「窗口内重启不重复成条」）。出处：fenixd.py:1033-1042（latest_signal 窗口判定与去重日志）、fenixd.py:114（STALE_ALERT_DEDUP_MINUTES=60）、tests/test_stale_code_selfheal.py:182（test_within_window_no_duplicate_entry） | pass | 0/2 | - |
| dedup-beyond-window-writes-new-entry | 超窗新周期照常成条：距上次 stale_code 告警超过 60 分钟后再次进入陈旧态，照常写入新告警且写入即 mark_handled（warning 级不进人工队列）语义不变（SPEC Scenario「超窗新周期照常成条」）。出处：fenixd.py:1043-1073（append + mark_handled 写入路径）、tests/test_stale_code_selfheal.py:199（test_beyond_window_new_cycle_writes_new_entry，断言新条目 handled=True 且不走去重分支） | pass | 0/2 | - |
| dedup-empty-storage-first-report | 空存储首报不受影响：存储中无任何 stale_code 记录（admin_alerts.json 尚未落盘）时首次检测到陈旧，照常写入告警且写入即 mark_handled——空状态路径不被窗口去重吞掉（SPEC Scenario「首报不受影响」，既有首报断言保持通过）。出处：fenixd.py:1033-1035（latest_signal 空存储返回 None 落入 else 写入分支）、tests/test_stale_code_selfheal.py:217（test_empty_storage_first_report_unchanged） | pass | 0/2 | - |
| dedup-edge-trigger-regression | 既有边沿触发语义回归（tasks 1.2「保持假→真边沿触发与写入即 mark_handled 语义不变」）：首报写入告警、持续陈旧不重复告警不刷 WARNING、真→假状态解除不产生新告警仅记日志——窗口去重插入点不得破坏原三态边沿行为。出处：fenixd.py:1014-1024（边沿判定与 WARNING）、tests/test_stale_code_selfheal.py:84-144（TestStaleStatePersistence 三用例） | pass | 0/4 | - |
| dedup-full-file-regression | 回归点：tests/test_stale_code_selfheal.py 整文件 30 用例全绿——窗口去重改动不得影响同文件覆盖的自愈触发、配置缺省、监督熔断等既有交付面（本 SPEC 影响范围为 fenixd.py 与该测试文件）。出处：fenixd.py:988-1080（_update_stale_code_state 全函数）、tests/test_stale_code_selfheal.py:149-227（新增 TestStaleAlertWindowDedup 三用例混入既有套件） | pass | 0/3 | - |

## 本轮场景集变更

当前稳定场景集共 6 个（第 1 轮）。

- 首轮写入 6 个场景

