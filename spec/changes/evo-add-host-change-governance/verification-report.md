# 验证报告：evo-add-host-change-governance

> ⚠️ 本报告由框架于 2026-10-05T22:33:51Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。
> 报告时效标记（判定本报告是否属上一轮）：合成源轮次指纹：report.json@2026-10-05T22:33:50.812871+00:00+run-result@mtime1791239630849890549

## 结论：✅ 通过（verified）

**状态：verified — 11/11 场景通过，0 失败，0 错误（全部场景通过）**

全绿快道: 11/11 场景通过、0 失败 0 警告——无分类对象，跳过 judge 机械 verified

| 指标 | 数量 |
| --- | --- |
| 通过 | 11 |
| 失败 | 0 |
| 错误 | 0 |
| 产品 Bug | 0 |
| 本链增量 Token（输入） | 2.44M |
| 本链增量 Token（输出） | 0.05M |


## 场景结果

| 场景 | 描述 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- | --- |
| implementer-prompt-host-change-contract | 实现者提示词宿主变更契约齐备：宿主系统级变更（内核模块/dkms/系统包/设备节点）MUST 先备份原版本（路径+版本+加载参数）、变更发生时即时写入 worktree 根 host_changes.json 登记文件、击杀类终止下登记是唯一权威载体、收尾 run 结果汇总与登记两处一致、附可执行回滚指引、用户态优先 MUST NOT 动系统级（spec 1.1；锚点 agents/implementer.md:14-19） | pass | 0/6 | - |
| administrator-prompt-destructive-backup-must | administrator 处置记录模板将备份目录/回滚计划升为破坏性动作 MUST 项：凡破坏性动作（删除/覆盖/状态重置/进程重启/宿主系统级变更）对应条目 MUST 写明备份目录与回滚计划（原版本位置+版本+还原步骤）、未先备份即动手属处置违规、备份目录与回滚计划为必填项不得仅作示例性提及（spec 1.2；锚点 agents/administrator.md:137,142） | pass | 0/5 | - |
| host-change-governance-testsuite-green | 交付测试套件全绿：python3 -m pytest tests/test_host_change_governance.py -v --tb=short（只 -v 不并列 -q），击杀类终态登记派发/失败终态派发与去重/成功零告警/汇总 fail-open/解析容忍/拷回守卫各代表用例逐条 PASSED 且 exit_code 0（tasks 3.1；锚点 tests/test_host_change_governance.py:118-454） | pass | 0/7 | - |
| dispatch-alert-shape-and-content | 回滚义务告警派发正向形态（进程内装配探针）：dispatch_host_change_rollback_alert 返回记录 kind=escalation、severity=major、signal_type=host_change_rollback_obligation、spec 正确、host_change_paths 含全部对象路径（含 path 别名元素）、description 含回滚义务文案/变更计数/原版本、recommended_action 含按备份与指引回滚、evidence 含 host_change_count、handled 缺省 false、落盘 .fenix/admin_alerts.json 恰 1 条（spec 2.2；锚点 core/admin_store.py:961-1046） | pass | 0/7 | - |
| dispatch-dedup-and-cross-spec-lifecycle | 去重键=spec+变更对象路径全生命周期（进程内装配探针）：同 spec 同对象路径二次派发返回 None 且磁盘不落新条（在途去重）；跨 spec 同对象路径照常落地不串扰；mark_handled 闭环后同 spec 同对象路径重新派发落新条（已处理闭环才落新条）；终态磁盘恰 3 条（spec 需求2 去重；锚点 core/admin_store.py:1033-1046、core/admin_store.py:589） | pass | 0/9 | - |
| dispatch-malformed-registry-fail-open | 登记形态缺陷降级为告警内容缩水不抛错（进程内装配探针）：host_changes 非 list（None/字符串）/空数组/全无效元素（非 dict、数字、空对象、空白路径、缺对象路径）派发均返回 None 且零落盘；混合清单只统计有效元素（host_change_count=1）；异常路径不产生任何 Python 异常（spec 2.2 宽松容忍；锚点 core/admin_store.py:986-1002） | pass | 0/8 | - |
| killed-terminal-dispatch-from-worktree-registry | 头牌场景——击杀类终止（worktree 无 .fenix-run-result.json）宿主变更登记不丢失（进程内装配探针）：终态记录点 _dispatch_host_change_rollback_on_failure 读 worktree 根 host_changes.json 派发回滚义务告警（含回滚指引与对象路径）；派发后 worktree 被整目录删除告警仍存活（义务不随 run 终态/worktree 清理丢失）；登记非法 JSON、空清单、登记文件缺失、wt_path=None 四分支均 fail-open 零新告警零异常（spec 需求2 击杀场景；锚点 core/agent_runner/runner.py:5101-5147） | pass | 0/11 | - |
| success-terminal-trace-only-zero-alerts | 成功终态不告警仅留痕（进程内装配探针）：登记在场时 _trace_host_changes_on_success 只落留痕日志（含『留痕』『不告警』文案与对象路径），零回滚义务告警落盘、不产生 admin_alerts.json；无登记零动作零日志；回归点——成功留痕后同 spec 失败终态派发通道仍正常工作（spec 需求3 成功终态不告警；锚点 core/agent_runner/runner.py:5149-5175） | pass | 0/9 | - |
| result-gate-summary-soft-check-fail-open | run-result host_changes 汇总警告级校验 fail-open 语义（进程内装配探针）：结果缺 host_changes 字段零拦截零告警（历史 run/无宿主变更 run 零开销）；结果非 dict 零动作；字段非数组、元素缺对象路径、汇总与 worktree 登记对象路径集合不一致三种形态仅 WARNING 放行且恒返回 None（不产生失败终态/不参与门判定）；汇总与登记一致时零告警（spec 2.3；锚点 core/agent_runner/result_gate.py:1364-1418） | pass | 0/8 | - |
| registry-parsing-tolerance | 登记文件解析容忍（进程内装配探针）：文件缺失/非法 JSON/顶层非列表（对象、字符串）均返回 None 按无有效登记处理；空数组是合法值返回 []（与缺失可区分）；{changes:[…]} 包装形态容忍；host_change_object_path 兼容 path 别名且 object_path 优先、非 dict 元素返回空串（spec 2.3 解析单点；锚点 core/agent_runner/result_gate.py:1331-1361） | pass | 0/10 | - |
| copyback-main-tree-trace-and-mtime-guard | result-bearing run 登记拷回主树留痕（进程内装配探针）：_copyback_host_changes 把 worktree 根 host_changes.json 拷到 .fenix/host_changes/<spec>.json（per-spec 文件防并发互覆）、内容与登记一致；无登记零动作不建文件；mtime 守卫——主树已有较新留痕时不被 worktree 陈旧登记回灌覆盖（spec 2.1 拷回；锚点 core/agent_runner/runner.py:5075-5099） | pass | 0/7 | - |
