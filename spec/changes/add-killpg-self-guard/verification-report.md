# 验证报告：add-killpg-self-guard

> ⚠️ 本报告由框架于 2026-10-07T10:34:06Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。
> 报告时效标记（判定本报告是否属上一轮）：合成源轮次指纹：report.json@2026-10-07T10:34:06.370596+00:00+run-result@mtime1791369246404027330

## 结论：✅ 通过（verified）

**状态：verified — 12/12 场景通过，0 失败，0 错误（全部场景通过）**

全绿快道: 12/12 场景通过、0 失败 0 警告——无分类对象，跳过 judge 机械 verified

| 指标 | 数量 |
| --- | --- |
| 通过 | 12 |
| 失败 | 0 |
| 错误 | 0 |
| 产品 Bug | 0 |
| 本链增量 Token（输入） | 2.25M |
| 本链增量 Token（输出） | 0.04M |


## 场景结果

| 场景 | 描述 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- | --- |
| guard-helper-contract | 守卫助手单点收口契约：core/proc_utils.py 导出 guard_killpg，签名含位置参 target_pid/sig 与 keyword-only caller/resolve，resolve 缺省 False（design D1；core/proc_utils.py） | pass | 0/2 | - |
| guard-reject-own-group-no-signal | 自身进程组拒绝且不发出信号：resolve 型（替身 pid=0 → os.getpgid(0) 解析到调用者自身组）与组长直传型（自身 pgid）均拒绝、返回 False、不抛异常；探针先 os.setpgrp() 独立成组隔离爆炸半径，守卫失效误发信号则探针被杀、场景失败（spec Scenario 替身 pid=0 不再团灭宿主；core/proc_utils.py） | pass | 0/2 | - |
| guard-reject-warning-log | 守卫拒绝留 WARNING 告警日志：捕获 logging 记录，断言 level=WARNING 且消息含调用点标识（caller）与目标 pgid（spec Scenario 守卫拒绝留告警；core/proc_utils.py guard_killpg） | pass | 0/2 | - |
| guard-uniform-across-forms | 两种入参形态判定一致：同一外部真实独立组（Popen start_new_session=True）resolve 型与直传型均放行，同一自身组两形态均拒绝——同一自身组比对口径不因入参形态漂移（spec Scenario 两种入参形态语义一致；core/proc_utils.py） | pass | 0/2 | - |
| guard-allows-real-session-group | 真实独立组正常清场行为不变：组长忽略 SIGTERM 的 start_new_session 子进程经收口后 kill_process_group 清场，SIGTERM→宽限→SIGKILL 补刀序列照常收整组（returncode=-9）、全程零 WARNING（spec Scenario 正常独立组清场行为不变；core/proc_utils.py kill_process_group） | pass | 0/2 | - |
| guard-esrch-and-resolve-fail-silent | fail-closed 静默语义：已消亡进程组（ESRCH）与解析失败 pid（-1，确定性 ProcessLookupError，对齐 tests/test_knowledge_backfill.py:751 先例）均静默返回 False、不抛异常、不改调用方控制流（proposal What Changes；core/proc_utils.py） | pass | 0/2 | - |
| cleanup-fake-pid0-no-suicide | 收口后清场函数端到端防自伤：proc_utils.kill_process_group 与 regression._kill_process_group 面对事故同款 pid=0 替身均静默返回、留 WARNING、宿主组零信号（spec Scenario 替身 pid=0 不再团灭宿主；core/regression.py:721 _kill_process_group、core/proc_utils.py:206 kill_process_group） | pass | 0/2 | - |
| guard-unit-tests-pass | 新守卫单测全绿：tests/test_killpg_self_guard.py 覆盖替身 pid=0/自身 pid 不团灭宿主、真实独立组清场不变、守卫拒绝留 WARNING、两种入参形态判定一致（tasks 1.4；tests/test_killpg_self_guard.py） | pass | 0/2 | - |
| fake-proc-pid0-removed | 存量替身怪值修正：tests/test_codefix_digest_metrics.py 不再存在 self.pid = 0（对齐 test_knowledge_backfill.py pid=-1 不可达 pid 先例，tasks 1.3；tests/test_codefix_digest_metrics.py:74） | pass | 0/3 | - |
| cleanup-sites-wired | 全部清场击杀点收口到守卫：16 个含真实击杀跳的 core 文件均引用 guard_killpg（proposal Impact 以 grep 全量盘点为准 + 本轮复核补充 serving_registry.py:322,358、dashboard/routes/regression_routes.py:206,241、verify_engine/cli_runner.py:587、v2_dev_server.py:507,526） | pass | 0/3 | - |
| no-bare-killpg-in-core | core 下清场击杀语义裸 os.killpg 零存在（探活 killpg(_, 0) 豁免、守卫实现 core/proc_utils.py 豁免）——独立复核 spec grep 验收，防未来新增清场点绕过守卫（specs/killpg-self-guard/spec.md；tasks 3.2） | pass | 0/3 | - |
| existing-cleanup-tests-pass | 既有清场相关测试在守卫落地后仍全绿（SIGTERM→宽限→SIGKILL 序列语义逐位不变的回归点）：tests/test_knowledge.py、tests/test_knowledge_backfill.py（pid=-1 先例所在文件）、tests/test_codefix_digest_metrics.py（怪值替身所在文件）（tasks 3.3；tests/） | pass | 0/2 | - |
