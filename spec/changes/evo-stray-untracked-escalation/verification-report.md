# 验证报告：evo-stray-untracked-escalation

> ⚠️ 本报告由框架于 2026-10-07T20:12:45Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。
> 报告时效标记（判定本报告是否属上一轮）：合成源轮次指纹：report.json@2026-10-07T20:12:44.861140+00:00+run-result@mtime1791403964898816328

## 结论：✅ 通过（verified）

**状态：verified — 14/14 场景通过，0 失败，0 错误（全部场景通过）**

全绿快道: 14/14 场景通过、0 失败 0 警告——无分类对象，跳过 judge 机械 verified

| 指标 | 数量 |
| --- | --- |
| 通过 | 14 |
| 失败 | 0 |
| 错误 | 0 |
| 产品 Bug | 0 |
| 本链增量 Token（输入） | 6.24M |
| 本链增量 Token（输出） | 0.06M |


## 场景结果

| 场景 | 描述 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- | --- |
| escalated-24h-threshold | 第二档升级·24小时滞留路径：滞留集合 elapsed≥24h 时恰发一次 maintree_untracked_stray_escalated（major），evidence 以「项目名=」开头并含集合体积（字节）暴露，注册表条目同源可查体积；同轮 info 信号一次性不重复。出处 spec stray-untracked-escalation『第二档升级信号』验收1、『体积采集随盘点输出』验收1（core/worktree_manager/stray_wip.py:504-566 现有盘点流） | pass | 0/11 | - |
| escalated-size-independent | 第二档升级·体积阈值独立路径：滞留集合含 530MB 真实大文件（≥缺省阈值 524288000 字节）且滞留时长远未达 24h（grace=0 使 info 告警在册后，升级在下一轮盘点即触发）——体积路径 MUST NOT 被滞留时长门控。出处 spec『第二档升级信号』验收2 与 design 关键取舍（core/worktree_manager/stray_wip.py:516-566） | pass | 0/8 | - |
| escalated-once-no-repeat | 第二档升级·只升级一次：同一滞留集合升级后继续多轮盘点并再次前移滞留时长（指纹未消失），升级信号与 info 信号记录数均恒为 1 不再增长（注册表双档 escalated 标记 + info 同指纹一次性双兜底）。出处 spec『第二档升级信号』验收3、tasks 1.2 | pass | 0/7 | - |
| below-threshold-clean-no-escalation | 空状态与降噪门回归：主树零散件时盘点无 untracked 信号、零告警；2 个散件（低于 entry 阈值 5）多轮盘点仅建档计时（below-threshold），零 info 零升级告警。出处 proposal 非目标『不动 info 信号降噪阈值』、stray_wip.py:500-549 现有阈值闸门 | pass | 0/7 | - |
| registration-tables-wiring | 自动唤起接线·登记表同步：SIGNAL_SEVERITY 登记 maintree_untracked_stray_escalated=major、SIGNAL_RECOMMENDATION 登记非空处置指引、STORED_SIGNAL_TYPES 收录新类型、_detect_family_explosion 项目名解析清单覆盖新类型（缺一则记录被丢弃唤起静默落空），evidence_project 单源解析可用。出处 spec『自动唤起接线』、tasks 2.1（core/admin_monitor.py:290/390/481/2511） | pass | 0/6 | - |
| ingestion-e2e-wakeup | 自动唤起接线·端到端摄取：向临时项目 store 写一条升级信号记录（spec=None、evidence 以「项目名=」开头），装配 AdminMonitor 最小上下文跑 _detect_family_explosion——按项目名解析出 spec、构造 severity=major 且 recommended_action 非空的信号、唤起 agent_runner、源记录 mark_escalated；二次摄取不重复唤起。出处 spec『自动唤起接线』验收1（core/admin_monitor.py:2486-2696） | pass | 0/8 | - |
| choices-registry-three-options | 裁决选项登记：adjudication_choices 注册表为 maintree_untracked_stray_escalated 登记恰好 3 个裁决选项（显式归档/追加 .gitignore/删除），全部 spec_scoped=False（全局信号可执行）、choice id 与 action 互不相同、桶内 resolve_choice 可解析、registered_signal_types 收录。出处 spec『untracked 认领执行器』、tasks 3.2（core/dashboard/data/adjudication_choices.py:129-315） | pass | 0/7 | - |
| executor-tracked-signal-reject | 认领执行器·tracked 桶信号拒绝零 git 写：以 tracked 桶信号 maintree_stray_wip_stale 逐一调用三个认领裁决选项（经 execute_adjudication_choice 公开入口），全部拒绝（ok=false），主树 HEAD 与 git status 逐字节不变、untracked 散件原位——零 git 写。出处 spec『untracked 认领执行器』验收1、tasks 3.1（core/dashboard/data/admin_actions.py:3140-3279） | pass | 0/7 | - |
| executor-archive-adjudication | 认领执行器·显式归档裁决落盘：对含归档语义的裁决选项，在带升级信号记录（evidence 文件清单段）的临时主树上执行——清单内文件移出原位、在项目内登记目录可寻得归档副本、执行结果 ok。出处 spec『untracked 认领执行器』验收2（admin_actions.py:2774-2794 清单单源复用） | pass | 0/6 | - |
| executor-gitignore-adjudication | 认领执行器·追加 .gitignore 裁决落盘：执行后 .gitignore 含清单路径条目且既有条目不重复追加（去重）、check-ignore --no-index 口径判定清单文件已被忽略、文件保留原位。出处 spec『untracked 认领执行器』验收2、tasks 3.1（_append_gitignore_entries/_path_already_ignored 复用，admin_actions.py:2907-2944） | pass | 0/7 | - |
| executor-delete-adjudication | 认领执行器·删除裁决落盘：清单内目标文件被移除，清单外无关文件不受影响，执行结果 ok 且 steps 非空（处置留痕）。出处 spec『untracked 认领执行器』验收2 | pass | 0/7 | - |
| executor-special-char-paths | 认领执行器·特殊字符路径兼容：信号清单段含中文+空格（报告 草稿.txt）与英文+空格（my notes v2.md）路径时，删除裁决能正确解析清单并精确移除目标、不误伤其他文件（清单段「文件清单(N):」解析对空格路径稳健）。出处 spec 验收偏差注解规范·异常路径覆盖要求（admin_actions.py:2723-2742 parse_stray_wip_manifest） | pass | 0/6 | - |
| regression-sweep-testsuite | 回归钉·盘点测试套件全过：tests/test_maintree_stray_wip_sweep.py 全量 pytest（含 tasks 4.1 新增的第二档升级覆盖：24h 触发、体积阈值触发、只升级一次、info 一次性不重复、TestAdminMonitorRegistration 两例随新信号同步）零失败。出处 tasks 4.1 | pass | 0/2 | - |
| regression-remediation-testsuite | 回归钉·根治测试套件全过：tests/test_stray_untrack_remediation.py 全量 pytest（含 tasks 4.2 新增覆盖：认领执行器对 tracked 桶信号拒绝零 git 写、归档/ignore/删除三种裁决落盘）零失败。出处 tasks 4.2 | pass | 0/2 | - |
