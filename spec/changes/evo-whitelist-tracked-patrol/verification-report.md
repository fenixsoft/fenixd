# 验证报告：evo-whitelist-tracked-patrol

> ⚠️ 本报告由框架于 2026-10-08T19:09:37Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。
> 报告时效标记（判定本报告是否属上一轮）：合成源轮次指纹：report.json@2026-10-08T19:09:37.164798+00:00+run-result@mtime1791486577190587552

## 结论：✅ 通过（verified）

**状态：verified — 8/8 场景通过，0 失败，0 错误（全部场景通过）**

全绿快道: 8/8 场景通过、0 失败 0 警告——无分类对象，跳过 judge 机械 verified

| 指标 | 数量 |
| --- | --- |
| 通过 | 8 |
| 失败 | 0 |
| 错误 | 0 |
| 产品 Bug | 0 |
| 本链增量 Token（输入） | 2.03M |
| 本链增量 Token（输出） | 0.04M |


## 场景结果

| 场景 | 描述 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- | --- |
| wl-patrol-index-removal-fires-major | 放行文件被移出索引即报（specs/whitelist-tracked-patrol/spec.md Requirement 1 Scenario 1）：夹具仓构造 .fenix/* 整体忽略 + !.fenix/verify.yaml 放行的白名单约定，git rm --cached 移出索引（盘上副本保持）后跑 MainTreeStrayWipSweeper.sweep——产生 whitelist_untracked 信号（status=alerted、severity=major、文件清单恰为 .fenix/verify.yaml）；该放行项不计入散件计数（untracked 键不出现，negation 豁免语义不变两流互不污染）；落盘记录 evidence 以「项目名=」开头且「文件清单(1):」段可被 parse_stray_wip_manifest 解析、放行规则快照随 evidence 下发；description 写明 negation 放行即声明入库意图、recommended_action 含 git add 恢复入库与删除放行规则二选一；盘点零触碰工作区。探针装配对齐 tests/test_stray_whitelist_untracked.py 的 _WmProbe 同款。出处：core/worktree_manager/stray_wip.py:63、:368-369、:762-960；core/admin_store.py evidence_project；core/dashboard/data/admin_actions.py parse_stray_wip_manifest | pass | 0/16 | - |
| wl-patrol-tracked-no-false-positive | 正常白名单文件不误报（spec.md Requirement 1 Scenario 2）：tracked 白名单文件（!.fenix/verify.yaml 放行且在索引中）与真散件 build.log 共存时 sweep——白名单流 clean 零告警（files=[]、AdminStore 无 whitelist_untracked 记录）；真散件照常进既有 untracked 散件流（files=[build.log]）；.fenix/verify.yaml 不被裹挟进散件清单（negation 豁免语义回归不变）；工作区零触碰。出处：core/worktree_manager/stray_wip.py:368-369（sweep 附加键）、:505-506（豁免语义保持不变） | pass | 0/7 | - |
| wl-patrol-dedup-evolve-reset | 重复盘点不重复告警（spec.md Requirement 3 同指纹去重）：放行文件移出索引后同 sweeper 连续两轮 sweep——仅首轮 alerted（告警数 1），次轮 recorded 且告警数不增（同指纹一次性）；白名单文件内容演化（新指纹）后再报（告警数 2、指纹改变，演化不被旧指纹吞掉）；git add 恢复入库后 clean 且 _whitelist_registry 自动复位（指纹消失自动复位）；同脱落形态再现（同内容同指纹）复位后可再报（告警数 3，未被旧 escalated_at 拖住）。出处：core/worktree_manager/stray_wip.py:812-876（指纹注册表分账独立 + 复位） | pass | 0/13 | - |
| wl-patrol-conservative-abandon-gate | 异常路径——保守放弃与 ls-files 求交门：check-ignore 批量明细不可用（detail=None）时白名单流整流放弃（_whitelist_signal 返回 status=abandoned、不写告警、注册表保持空——保守语义与 tracked/untracked 流同款，条目保留交下轮）；求交门过滤「命中放行规则但在 git 索引中」的 tracked 路径（不构成脱落候选，判定自洽）；detail 缺失时 _whitelist_untracked_entries 返回 None（调用方按放弃本流处置）。出处：core/worktree_manager/stray_wip.py:762-806、:828-834 | pass | 0/6 | - |
| wl-patrol-signal-registration-invocation | 信号唤起与裁决（spec.md Requirement 2 信号接入唤起）：三表登记完备——SIGNAL_SEVERITY[whitelist_untracked]=major 且与 maintree_untracked_stray_escalated 先例同级、SIGNAL_RECOMMENDATION 文案写明「negation 放行即声明入库意图」与 git add/删除二选一处置、whitelist_untracked 收录 STORED_SIGNAL_TYPES（三表缺一即不唤起）；摄取唤起端到端——AdminMonitor._detect_family_explosion 对 spec=None 记录按 evidence「项目名=」段解析出项目名（摄取项目名解析清单收录本类型，漏加即落空）、唤起 Administrator 恰一次、mark_escalated 留痕、二次摄取不重复。出处：core/admin_monitor.py:372、:470、:576、:2579 | pass | 0/12 | - |
| wl-patrol-unit-suite-green | 交付单测套件全绿（tasks.md 3.1）：python3 -m pytest tests/test_stray_whitelist_untracked.py -v --tb=short 8 例全通过——不误报/必报不计散件/同指纹一次性演化复位/求交门/保守放弃/三表登记/落盘记录可摄取形态/摄取唤起端到端（断言文案照抄 -v 实测输出行，无 -q 不并存）。出处：tests/test_stray_whitelist_untracked.py（用例名经实测核对，非 parametrize 无后缀） | pass | 0/10 | - |
| wl-patrol-knowledge-audit-crossref | 约定互引（tasks.md 2.2）：core/knowledge_audit.py 白名单注释补指向 whitelist_untracked 巡检——「白名单入库意图由 stray_wip 白名单脱落巡检机械核查（evo-whitelist-tracked-patrol 2.2：whitelist_untracked 信号，core/worktree_manager/stray_wip.py）」，使「白名单应入库」约定与执行机制互为引用（断言文案取自实测 grep 行，注释跨行处拆为单行稳定子串）。出处：core/knowledge_audit.py:78-79（裁决修复 2026-10-08：xref 步骤 grep -n → grep -n -A1——注释跨行 78-79，原命令仅回显匹配行 78 致续行 79 上的 whitelist_untracked/stray_wip.py 断言永不命中；扩取样面，5 条断言不变） | pass | 0/5 | - |
| wl-patrol-potplayer-verify-yaml-restored | 一次性处置回归（tasks.md 4.1）：/root/potplayer-base 的 .fenix/verify.yaml 处于 git 索引（ls-files --error-unmatch 退出 0），恢复提交留痕 c91213f 回归链（log 含「恢复 .fenix/verify.yaml 入库」），白名单其余文件 .fenix/todo.md 保持 tracked。环境依赖；无 fallback（处置目标为固定主机路径 /root/potplayer-base，实现轮提交 0bfcc8f 实测） | pass | 0/5 | - |
