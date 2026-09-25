# 验证报告：evo-add-stale-code-dangling-deadline

> ⚠️ 本报告由框架于 2026-09-25T00:47:29Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。
> 报告时效标记（判定本报告是否属上一轮）：合成源轮次指纹：report.json@2026-09-25T00:47:29.352481+00:00

## 结论：✅ 通过（verified）

**状态：verified — 13/13 场景通过，0 失败，0 错误（全部场景通过）**

全绿快道: 13/13 场景通过、0 失败 0 警告——无分类对象，跳过 judge 机械 verified

| 指标 | 数量 |
| --- | --- |
| 通过 | 13 |
| 失败 | 0 |
| 错误 | 0 |
| 产品 Bug | 0 |
| 本链增量 Token（输入） | 3.16M |
| 本链增量 Token（输出） | 0.07M |


## 场景结果

| 场景 | 描述 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- | --- |
| config-max-dangling-default | 配置正向·新键缺省值（tasks 1.1）：stale_code_selfheal 配置节缺失、键缺失两种空状态，以及显式配置 14400 三种输入下，get_stale_code_selfheal_config 返回的 max_dangling_seconds 均为缺省 14400 秒（4 小时）。出处：core/config.py:1396 get_stale_code_selfheal_config / spec.md Requirement 悬空超时不等空闲的安全重启（缺省 14400） | pass | 0/4 | - |
| config-max-dangling-zero-disables | 配置边界·0=关闭升级（tasks 1.1）：显式配置 max_dangling_seconds=0 是合法值，读取返回 0 而非回退缺省——验证实现为本键新写了「0 合法并返回 0」校验，未误复用 0/负一律回退缺省的 _stale_selfheal_positive_int helper。出处：core/config.py:1383 _stale_selfheal_positive_int / tasks.md 1.1 | pass | 0/3 | - |
| config-max-dangling-invalid-fallback | 配置异常路径·非法值回退缺省（tasks 1.1）：负值 -5、bool True、bool False、字符串 "3600"、None 五类非法输入下 max_dangling_seconds 均回退缺省 14400 且不抛异常（bool 是 int 子类须显式排除）。出处：tasks.md 1.1 / core/config.py:1371-1380 缺省常量区 | pass | 0/6 | - |
| dangling-since-edge-set-and-recovery-clear | 悬空计量正向+回归（tasks 2.1 / spec.md Requirement 代码基线悬空时长计量）：_code_stale 假→真边沿时记录悬空起点 _code_stale_since（UTC、≤当前时刻），且既有 stale_code 边沿告警行为不变（仍写入一条告警——回归点）；真→假恢复时 _code_stale_since 清零。进程启动即陈旧取启动时刻的情形由全量单测场景覆盖。出处：fenixd.py:1011-1103 _update_stale_code_state / spec.md Scenario 进入陈旧态记录起点、基线恢复新鲜清零 | pass | 0/5 | - |
| dangling-timeout-busy-writes-restart-request | 核心正向·忙时悬空超时触发安全重启（tasks 2.2 / spec.md Scenario 悬空超时且系统繁忙）：_code_stale 为真、悬空时长超 max_dangling_seconds、同时存在在飞 run（pm_engine._active_runs=1 非空闲）时，不再等待空闲直接写 .fenix/restart_request 触发既有规划性重启排水。出处：fenixd.py:1535-1724 _maybe_stale_selfheal_tick / fenixd.py:1105-1160 _is_idle / spec.md Requirement 悬空超时不等空闲的安全重启 | pass | 0/3 | - |
| dangling-timeout-history-self-triggered-faithful | 重启历史如实记录（spec.md Scenario 悬空超时且系统繁忙 THEN 子句）：超时分支触发的重启经既有 _record_selfheal_restart 路径落 restart_history.jsonl，距上次重启超 self_triggered_window_seconds（预置 1 小时前历史）时新条目 self_triggered 必须记否（streak 归零）——超时分支不得强制置真。出处：fenixd.py:1348-1380 _record_selfheal_restart / spec.md「该标志记否；超时分支不得强制置真」 | pass | 0/5 | - |
| dangling-not-timeout-no-trigger | 回归点·悬空未超时行为与现状一致（tasks 2.2 / spec.md Scenario 悬空未超时不触发）：_code_stale 为真但悬空 60 秒未达 max_dangling_seconds=3600 且系统繁忙时，不写 restart_request、不产生 stale_code_dangling_timeout 告警、不追加重启历史——忙时仅清零空闲计时。出处：fenixd.py:1535-1724 / spec.md Scenario 悬空未超时不触发 | pass | 0/4 | - |
| dangling-timeout-zero-config-disabled | 异常路径·升级开关关闭（tasks 1.1 / spec.md Scenario 升级开关关闭）：max_dangling_seconds=0 时即使悬空已达一天也不执行悬空超时分支——不写 restart_request、不写升级告警，行为与现状完全一致（空闲自愈路径不受影响）。出处：spec.md Scenario 升级开关关闭 / core/config.py 0=关闭升级语义 | pass | 0/3 | - |
| dangling-timeout-alert-unhandled-dedup | 升级告警交互流程（tasks 3.1 / spec.md Requirement 悬空超时升级告警需人工知悉）：超时分支首次触发写入 signal_type=stale_code_dangling_timeout、severity=warning 告警且保持未处理（不写入即 mark_handled，须进入人工待处理视图）；模拟重启后新进程在 60 分钟内再次超时触发（STALE_ALERT_DEDUP_MINUTES=60 窗口内），告警经 latest_signal 去重不重复写（仍 1 条）但重启触发不受影响（restart_request 二次写入）。出处：fenixd.py:114 STALE_ALERT_DEDUP_MINUTES / fenixd.py:1382-1422 _alert_selfheal_cooldown 写入模式 / spec.md Scenario 超时触发产生未处理告警、60 分钟内不重复写 | pass | 0/6 | - |
| dangling-timeout-in-flight-no-rewrite | 防重复写（tasks 2.3）：.fenix/restart_request 已在场（in-flight 重启在途）时，即使悬空已超时也不重写该文件（内容保持原样）——避免主循环 1s tick 每秒重复 touch。出处：fenixd.py:1601-1604 in-flight 阻断 / tasks.md 2.3 | pass | 0/3 | - |
| dangling-timeout-gates-still-hold | 回归点·既有闸门对超时分支仍生效（tasks 2.2）：a) cooldown 锁存未到期（_cooldown_started_at 置为当前）时悬空超时不写 restart_request；b) SPEC delta specs/stale-code-dangling-deadline/spec.md:25 明言悬空超时触发时距上次重启必然已超自触发窗口（结构性互斥，重启即刷新 baseline），原『10s 前重启→不写』前提不可达，改为：窗口内超时触发按既有 _record_selfheal_restart 语义如实记录 self_triggered=True、streak 1→2 延续（不得强制置真/写死的双向校验）。出处：fenixd.py:1797-1865 / tasks.md 2.2 | pass | 0/3 | - |
| stale-selfheal-pytest-full-regression | 单测交付物全量回归（tasks 4.1/4.2）：tests/test_stale_code_selfheal.py 全文件 pytest 通过——既有用例（陈旧状态持久化/告警窗口去重/空闲自愈触发/配置缺省/冷却熔断）无回归，且实现者新增的悬空计量/超时重启/升级告警用例全部通过。出处：tests/test_stale_code_selfheal.py / tasks.md 4.1/4.2 | pass | 0/2 | - |
| unit-tests-new-marker-coverage | 单测新行为覆盖在场校验（tasks 4.1 防缺位）：tests/test_stale_code_selfheal.py 中必须真实出现本 SPEC 新交付的契约标识符——配置键 max_dangling_seconds 与告警 signal_type stale_code_dangling_timeout（两者为 SPEC 规定的契约名，覆盖用例必然引用），防止「旧文件全过但新行为零覆盖」的假阴性。出处：tasks.md 1.1/3.1/4.1 | pass | 0/2 | - |

## 本轮场景集变更

当前稳定场景集共 13 个（第 1 轮）。

- 首轮写入 13 个场景

