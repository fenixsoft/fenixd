# 验证报告：move-distill-trigger-to-push

> ⚠️ 本报告由框架于 2026-11-02T04:29:18Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。
> 报告时效标记（判定本报告是否属上一轮）：合成源轮次指纹：report.json@2026-11-02T04:29:17.154764+00:00+run-result@mtime1793593757204519797

## 结论：✅ 通过（verified）

**状态：verified — 23/23 场景通过，0 失败，0 错误（全部场景通过）**

全绿快道: 23/23 场景通过、0 失败 0 警告——无分类对象，跳过 judge 机械 verified

| 指标 | 数量 |
| --- | --- |
| 通过 | 23 |
| 失败 | 0 |
| 错误 | 0 |
| 产品 Bug | 0 |
| 本链增量 Token（输入） | 0.61M |
| 本链增量 Token（输出） | 0.08M |


## 场景结果

| 场景 | 描述 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- | --- |
| push-approve-dispatch-on-success | push 触发派发·成功转移：done 状态 SPEC 经 PmEngine.approve_push 成功转移为 pushed 后，以该 SPEC 名恰好调用一次注入的 distill 派发替身，approve_push 返回 True 且状态落账 pushed（人工 fenix-approve 与 _auto_approve 双路汇聚的单点写点；出处 core/pm_engine/engine.py:3235 approve_push，SPEC specs/distill-push-trigger/spec.md「approve_push 成功即派发」，任务 1.1） | pass | 0/4 | - |
| push-idempotent-replay-no-dispatch | push 触发派发·幂等边界：SPEC 已是 pushed 时 approve_push 幂等 skip 分支返回 True 且不派发蒸馏（同一 pushed 生命周期至多一次触发，git push 与项目日志零调用；出处 engine.py:3258 幂等 skip 分支，SPEC「幂等回放不重复派发」，任务 1.1） | pass | 0/2 | - |
| push-guarded-branches-no-dispatch | push 触发派发·早退分支不派发：非 done 状态（转移被拒）、push 退避期内跳过、SPEC 不存在三个早退分支均返回 False 且不派发蒸馏（出处 engine.py:3254/3266/3273 早退分支，SPEC 幂等边界第 2 条，任务 1.1） | pass | 0/4 | - |
| push-dispatch-exception-fail-open | push 触发派发·fail-open：蒸馏派发替身抛异常时 approve_push 仍返回 True、状态照常转移 pushed（派发任何异常不影响主流程返回值与状态转移结果，与归档触发时代 fail-open 口径一致；出处 engine.py:3347 transition 与任务 1.1 fail-open 要求） | pass | 0/2 | - |
| push-reopened-respec-dispatch | push 触发派发·打回重做重新蒸馏：已 pushed 且已派发的 SPEC 打回重做（update_spec 直写非终态）回 done 后再次 approve_push 成功，作为新 pushed 生命周期重新派发蒸馏（知识页按幂等更新语义覆盖更新；出处 design.md D5 语义边界表，SPEC「打回重做后再次 push 重新蒸馏」） | pass | 0/3 | - |
| archive-move-no-dispatch-compat | 归档不再触发：commit_archive_move 完成归档移动与 git 提交后不再派发蒸馏（distill 恒 None），且返回结构保留 distill 键兼容既有消费方——git 仓库正常路径与非 git 仓库提前返回路径双态核对（出处 core/archive_commit.py:37 commit_archive_move 与 docstring 返回契约，任务 1.2，SPEC「归档不再触发」） | pass | 0/4 | - |
| gate-changes-state-pass-prompt | 蒸馏输入双态解析·push 态：SPEC 在 spec/changes/（未归档）时 _gate_distill 放行，build_distill_prompt 动态段给出 changes/ 真实绝对路径且措辞由「本次待蒸馏的归档」改为「本次待蒸馏的 SPEC」（出处 core/knowledge.py:2103 _gate_distill、:586 build_distill_prompt，任务 2.1，SPEC「push 触发读 changes 目录」） | pass | 0/4 | - |
| gate-archive-fallback-pass-prompt | 蒸馏输入双态解析·归档兜底态：仅 spec/archive/<名> 存在（push 后蒸馏失败入 pending、恢复重派时 SPEC 已被时效归档）时门控兜底放行、prompt 动态段指向归档目录绝对路径（出处 knowledge.py:2103 双态探测 changes/ 优先 archive/ 兜底，SPEC「恢复重派兜底归档目录」，任务 2.1） | pass | 0/3 | - |
| gate-missing-both-rejected | 蒸馏输入双态解析·双缺拒绝：SPEC 名在 changes/ 与 archive/ 均无目录时拒绝派发，reason 保留 archive-dir-missing 字面量（单条形态原样返回、批量形态含缺失名单）（出处 knowledge.py:2142 reason 字面量兼容既有消费方，SPEC「双态均缺失拒绝」，任务 2.1） | pass | 0/3 | - |
| recover-pending-dual-state | 恢复重派双态探测：pending 台账两批（一批 SPEC 已归档、一批仍在 changes/）经 DistillManager.recover_pending 恢复重派均放行（恢复数=2），已归档批 prompt 兜底指向 archive/ 目录、changes 批 prompt 指向 changes/ 目录，批正常入队执行（出处 knowledge.py:2027 recover_pending 走同一门控链，任务 4.1，SPEC「恢复重派兜底归档目录」） | pass | 0/3 | - |
| distill-template-push-contract | 蒸馏模板 push 语境契约：distill.md 开篇语境改为 SPEC 刚 push 完成进入终态、sources 行与溯源链接契约改指 spec/changes/<名>/、溯源行保持全角括号纯文本形态不引入 markdown 链接形态（](spec/ 字样必须绝迹），动态段「本次待蒸馏的 SPEC」措辞同步（出处 core/knowledge_prompts/distill.md 与 design.md D4 模板↔_check_links 一致性要求，任务 2.2） | pass | 0/3 | - |
| archive-rewrite-e2e-cli-same-commit | 归档改写 pass·CLI 端到端：临时 git 项目内知识页溯源（marker sources 行 + 全角括号正文行）指向 spec/changes/rew-spec，经 bin/fenix_archive.py 归档成功后页面全部改写为 spec/archive/<YYYY-MM-DD-名>，且知识页改动与归档移动同入单一 [fenix] archive: 提交（subject 语义不变；出处 bin/fenix_archive.py:62,158、core/archive_commit.py:137，任务 3.1/3.2，SPEC「归档时知识页链接迁移」） | pass | 0/3 | - |
| archive-rewrite-prefix-boundary | 归档改写 pass·前缀同名右边界：知识页同时引用 spec/changes/merge-back 与 spec/changes/merge-back-precheck，仅归档 merge-back 后前者（sources 与正文）改写为归档路径、后者原样保留（替换匹配带名字右边界，后随非 [A-Za-z0-9._-] 字符或串尾方算命中，防前缀同名 SPEC 误伤；出处 design.md D3 右边界规则，任务 3.1） | pass | 0/2 | - |
| soft-delete-rewrite-naming-agnostic | 归档改写 pass·软删除路径：soft_delete_spec 软删除 SPEC（归档命名 <名>-<Unix秒>）成功后，知识页 sources 与正文同样改写为实际归档目录名（改写器按实际归档目录名注入、与命名方案无关，软删除也是归档移动；出处 core/dashboard/data/spec_archive.py:103,404，任务 3.2，SPEC「归档时知识页链接迁移」） | pass | 0/2 | - |
| validate-knowledge-two-state | 链接门两态等价：validate_knowledge 对 changes 态（sources 指向真实存在的 spec/changes/<名>）与 archive 态（归档改写后）均零违规；sources 指向不存在目录仍报违规、越界穿透（../ 形态）仍被复核拦截（防穿透强度不降）；spec/knowledge/ 未初始化空状态零违规（出处 core/knowledge.py:268 validate_knowledge、:447-465 sources 分支放宽为两态前缀合法，任务 3.5，SPEC「链接门两态不误报」） | pass | 0/6 | - |
| pytest-move-distill-new-file | 专项测试文件回归：tasks.md 要求新增的 tests/test_move_distill_trigger_to_push.py 全量通过（触发迁移/双态解析/改写器边界/两态校验等专项用例；出处 tasks.md 3.1/3.4 交付要求；文件缺失或用例失败即场景失败） | pass | 0/3 | - |
| pytest-approve-push-coupling | 审批推送测试回归：tests/test_spec_approve_push.py 全量通过（成功转移→派发被调用一次、幂等回放/非 done/退避期→不派发、派发抛异常→approve_push 返回值与状态转移不变；出处 tasks.md 1.3） | pass | 0/3 | - |
| pytest-knowledge-two-state | 知识蒸馏门控测试回归：tests/test_knowledge.py 全量通过（push 态门控放行+prompt 路径、归档态兜底、双缺 reason、模板契约段与 _check_links 一致性、两态 sources 用例；出处 tasks.md 2.3/3.5） | pass | 0/3 | - |
| pytest-spec-archive-rewrite | 归档改写测试回归：tests/test_spec_archive.py 全量通过（归档→改写落库同提交、改写异常→归档照常+告警留痕（fail-open，SPEC「改写失败不阻塞归档」）、dashboard archive_spec 与 soft_delete_spec 调用点接线；出处 tasks.md 3.4） | pass | 0/3 | - |
| pytest-resume-dual-state | 恢复重派测试回归：tests/test_knowledge_distill_resume.py 全量通过（pending 批 SPEC 已归档→双态兜底命中 archive/、批正常执行；SPEC 仍在 changes/→按 changes/ 执行；出处 tasks.md 4.1） | pass | 0/3 | - |
| pytest-distill-family-regression | 蒸馏族全量零回归：test_knowledge 族（含 audit/backfill/config/resume/run_artifacts/e2e/lanes_e2e）与 test_dashboard_knowledge_api 全部通过（触发源迁移不得破坏批生命周期、run 产物、回填排队、flock 单飞、修正轮既有语义；出处 tasks.md 4.2） | pass | 0/2 | - |
| compileall-core-bin | 语法完整性：python3 -m compileall -f core/ bin/ 全量强制重编译通过（交付面涉及 7 个源文件改动，编译门兜底语法/缩进错误；出处 tasks.md 4.2） | pass | 0/3 | - |
| pytest-archive-family-regression | 归档族与推送族零回归：test_spec_archive / test_spec_archive_drain / test_spec_approve_push / test_daemon_lifecycle_races 全部通过（approve_push 既有幂等/单飞/退避语义不受派发挂载影响，归档提交与 merge-back 残留语义不变；出处 tasks.md 4.2） | pass | 0/2 | - |

## 本轮场景集变更

当前稳定场景集共 23 个（第 1 轮）。

- 首轮写入 23 个场景

