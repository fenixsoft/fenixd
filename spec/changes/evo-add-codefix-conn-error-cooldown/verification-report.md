# 验证报告：evo-add-codefix-conn-error-cooldown

> ⚠️ 本报告由框架于 2026-10-02T19:31:59Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。
> 报告时效标记（判定本报告是否属上一轮）：合成源轮次指纹：report.json@2026-10-03T05:05:00+08:00+run-result@mtime1790969517305073535

## 结论：❌ 未通过（Bug Found）

**状态：bug-found — 14/16 场景通过，1 失败，0 错误（1 个真实产品 Bug）**

| 指标 | 数量 |
| --- | --- |
| 通过 | 14 |
| 失败 | 1 |
| 错误 | 0 |
| 产品 Bug | 1 |
| 本链增量 Token（输入） | N/A |
| 本链增量 Token（输出） | N/A |


## 真实产品 Bug

### BUG-01（severity=major）· -

- 证据：
  - 独立复现（.history/tmp/repro7.py, REPRO-CONFIRMED）：cfg={'admin':{'code_review_fix':{'switch_cooldown_seconds':0}}}（0=关闭）下预置残留未来冷却态（switch_cooldown_until=now+300）后 orch.checkpoint() 返回 {'triggered': False, 'reason': 'switch_cooldown'} 仍拦截。守卫只读 prev_chain.get('switch_cooldown_until')，不调用 _switch_cooldown_seconds() 复核配置；_arm 层（core/code_fix.py:2568）配置 0 时不武装新冷却，但关闭配置不解除残留态


## 场景结果

| 场景 | 描述 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- | --- |
| conn-vocab-local-constant-covers-death-signatures | R1 分类词表：code-fix 车道本地常量 CODE_FIX_CONN_ERROR_PATTERNS 命中实测死因两形态（Can't reach the API server / ENOTFOUND）；负向——单轮超时文本、unrecognized_model 定噪行、空文本、超长文本均不命中（进程内探针；出处 spec R1 + design D1 + | pass | 0/1 | - |
| conn-shared-wordlist-unchanged-switch-semantics | Non-Goal 守卫：共享 SWITCH_ERROR_CONN_PATTERNS 未被扩充（对死因文本仍漏判、词源不含 ENOTFOUND/Can't reach），classify_switch_error 既有行为不变；is_api_timeout_signature 宽分支（terminal_reason=api_error）保持（进程内探针；出处  | pass | 0/1 | - |
| conn-envelope-conn-error-and-result-text-transparent | D2 信封透传：run_code_fix 失败信封携带 conn_error 布尔与 result_text 字段；单轮超时异常保持 api_timeout=True 且 conn_error=False（salvage 语义不动）；非挂载异常与产物硬门失败 conn_error=False（mock _run_claude 进程内探针；出处 core/ag | pass | 0/1 | - |
| cooldown-progress-field-persisted-and-readable | D4 冷却态持久化：write_progress 写 switch_cooldown_until（epoch 秒）原子合并落盘，fix-progress.json 含该字段，read_progress 经缺省表白名单读回（进程内探针；出处 core/code_fix.py:70/227/195-199） | pass | 0/1 | - |
| cooldown-gate-blocks-checkpoint-until-expiry | R2/R4 冷却闸门挂 checkpoint：seed 未来冷却态后直接调 checkpoint（full scan/手动/事件驱动重试与自驱动共用的唯一投递入口，非 _resubmit 专属）零建树零派发；冷却态拨到过期后首批正常投递且链收敛（进程内装配探针；出处 core/code_fix.py:2544 checkpoint、2911-2983 投递块 | pass | 0/1 | - |
| cooldown-config-override-zero-invalid-fallback | R2 冷却时长配置：admin.code_review_fix.switch_cooldown_seconds 覆盖生效（小值到期即放行）；0=关闭（未来冷却态不拦）；非法值（负数/非数）回退缺省仍拦；缺省复用 PROVIDER_SWITCH_COOLDOWN_SECONDS=300 且源码引用该键名（进程内探针；出处 core/code_fix.py:32 | fail | 1/2 | - |
| cooldown-e2e-conn-failure-defers-resubmit-then-delivers | SPEC 场景1 全链（R4 验收）：批 A 以 conn_error 失败信封收尾 → 冷却态+告警落地（默认时长≈PROVIDER_SWITCH_COOLDOWN_SECONDS）→ 链内自驱动重派被 checkpoint 拦下（窗口内派发/建树计数零增量）→ 冷却过期后批 B 正常投递（进程内装配探针；出处 core/code_fix.py:3820- | pass | 0/1 | - |
| cooldown-consumed-accounting-unchanged | R2 记账语义不变：冷却命中推迟仅影响投递时刻，失败批条目保持 open、chain_skipped 收录批条目、reason=agent_run_failed（consumed 语义与现状一致，无核销）（进程内装配探针；出处 core/code_fix.py:3846-3853） | pass | 0/3 | - |
| cooldown-alert-signal-fields-on-trigger | R3/D5 触发告警：冷却触发经 AdminStore 写 kind=SIGNAL 告警——signal_type=code_fix_switch_window_deferred、source=code-fix-lane、severity=warning，evidence 携带 run_id/死因文本/到期时刻（进程内装配探针；出处 core/code_fi | pass | 0/1 | - |
| cooldown-clear-alert-on-first-post-expiry-checkpoint | D5 解除告警：冷却到期后首个通过守卫的 checkpoint 补写一条解除告警（code_fix* 系列、文案携带推迟/冷却语义），触发+解除记录数递增（进程内装配探针；出处 design D5） | pass | 0/1 | - |
| fingerprint-crossday-recurrence-escalates-past-known-cooldown | SPEC 场景4（R3/D6 跨日同刻指纹升级）：已知指纹 + 重启冷却窗内 + 跨日同刻（24h−40s）复发 → _detect_daemon_errors 产出 daemon_errors 升级信号，不被已知指纹 30 分钟冷却压制（AdminMonitor 直构探针；出处 core/admin_monitor.py:2686-2760/2762、te | pass | 0/1 | - |
| fingerprint-non-proximity-and-same-window-controls | D6 控制组：跨日差 25h（超出 ±5 分钟容差）+ 已知指纹 + 冷却窗内仍被压制（升级仅限跨日同刻近似复发）；同窗 10 分钟内两条同指纹 → 既有升级路径照常工作（AdminMonitor 直构探针；出处 core/admin_monitor.py:133-142 常量、2686） | pass | 0/3 | - |
| pytest-new-test-file-green | 交付测试套件全量通过：python3 -m pytest tests/test_codefix_conn_error_cooldown.py -v（tasks 4.1 分类判据单测 / 4.2 冷却闸门单测 / 4.3 告警与跨日指纹单测；出处 spec/changes/evo-add-codefix-conn-error-cooldown/tasks.md | pass | 0/1 | - |
| pytest-provider-circuit-and-salvage-regression-green | 回归守卫：既有 provider_circuit 套件与 api_timeout salvage 套件全量通过（R1 MUST NOT 扩共享词表、单轮超时 salvage 语义不变的回归面；出处 tests/test_provider_circuit.py、tests/test_code_fix_api_timeout_salvage.py） | pass | 0/1 | - |
| pytest-codefix-orchestrator-regression-green | 回归守卫：既有 code-fix 车道套件全量通过（R2 冷却闸门 MUST NOT 改变既有投递/记账行为的回归面；出处 tests/test_code_fix.py、tests/test_code_fix_item_level_progress.py） | warning | 1/3 | - |
| pytest-admin-monitor-regression-green | 回归守卫：既有 admin_monitor daemon_errors 套件全量通过（D6 跨日维度为增量、既有窗口/冷却/合并语义不变的回归面；出处 tests/test_admin_dispatch_escalation.py） | pass | 0/1 | - |
