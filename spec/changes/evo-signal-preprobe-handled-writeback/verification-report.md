# 验证报告：evo-signal-preprobe-handled-writeback

> ⚠️ 本报告由框架于 2026-09-26T04:29:10Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。
> 报告时效标记（判定本报告是否属上一轮）：合成源轮次指纹：report.json@2026-09-26T04:29:10.034867+00:00

## 结论：✅ 通过（verified）

**状态：verified — 11/11 场景通过，0 失败，0 错误（全部场景通过）**

全绿快道: 11/11 场景通过、0 失败 0 警告——无分类对象，跳过 judge 机械 verified

| 指标 | 数量 |
| --- | --- |
| 通过 | 11 |
| 失败 | 0 |
| 错误 | 0 |
| 产品 Bug | 0 |
| 本链增量 Token（输入） | 2.47M |
| 本链增量 Token（输出） | 0.03M |


## 场景结果

| 场景 | 描述 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- | --- |
| suite-deliverable-tests-15 | 交付物单测全量通过：tests/test_signal_preprobe_handled_writeback.py 15 例（tasks 2.1）——探测通过免唤起且 escalated=true、诉求未满足照常唤起、探测异常 fail-open 照常唤起、处置终态回写 handled=true 及 escalate/pending/signal_rec=None 分支、白名单外行为不变。命令只用 -v 不并列 -q，断言文案照抄实测输出行 | pass | 0/5 | - |
| preprobe-pass-regression-closure | R3/R6 探测通过即闭环：项目 .fenix/verify.yaml 已含 regression 段时摄取 verify_regression_missing 信号 → 不唤起 Administrator（mock 计数 0）、handled=true、escalated=true（摄取过滤只看 escalated，防下一 tick 重捞）、恰 1 条 result=resolved 处置留痕且 action_taken 注明「探测通过/免唤起」、不带 admin_run_id（不伪造在飞 run）；下一 tick 不重捞、不重复留痕。出处：core/admin_monitor.py:1870-1884（前置探测守卫）、:1978（_close_signal_preprobed）、白名单常量 :463（PREPROBE_SIGNAL_TYPES） | pass | 0/2 | - |
| preprobe-pass-other-whitelist-types | R3 白名单另两型探测通过闭环：verify_contract_missing（.fenix/verify.yaml 存在且可解析即诉求满足）、build_artifact_paths_missing（worktree.build_artifact_paths 非空；has_build_artifacts=false「确无产物」已裁决亦算满足）三夹具均免唤起（mock 计数 0）且 handled=true。出处：core/admin_monitor.py:1948-1976（_preprobe_signal_satisfied 只读谓词） | pass | 0/2 | - |
| preprobe-unsatisfied-still-invokes | R3 反例（现有路径不变）：verify.yaml 存在但缺 regression 段、verify.yaml 整体缺失、build_artifact_paths_missing 未裁决（无路径且无 has_build_artifacts=false）三态均唤起恰 1 次、照常 mark_escalated=true、handled 不置位。出处：core/admin_monitor.py:1870-1884（satisfied=False 落回原唤起路径） | pass | 0/2 | - |
| preprobe-fail-open-still-invokes | R4 fail-open：_preprobe_signal_satisfied 抛 RuntimeError 时按原路径照常 mark_escalated 并唤起 Administrator（计数 1）、不置 handled，且留「前置探测异常」警告日志可对账（R6）——探测器自身缺陷不吞信号。出处：core/admin_monitor.py:1871-1880（except 分支） | pass | 0/2 | - |
| preprobe-readonly-project-untouched | R2 探测只读：对白名单三型依次执行 _preprobe_signal_satisfied，项目树（.fenix/verify.yaml 等）递归快照（相对路径/大小/mtime_ns）前后完全一致——不写项目文件、不触发构建或网络访问。出处：core/admin_monitor.py:1948-1976（谓词仅 load_verify_contract 读文件与 config 读键） | pass | 0/2 | - |
| whitelist-boundary-unchanged | R1 白名单边界：PREPROBE_SIGNAL_TYPES 恰含三种可探测类型（verify_regression_missing/verify_contract_missing/build_artifact_paths_missing）；白名单外 verify_uniform_failure 即使诉求事实已满足（regression 段在场）也不触发探测（mock assert_not_called）、照常唤起 1 次、不置 handled——白名单外行为完全不变。出处：core/admin_monitor.py:456-472（常量注释含收录约束）、:1870（守卫入口） | pass | 0/2 | - |
| writeback-final-resolved | R5 处置终态回写：_invoke_administrator 落 result=resolved 的最终 DISPOSITION 后回写原信号 handled=true（AdminStore.mark_signal_handled），处置记录本身照常落盘（恰 1 条 result=resolved）。出处：core/admin_monitor.py:3590-3617（终态回写：result 非 pending、escalate 为假、signal_rec 非 None）、:3441（_invoke_administrator） | pass | 0/2 | - |
| writeback-exemptions-skip | R5 豁免与非终态：escalate=true（升级人工，人工处置是唯一出路）不自动回写；result=pending（非终态）不回写；人工显式触发 signal_rec=None 无关联记录跳过回写且不抛错；各分支处置结果均照常落盘。出处：core/admin_monitor.py:3590-3617（豁免条件） | pass | 0/2 | - |
| writeback-failure-degrades | R5 回写失败降级：mark_signal_handled 抛 OSError 时 _invoke_administrator 不抛出、处置结果照常落盘（恰 1 条 result=resolved）、仅记「回写」警告日志不阻塞落盘（R6 可对账）。出处：core/admin_monitor.py:3604-3614（except 降级分支） | pass | 0/2 | - |
| admin-related-regression-suite | 存量回归零破坏：admin 监视器/存储/派发升级/信号相关 5 个测试文件（test_admin.py、test_admin_store_corruption.py、test_admin_dispatch_escalation.py、test_artifact_paths_signal.py、test_stuck_signal_hygiene.py）共 207 例全过——前置探测守卫插入 _detect_family_explosion（core/admin_monitor.py:1866-1884）后既有摄取路径行为不变。命令只用 -q 不并列 -v，断言「N passed」汇总行 | pass | 0/2 | - |

## 本轮场景集变更

当前稳定场景集共 11 个（第 1 轮）。

- 首轮写入 11 个场景

