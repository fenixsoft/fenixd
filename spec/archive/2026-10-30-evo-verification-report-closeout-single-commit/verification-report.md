# 验证报告：evo-verification-report-closeout-single-commit

> ⚠️ 本报告由框架于 2026-10-10T17:42:12Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。
> 报告时效标记（判定本报告是否属上一轮）：合成源轮次指纹：report.json@2026-10-10T17:42:11.712875+00:00+run-result@mtime1791654131753742501

## 结论：✅ 通过（verified）

**状态：verified — 12/12 场景通过，0 失败，0 错误（全部场景通过）**

全绿快道: 12/12 场景通过、0 失败 0 警告——无分类对象，跳过 judge 机械 verified

| 指标 | 数量 |
| --- | --- |
| 通过 | 12 |
| 失败 | 0 |
| 错误 | 0 |
| 产品 Bug | 0 |
| 本链增量 Token（输入） | 6.40M |
| 本链增量 Token（输出） | 0.08M |


## 场景结果

| 场景 | 描述 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- | --- |
| gate-synthesized-single-commit-with-section | synthesized 出口闸门合并提交：报告缺失时经 report_gate._ensure_verification_report 注入场景段渲染回调后放行，真实 git 临时仓中 HEAD 恰一次新提交、内容同时含报告本体与「本轮场景集变更」（首轮写入小节）、报告不再滞留工作区、pathspec 严格单文件。需求1/需求2/验收1。源码证据：core/verify_report.py:1227（三出口 :1166/:1184/:1227 均先 _run_pre_commit 再 _commit_verification_report）、core/pm_engine/verification/report_gate.py:104（延迟导入注入 :119）、core/pm_engine/verification/scenario_gate.py:694（幂等标题判定）。 | pass | 0/8 | - |
| gate-present-single-commit-agent-body-kept | present 出口闸门合并提交：Agent 已写报告在盘（结论与本轮一致不被判残留），闸门回调渲染场景段后与 Agent 报告本体一并单次入库，HEAD 恰一次新提交、Agent 叙述原文保留（不被覆盖）、含「本轮场景集变更」、pathspec 严格单文件。需求1/需求2/验收1。源码证据：core/verify_report.py:1166（present 出口 _run_pre_commit 先于提交器）、:1163（_report_is_superseded=False 走 present）、core/pm_engine/verification/report_gate.py:119。 | pass | 0/7 | - |
| gate-resynthesized-single-commit-superseded | resynthesized 出口闸门合并提交：盘上报告为上一轮残留（手写结论行与本轮结构化数据矛盾，_report_is_superseded 判据二命中），闸门重合成覆盖后回调渲染场景段一并单次入库，HEAD 恰一次新提交、含新合成本体与「本轮场景集变更」、放行结论仍 ok、残留告警 WARNING 自带恰一条。需求1（三出口全覆盖）。源码证据：core/verify_report.py:1184（resynthesized 出口 _run_pre_commit 先于提交器）、:1181（残留 WARNING）、:460（_report_is_superseded 判据二：declared_verdict 与本轮 derive_status 矛盾）。 | pass | 0/9 | - |
| pre-commit-callback-exception-degrades-to-warning | pre_commit 回调抛异常降级：以 present 出口为载体（该出口闸门自身零 WARNING，WARNING 恰一条即回调异常本身），直调 ensure_verification_report 传入必抛回调——闸门仍放行（ok=True/action=present）、报告本体照常入库（提交恰 +1、HEAD 含 Agent 叙述、不含场景段标题）、WARNING 恰一条且含「pre-commit 回调失败」与异常消息。需求1/验收3。源码证据：core/verify_report.py:1134-1146（_run_pre_commit try/except Exception 仅 logger.warning 不阻断）、:1166-1168（异常后继续提交与放行）。 | pass | 0/8 | - |
| tail-rerender-after-gate-idempotent-zero-cost | 采纳尾段二次渲染幂等兜底：闸门（report_gate 真实注入路径）已合并提交后，模拟 pipeline 采纳尾段直调 _render_scenario_change_section_to_report——报告已含「本轮场景集变更」标题即零成本跳过，提交计数不增、日志记录零新增（含 WARNING）、无「入库失败」。需求3/验收2。源码证据：core/pm_engine/verification/scenario_gate.py:694（标题已存在即 return）、:705-723（写盘即入库提交器）、core/pm_engine/verification/pipeline.py:1232/:1408（尾段渲染点保留为兜底）。 | pass | 0/7 | - |
| gate-merged-commit-pathspec-isolated | pathspec 隔离回归：其它 spec 的在途草案（staged 的 spec/changes/other-spec-wip/tasks.md）与已跟踪文件未暂存修改（README.md）在场时闸门合并提交，HEAD 恰含本 spec verification-report.md 单文件、他 spec 草案仍 staged（A 状态）、README 修改仍未暂存（ M 状态）——草案不被卷入闸门提交。需求3/验收4。源码证据：core/verify_report.py:982（_commit_verification_report pathspec 精确单文件）、:1105（commit_verification_report 公开别名）。 | pass | 0/6 | - |
| default-no-callback-push-closeout-equivalent | 默认 None 向后兼容与 push 收口等价：ensure_verification_report 不传 pre_commit（push 收口等未传回调的调用方形态）时行为与现状逐字等价——报告入库单提交、无回调相关 WARNING；随后 push 收口直调 commit_verification_report（公开别名）对已入库 pathspec 幂等静默跳过，提交计数不增、零 WARNING。需求1（默认 None）/需求3。源码证据：core/verify_report.py:1137（pre_commit is None 直接 return）、:1105（commit_verification_report 公开别名直引同一实现）。 | pass | 0/8 | - |
| render-direct-call-write-then-commit-unchanged | 渲染函数直调「写盘即入库」行为不变：不经闸门、无 pre_commit 介入，直调 scenario_gate._render_scenario_change_section_to_report——报告获得「本轮场景集变更」小节且恰产生一次单文件提交（HEAD 含小节），幂等重复调用第二次跳过（提交不增）。需求3。源码证据：core/pm_engine/verification/scenario_gate.py:705-723（写盘即入库提交器）、:694（幂等跳过）、:714（公开别名 commit_verification_report）。 | pass | 0/6 | - |
| non-git-project-silent-skip | 非 git 项目静默跳过：被管项目根无 .git 时闸门照常放行（ok=True）、合成报告落盘在 spec/changes/<spec>/verification-report.md，但入库机制不适用——静默跳过，无「验证报告入库失败」WARNING、零噪声。需求3。源码证据：core/verify_report.py:982（提交器内建非 git 静默跳过）、tests/test_verification_report_commit.py:532（TestNonGitProjectSilentSkip 既有契约）。 | pass | 0/5 | - |
| four-adoption-callpoints-callback-injected | 四个采纳调用点回调注入静态取证：pipeline._apply_bug_found（core/pm_engine/verification/pipeline.py:1150）、_apply_verified（:1316）、legacy 两处（core/pm_engine/verification/legacy.py:408/:603）均经 pipeline._ensure_verification_report(spec_name) 进入 report_gate 注入路径（同一函数、同一 pre_commit 闭包），且 report_gate.py 确以 pre_commit= 注入渲染回调、pipeline.py:1232/:1408 尾段渲染点保留为兜底。需求2。源码证据：core/pm_engine/verification/report_gate.py:85/:104/:119、core/pm_engine/verification/pipeline.py:216/:327（函数注册为 pipeline 成员，legacy 共用同一入口）。 | pass | 0/7 | - |
| existing-test-suites-regression-green | 既有用例回归：tests/test_verification_report_commit.py（含既有 TestScenarioSectionCommit 直调渲染单文件提交、幂等跳过，TestNonGitProjectSilentSkip，以及本 spec 新增 TestGateMergedScenarioSectionCommit 合并形态五用例）与 tests/test_push_closeout_report_commit.py（push 收口路径）全量通过，退出码 0、25 passed。需求3/验收5。取证：2026-10-11 实跑「python3 -m pytest tests/test_verification_report_commit.py tests/test_push_closeout_report_commit.py -v --tb=short」输出「25 passed, 5 warnings in 2.25s」。 | pass | 0/8 | - |
| knowledge-doc-rules-rewritten | 知识库同步：spec/knowledge/domains/verify-pipeline/verification-report.md 已改写「场景段写盘即入库」与「入库挂点链」两条规则为「场景段渲染合并进闸门 pre-commit 挂点、采纳流程内报告相关提交至多一次」，溯源段补记本 spec（2026-10-11 evo-verification-report-closeout-single-commit），头部 sources 与 rev 元信息已更新。需求4。取证：文件实测含「场景段渲染合并进闸门 pre-commit 挂点」「采纳流程内报告相关提交至多一次」及溯源条目。 | pass | 0/6 | - |

## 本轮场景集变更

当前稳定场景集共 12 个（第 1 轮）。

- 首轮写入 12 个场景

