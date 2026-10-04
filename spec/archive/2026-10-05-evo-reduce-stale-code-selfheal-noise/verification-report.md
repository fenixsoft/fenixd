# 验证报告：evo-reduce-stale-code-selfheal-noise

> ⚠️ 本报告由框架于 2026-09-26T19:54:37Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。
> 报告时效标记（判定本报告是否属上一轮）：合成源轮次指纹：report.json@2026-09-26T19:54:37.828206+00:00

## 结论：✅ 通过（verified）

**状态：verified — 15/15 场景通过，0 失败，0 错误（全部场景通过）**

全绿快道: 15/15 场景通过、0 失败 0 警告——无分类对象，跳过 judge 机械 verified

| 指标 | 数量 |
| --- | --- |
| 通过 | 15 |
| 失败 | 0 |
| 错误 | 0 |
| 产品 Bug | 0 |
| 本链增量 Token（输入） | 10.10M |
| 本链增量 Token（输出） | 0.14M |


## 场景结果

| 场景 | 描述 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- | --- |
| cli-fixture-reset-idle-default | 夹具自建（首轮裁决修复，evo-reduce-stale-code-selfheal-noise）：幂等清除用户级 /root/.fenix/config.yaml（及项目级同名文件若在场）中 stale_code_selfheal.idle_confirm_seconds 的显式遗留值，使后续 GET /api/config 的 600 断言真实走 seeds/ConfigLoader 缺省路径，而非回显运行前遗留的显式旧值 120；仅删除该键所在行，文件其余内容逐字节保留，幂等可重入 | pass | 0/2 | - |
| cli-idle-default-parse-and-override | 缺省 idle_confirm_seconds=600 的解析、项目显式覆盖优先、非法值回退不抛异常（tests/test_stale_selfheal_idle.py 单元回归，evo-reduce-stale-code-selfheal-noise 3.1；出处 tests/test_stale_selfheal_idle.py:257 test_default_parses_600、:263 test_project_override_wins、core/config.py:1492/:1572）（首轮裁决修复注记：test_invalid_values_fallback_no_raise 实位于 tests/test_stale_code_selfheal.py:865，原命令仅列 tests/test_stale_selfheal_idle.py 致 -k 第三项落空，pytest 目标补该文件；三条断言未改动） | pass | 0/4 | - |
| cli-idle-dense-batches-single-round | 密集批次合并为一轮重启：缺省 600 秒确认窗达到前不触发重启、空闲窗内反复落地仅触发一轮自愈重启（spec「开发日密集落地」场景，R1 合批语义；出处 tests/test_stale_selfheal_idle.py:274 test_default_blocks_trigger_before_600、:283 test_dense_batches_single_restart_round、fenixd.py:1735 _maybe_stale_selfheal_tick 空闲累计与判定） | pass | 0/3 | - |
| cli-alert-info-when-healthy | 自愈健康路径 info 级留痕：selfheal enabled 且未悬空超限时 stale_code 告警以 kind=info / severity=info 写入并附当日累计日志，日计数以存储当日记录数计、跨重启存活（spec「自愈启用且重启成功」；出处 fenixd.py:1201-1241 info 写入块与日计数日志、:1289 _stale_selfheal_healthy、:1305 _stale_code_daily_count、tests/test_stale_code_selfheal.py:116/:144） | pass | 0/3 | - |
| cli-alert-escalation-fallbacks | 分流反面仍走 escalation：selfheal disabled 写 escalation、悬空超限由独立 signal_type=stale_code_dangling_timeout 升级（不双重升级、不写 info）、restart_request 写失败新增 escalation 升级（spec「自愈禁用、失败或悬空超限」；出处 fenixd.py:1254-1277 disabled 分支、:1555 _alert_dangling_timeout、:1721/:2146 _alert_selfheal_write_failure、tests/test_stale_code_selfheal.py:191/:204/:600） | pass | 0/4 | - |
| cli-alert-dedup-shared-window | 60 分钟去重对 info 级生效且与 escalation 同窗口互斥：任一在窗内即跳过写入降级为日志、持续陈旧不重复成条、写失败升级同受去重（出处 fenixd.py:158 STALE_ALERT_DEDUP_MINUTES、:1186-1195 latest_signal 窗口查询、core/admin_store.py:36 INFO 常量、:557 INFO 入 latest_signal kind 白名单、tests/test_stale_code_selfheal.py:163/:344/:614） | pass | 0/4 | - |
| cli-alert-info-not-in-pending-views | info 级记录不进 pending_escalations 同口径清单，告警视图/admin 活动流/SPEC 时间轴均忽略 info，mark_handled 仅锚定 ESCALATION 的闭环口径不受影响（出处 core/admin_store.py:380-444 ESCALATION 锚定注释、fenixd.py:1213-1214 info 记录 handled=true+handled_at 随 payload 落盘不经 mark_handled 接口、tests/test_stale_code_selfheal.py:221/:664/:678） | pass | 0/4 | - |
| cli-seed-info-record | 向验证实例 .fenix/admin_alerts.json 注入一条真实 info 级 stale_code 记录（走验证树自带 core.admin_store 真实写入路径），供后续 web 场景断言前端对未知 kind=info 的容忍与不渲染（evo-reduce-stale-code-selfheal-noise 3.3 前置种子；出处 core/admin_store.py:36 INFO 常量、:85-87 alerts_path=.fenix/admin_alerts.json、append 补齐 id/created 默认字段） | pass | 0/3 | - |
| api-config-default-idle-600 | GET /api/config（用户级）返回陈旧自愈缺省 enabled=true / idle_confirm_seconds=600（evo-reduce-stale-code-selfheal-noise R1/2.4：生效配置 seeds 与 ConfigLoader 缺省同步 120→600，防设置页以旧缺省回填；出处 core/config.py:1492 STALE_CODE_SELFHEAL_IDLE_SECONDS_DEFAULT=600、core/dashboard/data/config_admin.py:454 seeds、:885 GET 读路径填充）（首轮裁决修复注记：新增前置夹具 cli-fixture-reset-idle-default 幂等清除用户级遗留显式 idle_confirm_seconds=120，使本场景真实回归 seeds/缺省 600 路径；断言未改动） | pass | 0/4 | - |
| api-config-project-override-roundtrip | 项目显式覆盖优先生效且可往返：POST /api/config 写入 idle_confirm_seconds=300 后读回 300，再写回 600 恢复缺省显示（spec「项目显式覆盖」场景；出处 core/config.py:1572 get_stale_code_selfheal_config 项目覆盖读取路径、core/dashboard/data/config_admin.py:1216-1223 stale 节两键合并写路径）（首轮裁决修复注记：depends_on 补串夹具 cli-fixture-reset-idle-default——基线 GET 曾受用户级遗留显式 120 污染回显；断言未改动） | pass | 0/7 | - |
| web-panel-default-600 | 设置页「自进化」页签陈旧自愈面板按新缺省回填：空闲确认秒数输入框显示 600、总开关缺省开启（evo-reduce-stale-code-selfheal-noise 2.5；出处 core/dashboard/static/src/pages/settings/components/StaleCodeSelfhealPanel.tsx:11 DEFAULT_IDLE_SECONDS=600、:69/:100 两控件 testid、core/dashboard/static/src/pages/settings/pageLabels.ts:16 页签「自进化」、core/dashboard/static/src/pages/settings/index.tsx:406-427 面板挂载） | pass | 0/5 | - |
| api-config-invalid-value-rejected | 非法 idle_confirm_seconds 被服务端校验拒绝（400）且不落盘：负数与非数字均拒，读回仍为 600 缺省兜底（异常路径；出处 core/dashboard/data/config_admin.py:1687-1690 stale 节前置校验 fail、core/config.py:1585-1594 非法值回退缺省） | pass | 0/5 | - |
| web-panel-save-roundtrip-keeps-600 | 表单缺省值直存回归：不做任何改动直接保存，用户级配置写回 idle_confirm_seconds=600 而非旧缺省 120（tasks 2.5 核心回归点——防「设置页以 120 回填表单、用户保存即把 120 显式写回、静默覆盖新缺省」；出处 core/dashboard/static/src/pages/settings/index.tsx:418-424 页签唯一保存按钮 data-testid=settings-save、:169 保存成功 toast、StaleCodeSelfhealPanel.tsx:37-50 collect 恒返回该节配置） | pass | 0/4 | - |
| web-overview-info-record-silent | 概览页对未知 kind=info 容忍：在场 info 记录不致页面渲染报错、也不出现在告警横幅（横幅仅消费 ESCALATION，空态整体不渲染；evo-reduce-stale-code-selfheal-noise 3.3；出处 core/dashboard/static/src/pages/overview/index.tsx:115 AlertBanner 挂载、overview/components/AlertBanner.tsx:64 无告警时 return null、core/dashboard/data/admin_alerts.py:21/:35-36 unhandled 仅取 ESCALATION） | pass | 0/3 | - |
| web-activities-alert-view-tolerates-info | 运维页「人工告警」视图对未知 kind=info 容忍：注入 info 记录后切换告警视图不报错、info 记录不显示（evo-reduce-stale-code-selfheal-noise 3.3；出处 core/dashboard/static/src/pages/activities/index.tsx:481 data-testid=view-mode-switch、:483-485「人工告警」选项、core/dashboard/static/src/services/dashboard.ts:326-327 getAlerts → GET /api/alerts） | pass | 0/4 | - |

## 本轮场景集变更

当前稳定场景集共 15 个（第 1 轮）。

- 新增场景 cli-fixture-reset-idle-default（重新规划，第 1 轮）

