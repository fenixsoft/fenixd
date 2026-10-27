# 验证报告：evo-recurring-stray-remediation

> ⚠️ 本报告由框架于 2026-10-06T19:48:25Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。
> 报告时效标记（判定本报告是否属上一轮）：合成源轮次指纹：report.json@2026-10-06T19:48:24.806222+00:00+run-result@mtime1791316104841005734

## 结论：✅ 通过（verified）

**状态：verified — 14/14 场景通过，0 失败，0 错误（全部场景通过）**

全绿快道: 14/14 场景通过、0 失败 0 警告——无分类对象，跳过 judge 机械 verified

| 指标 | 数量 |
| --- | --- |
| 通过 | 14 |
| 失败 | 0 |
| 错误 | 0 |
| 产品 Bug | 0 |
| 本链增量 Token（输入） | 2.20M |
| 本链增量 Token（输出） | 0.05M |


## 场景结果

| 场景 | 描述 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- | --- |
| untrack-choice-registered | 裁决空间扩 untrack：maintree_stray_wip_stale 桶新增 untrack_stray_wip 选项，与 commit_stray_wip 并存不冲突、spec_scoped=False、resolve_choice 单源可解析且 action 语义为 untrack 根治（tasks 1.1；锚 core/dashboard/data/adjudication_choices.py:101-108 _COMMIT_STRAY_WIP 先例、:292-294 maintree 桶） | pass | 0/3 | - |
| untrack-executor-end-to-end | 一键根治生成物日志（spec.md Scenario 1）：临时仓库 seed 被 track 的生成物文件+含文件清单的信号记录，执行 untrack_stray_wip——文件脱离 git 索引、工作区内容保留、.gitignore 增加对应条目（无则创建）、独立提交只含根治改动、结果含文件清单与提交号（tasks 1.2；锚 core/dashboard/data/admin_actions.py:2765 _exec_commit_stray_wip 先例、:2879 execute_adjudication_choice） | pass | 0/3 | - |
| untrack-signal-type-guard | 非 maintree 散件信号拒绝该选项（spec.md Scenario 2）：以姊妹信号 maintree_untracked_stray_stale 与空 signal_type 调用 untrack 选项均被拒绝，主树 git 状态零改动（文件仍 tracked、无新提交、.gitignore 不落盘、工作区原样）——沿 commit 执行器 D4 fail-closed 先例 | pass | 0/3 | - |
| untrack-gitignore-dedup | .gitignore 追加去重（design D4）：条目已存在时不重复写（同条目仅 1 行），且不破坏既有 ignore 规则，untrack 与独立提交仍正常完成（tasks 1.2「.gitignore 追加（已存在则去重）」） | pass | 0/3 | - |
| untrack-refuses-without-manifest | 文件来源单源守卫：store 无含可解析「文件清单(N):」段的 maintree_stray_wip_stale 信号记录（空 store；或仅有姊妹信号记录）时拒绝执行并返回明确 error、零 git 写——拒任意路径，清单单源与 commit 执行器同契约 | pass | 0/3 | - |
| untrack-scope-limited-to-manifest | 作用面限告警指认清单（design 风险缓冲「作用面限于告警指认文件清单，误伤面最小」）：仓库同时存在清单外的 tracked 改动文件时，untrack 只处理清单内文件，清单外文件保持 tracked 脏且不被裹挟进根治提交（tasks 1.2「对告警指认文件清单执行」） | pass | 0/3 | - |
| first-alert-no-recurrence-marker | 首次处置维持现状（spec.md Scenario「首次处置维持现状」）：真实 _write_alert 发射路径（stray_wip.py:672）对同文件首次发射的告警，evidence 不带「已 N 度处置」计数，choices 快照含既有 commit_stray_wip 与新增 untrack_stray_wip，文件清单段可解析（tasks 2.1） | pass | 0/3 | - |
| second-alert-carries-count-and-guidance | 第二次处置触发根治义务（spec.md Scenario）：同文件第 2 次经真实 _write_alert 发射告警，evidence 含「已 2 度处置」计数（admin_alerts 同文件历史口径）与指向 untrack 选项的根治指引（tasks 2.1） | pass | 0/3 | - |
| third-alert-count-generates | 复发计数按 N 泛化（tasks 2.1「已 N 度处置」）：同文件第 3 次发射告警，evidence 含「已 3 度处置」；第 2 次记录仍为「已 2 度处置」（计数随次数递增、不串档） | pass | 0/3 | - |
| admin-contract-iron-rule | admin 处置契约铁律（tasks 2.2；锚 agents/administrator.md:110 裁决选项消费、:118 铁律区）：契约新增复发型主树散件条款——提及 untrack_stray_wip 根治选项、同文件第 2 次处置起的触发条件、禁止「仅提交」收尾义务表述、首次处置维持「提交+建议」现状 | pass | 0/3 | - |
| adjudication-choices-test-suite | 交付物测试套件（tasks 3.1）：tests/test_adjudication_choices.py 扩 UNTRACK_STRAY_WIP 用例（选项注册/resolve、signal_type 绑定守卫、与 _COMMIT_STRAY_WIP 并存不冲突）全绿——-v 输出含 passed 汇总且退出码 0 | pass | 0/2 | - |
| stray-untrack-remediation-test-suite | 交付物测试套件（tasks 3.2）：新建 tests/test_stray_untrack_remediation.py（临时仓库端到端：seed 生成物→执行选项→脱离索引/.gitignore 增行且重复执行不重复写/独立提交/结果含清单与提交号；复发计数：同文件两次告警后 evidence 含「已 2 度处置」）全绿——-v 输出含 passed 汇总且退出码 0 | pass | 0/2 | - |
| commit-stray-wip-regression | 回归点：新增 untrack 选项后既有 commit_stray_wip 一键提交路径不回归（evo-add-commit-stray-wip-choice 既有行为）——清单内散件正常提交、工作区收敛干净、结果附提交 hash | pass | 0/3 | - |
| untrack-closes-recurrence-loop | 根治闭环回归点（spec.md Scenario 1 尾句「此后该文件改动不再产生 maintree 散件告警」）：真实盘点流全链路——sweep（宽限 0）发射告警→untrack 根治→同文件再改动→复扫 clean、信号记录数不增：检测面零改动下由 untrack+.gitignore 自然止损（tasks 1.2+2.1；锚 core/worktree_manager/stray_wip.py:195-224 sweep、:270-374 tracked 流） | pass | 0/3 | - |

## 本轮场景集变更

当前稳定场景集共 14 个（第 1 轮）。

- 首轮写入 14 个场景

