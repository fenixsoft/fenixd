# 验证报告：evo-add-commit-stray-wip-choice

> ⚠️ 本报告由框架于 2026-10-06T18:20:51Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。
> 报告时效标记（判定本报告是否属上一轮）：合成源轮次指纹：report.json@2026-10-06T18:20:50.990714+00:00+run-result@mtime1791310851025129560

## 结论：✅ 通过（verified）

**状态：verified — 9/9 场景通过，0 失败，0 错误（全部场景通过）**

全绿快道: 9/9 场景通过、0 失败 0 警告——无分类对象，跳过 judge 机械 verified

| 指标 | 数量 |
| --- | --- |
| 通过 | 9 |
| 失败 | 0 |
| 错误 | 0 |
| 产品 Bug | 0 |
| 本链增量 Token（输入） | 2.20M |
| 本链增量 Token（输出） | 0.04M |


## 场景结果

| 场景 | 描述 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- | --- |
| registry-stray-wip-bucket-registered | 注册表登记（任务 1.1/3.1，SPEC「信号可裁决」数据侧契约）：maintree_stray_wip_stale 桶新增 commit_stray_wip 选项（id/label/desc/action 齐备、spec_scoped=False 全局信号作用域）、is_adjudicable 为真、resolve_choice 桶内精确匹配可达、跨信号/全表反查通道语义守卫。出处 core/dashboard/data/adjudication_choices.py:96-110,292-296；tests/test_adjudication_choices.py:160 | pass | 0/5 | - |
| executor-scope-guard-global-allowed | 执行器作用域守卫（design D1/D1.2，spec_scoped=False 硬约束）：spec=None/空串/占位 'global' 三形态全局信号拒绝 spec_scoped 选项（retry_review）；commit_stray_wip 非作用域对全局信号放行；注册桶内 retry_review × 真实冻结 spec 对照（守卫不误伤合法路径）。出处 core/dashboard/data/admin_actions.py:2881-2992；tests/test_global_signal_choice_guard.py:142 | pass | 0/5 | - |
| executor-commit-happy-path-hash-trace | 正常执行留痕（任务 2.1，SPEC「正常执行留痕」）：全局信号 × commit_stray_wip 放行，只提交信号清单内文件（a.txt）、处置结果附提交 hash 且 steps 留痕、清单外 c.txt 不被裹挟；清单中已不在当刻 status 的陈旧条目静默跳过不报错（同指纹一次性告警语义）。出处 core/dashboard/data/admin_actions.py:2765-2879；tests/test_global_signal_choice_guard.py:267-296 | pass | 0/3 | - |
| executor-out-of-manifest-and-missing-record-rejected | 清单约束异常路径（任务 2.1，SPEC「清单外文件拒绝」）：执行请求携带信号清单之外路径被拒绝并返回原因、零 git 写（design D2 文件来源 MUST 限信号记录清单）；无含可解析「文件清单(N):」段的信号记录时在任何 git 读/写之前返回明确 error。出处 core/dashboard/data/admin_actions.py:2795-2821,2840-2851；tests/test_global_signal_choice_guard.py:311-355 | pass | 0/3 | - |
| executor-signal-type-binding-and-empty-intersection | signal_type 绑定守卫与空状态（任务 2.1，design D4，SPEC「跨信号触达拒绝」）：以 maintree_stray_wip_stale 之外的 signal_type（含未注册信号与姊妹 info 信号 maintree_untracked_stray_stale）请求 commit_stray_wip 一律拒绝且零 git 写——封死 resolve_choice 非作用域全表反查通道把本 git 写动作暴露给任意未注册信号的面；信号清单∩当刻改动为空时返回明确 error、不产生空提交。出处 core/dashboard/data/admin_actions.py:2704-2711,2789-2794,2830-2839；tests/test_global_signal_choice_guard.py:298-339 | pass | 0/3 | - |
| emission-record-choices-snapshot | 发射点带出选项（任务 2.2/3.3，SPEC「记录自带选项」）：宽限耗尽告警落库记录含 choices 快照（恰为 [commit_stray_wip] 且 spec_scoped=False）、recommended_action 文案提及选项 id；同指纹一次性告警回归点（不重复落库）。出处 core/worktree_manager/stray_wip.py:700-731；tests/test_maintree_stray_wip_sweep.py:151-191 | pass | 0/2 | - |
| monitor-recommendation-three-tables | admin_monitor 三表登记基线（任务 2.3 摄取门前置）：SIGNAL_SEVERITY=major、SIGNAL_RECOMMENDATION 非空、STORED_SIGNAL_TYPES 收录 maintree_stray_wip_stale；姊妹信号 mergeback_wip_orphan_stuck 同族对账。出处 core/admin_monitor.py:436-441；tests/test_maintree_stray_wip_sweep.py:379-395 | pass | 0/2 | - |
| probe-registry-contract-and-recommendation-sync | 直探注册表单源契约与双处文案同步（任务 1.1/2.3 直证，独立于项目测试套件）：choices_for(maintree_stray_wip_stale) 返回恰一选项 commit_stray_wip 且 spec_scoped=False、is_adjudicable 为真、resolve_choice 精确匹配可达且无拒绝原因；SIGNAL_RECOMMENDATION[maintree_stray_wip_stale] 带出选项 id 且与发射点 inline 文案含同文片段「或执行裁决选项 commit_stray_wip 一键提交信号清单内文件」（防双处漂移）；姊妹信号 maintree_untracked_stray_stale 有独立指引文案（对照，不受本选项污染）。stdout 纯 JSON，json_output 断言。出处 core/dashboard/data/adjudication_choices.py:311-343；core/admin_monitor.py:436-441 | pass | 0/11 | - |
| probe-executor-e2e-temp-repo | 临时隔离仓端到端直证（SPEC 三执行场景全链，独立于项目测试套件，回归点=执行前后 HEAD/工作区对比）：①夹具按 tests/test_global_signal_choice_guard.py:208-262 同构——临时 git 仓基线提交后留散件 WIP（a.txt 改动 + 清单外 c.txt），AdminStore 播种含「文件清单(1): a.txt」段的 maintree_stray_wip_stale SIGNAL 记录；②execute_adjudication_choice 执行 → ok=True、commit_hash==当前 HEAD（head 前移）、steps 含 hash 留痕、a.txt 出脏区、清单外 c.txt 不被裹挟；③守卫四连——姊妹信号 maintree_untracked_stray_stale 拒绝（error 提及绑定信号名）且零 git 写、未注册信号拒绝、_exec_commit_stray_wip paths 显式收窄携清单外 evil.txt 拒绝零 git 写（HEAD 三次均不动）；④复执行因清单∩当刻改动为空返回「空提交」error 不空提交。出处 core/dashboard/data/admin_actions.py:2765-2879 | pass | 0/14 | - |
