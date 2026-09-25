# 验证报告：add-cancelled-spec-resume-action

> ⚠️ 本报告由框架于 2026-09-21T14:27:56Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。
> 报告时效标记（判定本报告是否属上一轮）：合成源轮次指纹：report.json@2026-09-21T14:27:56.210560+00:00

## 结论：✅ 通过（verified）

**状态：verified — 20/20 场景通过，0 失败，0 错误（全部场景通过）**

全绿快道: 20/20 场景通过、0 失败 0 警告——无分类对象，跳过 judge 机械 verified

| 指标 | 数量 |
| --- | --- |
| 通过 | 20 |
| 失败 | 0 |
| 错误 | 0 |
| 产品 Bug | 0 |
| 本链增量 Token（输入） | 7.11M |
| 本链增量 Token（输出） | 0.05M |


## 场景结果

| 场景 | 描述 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- | --- |
| cli-seed-resume-fixtures | 种子场景：向 scheduling-showcase 夹具仓库写入本 SPEC 全部夹具——幂等建立 main 基线分支（动作内 rev-list main..branch 闸门需要，夹具仓库现状仅 master）；重建三条领先 main 一提交的保留分支 fenix/ch-resume-hit、fenix/ch-resume-hold-web、fenix/ch-resume-hit-rb（先摘 worktree、删分支再重建，保证 rev-list 非空）；为 ch-resume-hit / ch-resume-hold-web 预建在册 worktree（WT_AVAILABLE 原地续做——对应取消后清理链豁免、现场留存的常态），ch-resume-hit-rb 不建（载体缺失重建子路径由独立场景覆盖）；注入 STATE 夹具：ch-hold-detail(implementing+hold，供详情/列表可见性断言、从不恢复)、ch-resume-hit(implementing+hold+branch 锚点+implementer_run 锚点+陈旧 tester_run/_retry_count/_merge_streak/_redispatch_* 计数，供命中路径与收口字段归零断言)、ch-resume-hit-rb(implementing+hold+分支在位无 worktree，供重建子路径场景)、ch-resume-degraded(implementing+hold+无锚点，供降级路径)、ch-resume-nothold(ready+_cancelled_hold: False 文本字面量，供负例①幂等拒绝与摘要不误标)、ch-resume-frozen(blocked+frozen:True+hold，供冻结拒绝)、ch-resume-done(done+hold，供终态 403)、ch-resume-hold-web(implementing+hold+保留分支+worktree，供 web 展示/取消/成功确认)、ch-resume-degraded-web(implementing+hold+无锚点，供 web 降级提示)；全部非终态夹具 start_after 置 2030 防 daemon 调度漂移（恢复动作不触碰 start_after，保留闸门），并为列表可见性 mkdir spec/changes 目录（archived 过滤，pushed/done 无目录会被列表隐藏）。出处：夹具路径 /root/scheduling-showcase（复用 add-spec-status-modal-budget / add-spec-approve-push-modal 既有 fixture 项目）；STATE 写入经 core/state_machine.py:967 add_spec（_ 前缀字段经 serialize core/state_machine.py:456-461 持久化）；保留分支闸门 core/state_machine.py:1555-1559（rev-list main..branch 非空）；载体在场判定 core/worktree_manager/queries.py:228-263（find_worktree_path 以 git worktree list --porcelain 为真相）。 | pass | 0/10 | - |
| cli-unit-resume-actions | 后端单测回归：运行 tests/test_cancelled_spec_resume.py 全量 9 用例（命中写续做集+kick、降级不置 _recovery_resume、非保持态幂等拒绝、冻结拒绝、终态拒绝、not found、负例①文本 _cancelled_hold: False 归一化、负例②WorktreeManager 构造失败零变更、parse_state 归一化）——覆盖 wm 构造失败 fail-closed 与 scheduling_kick 文件存在性等实例场景不可稳定复现的分支（kick 文件会被 daemon 1s 粒度消费）。出处：tests/test_cancelled_spec_resume.py:81-290（def test_* 用例名逐一核对，非 parametrize，output_match 照抄用例名+PASSED）；动作实现 core/dashboard/data/admin_actions.py:639 resume_cancelled_spec。 | pass | 0/10 | - |
| api-resume-hit-preserved-branch | 功能正向·POST /api/spec-resume 命中保留分支续做（载体在场，WT_AVAILABLE 原地续做）：对取消保持态 SPEC（ch-resume-hit，implementing + _cancelled_hold:True + STATE.branch=fenix/ch-resume-hit 领先 main 一提交 + 该分支的在册 worktree 在场——对应 run 被人工取消后清理链豁免、现场留存的常态）调用，返回 200 + {ok:true, spec:ch-resume-hit}（degraded 键缺省=未降级；STATE 落点与 scheduling_kick 由 cli-assert-resume-state 与单测场景断言）。出处：core/dashboard/routes/base.py:349（POST /api/spec-resume 路由表）、core/dashboard/routes/spec_routes.py:346-399（_api_spec_resume 成功分支）、core/dashboard/data/admin_actions.py:639-720（命中分支写保留续做集）、core/worktree_manager/repair_site.py:85-90（WT_AVAILABLE 原地返回）。 | pass | 0/4 | - |
| api-resume-hit-rebuild-worktree | 功能正向·POST /api/spec-resume 命中保留分支续做（载体缺失，WT_REBUILDABLE 分支重建）：对取消保持态 SPEC（ch-resume-hit-rb，implementing + hold + STATE.branch=fenix/ch-resume-hit-rb 领先 main 一提交 + 无在册 worktree——worktree 被清理只剩分支的窗口）调用，验收预期 200 + {ok:true}：共享判定经 create_worktree_on_branch 在既有分支上重建载体后写保留续做集。当前实现有一处确定性缺陷：dashboard 侧 WorktreeManager 以 logger=None 构造（core/dashboard/data/admin_actions.py:701，与 unfreeze 先例 :389 同型），而重建路径 create_worktree_on_branch 成功/失败分支均无条件调 self.logger（core/worktree_manager/queries.py:205/212/221）→ AttributeError 未捕获 → 路由 500、STATE 零变更。本场景按 SPEC 验收断言（spec.md『载体可用』三态含可重建），失败即暴露该缺陷。出处：core/worktree_manager/repair_site.py:92（REBUILDABLE → create_worktree_on_branch）、core/state_machine.py:1567（resolve_resume_site 调用点）。 | pass | 0/3 | - |
| api-resume-degraded-fresh-dispatch | 功能正向·POST /api/spec-resume 降级全新重派：对取消保持态但三层锚点均不可得的 SPEC（ch-resume-degraded，branch=null、无在册 worktree、无同名分支）调用，返回 200 + {ok:true, degraded:true, reason 含「无可保留分支」}。出处：core/dashboard/routes/spec_routes.py:393-395（degraded 透传）、core/dashboard/data/admin_actions.py:721-748（降级分支：锚点清空、不置 _recovery_resume）。 | pass | 0/4 | - |
| api-resume-reject-non-hold | 异常路径·非取消保持态幂等拒绝（负例①）：对 _cancelled_hold 为 False 文本字面量（STATE 序列化 `- _cancelled_hold: False`，同存量条目真值字符串陷阱）的 ready SPEC（ch-resume-nothold）调用，返回 200 + {ok:false, reason 含「该 SPEC 并非取消保持态」}，STATE 零变更（由 cli-assert-resume-state 回归断言）。出处：core/dashboard/data/admin_actions.py:663-668（归一化判据拒绝）、core/dashboard/routes/spec_routes.py:383-392（200+reason 幂等拒绝路径）；归一化单点 core/dashboard/data/state.py:16 normalize_bool_flag。 | pass | 0/3 | - |
| api-resume-reject-frozen | 异常路径·冻结态拒绝恢复：对 frozen:True 且 _cancelled_hold:True 的 blocked SPEC（ch-resume-frozen）调用，返回 200 + {ok:false, reason 含「冻结 SPEC 须先解冻」}，禁止绕过冻结直接恢复。出处：core/dashboard/data/admin_actions.py:656-661（is_spec_frozen 入口拒绝）、core/dashboard/routes/spec_routes.py:383-392。 | pass | 0/3 | - |
| api-resume-reject-terminal | 异常路径·终态拒绝恢复（HTTP 403 语义）：对 done 终态且 _cancelled_hold:True 的 SPEC（ch-resume-done）调用，返回 403 + 文案含「终态」，STATE 零变更。出处：core/dashboard/data/admin_actions.py:651-655（terminal=True）、core/dashboard/routes/spec_routes.py:380-382（403 终态不可恢复）。 | pass | 0/2 | - |
| api-resume-404-unknown-spec | 异常路径·spec 不存在：对 scheduling-showcase 项目内不存在的 spec（ghost-no-such-spec）调用 POST /api/spec-resume，返回 404 + spec not found。出处：core/dashboard/routes/spec_routes.py:377-379（found=False → 404）、core/dashboard/data/admin_actions.py:647-649。 | pass | 0/2 | - |
| api-resume-404-unknown-project | 异常路径·project 不存在：对不在 dashboard registry 的项目（nonexistent-project）调用 POST /api/spec-resume，返回 404 + unknown project。出处：core/dashboard/routes/spec_routes.py:366-371（project 缺失/不存在 → 404）。 | pass | 0/2 | - |
| api-detail-cancelled-hold-true | 可见性·spec 详情下发 cancelled_hold=true：GET /api/specs/ch-hold-detail?project=scheduling-showcase（implementing + _cancelled_hold:True），详情响应 cancelled_hold 为 true、status 为 implementing——前端弹窗区块渲染判据的数据源。出处：core/dashboard/routes/base.py:301（regex ^/api/specs/([^/]+)$ → _get_spec_detail）、core/dashboard/data/summary.py:691（spec_detail cancelled_hold 归一化透传）。 | pass | 0/3 | - |
| api-detail-cancelled-hold-false | 可见性·非保持 SPEC 详情不误标（负例①数据面）：GET /api/specs/ch-resume-nothold?project=scheduling-showcase（ready + STATE 文本 `- _cancelled_hold: False` 真值字符串），详情响应 cancelled_hold 为 false——归一化口径防回归（裸 bool() 会把文本 False 误判 true）。出处：core/dashboard/data/summary.py:691 + core/dashboard/data/state.py:59-68（_cancelled_hold 登记进归一化表）。 | pass | 0/2 | - |
| cli-summary-list-cancelled-hold | 可见性·列表摘要按 spec 名下发 cancelled_hold：经 FENIX_VERIFY_BASE_URL 真实请求 GET /api/specs?project=scheduling-showcase，断言 ch-hold-detail 摘要 cancelled_hold=true、ch-resume-nothold 与存量 c-sched-set 摘要 cancelled_hold=false（列表为按 name 取值的字段级断言，json_path 无法按 name 索引故用脚本逐名校验，端点仍打真实实例不 mock）。出处：core/dashboard/routes/base.py:299（GET /api/specs）、core/dashboard/data/summary.py:344（列表摘要 cancelled_hold 字段）、summary.py:448（_ENTRY_SIG_KEYS 增列 _cancelled_hold，指纹缓存失效）。 | pass | 0/2 | - |
| web-hold-modal-resume-block | 功能正向·取消保持态 SPEC「修改状态」弹窗渲染「恢复运行」区块：打开 ch-resume-hold-web（implementing+_cancelled_hold:True）弹窗，区块含「恢复运行」标题、取消保持态说明（daemon 全部自动恢复链路跳过、需显式恢复）、「恢复会消耗一次实现尝试预算」预算明示、danger「恢复运行」按钮。出处：core/dashboard/static/src/pages/projects/components/SpecStatusModal.tsx:536-549（cancelledHold && nonTerminal 条件渲染区块）；渲染判据 :104（summary.cancelled_hold===true）；SPA 路由 core/dashboard/static/src/app.tsx:107（/projects/:name hash 路由）；列表入口 list.tsx:908（key:status 修改状态菜单）。 | pass | 0/6 | - |
| web-nonhold-modal-no-resume-block | 空状态/负向·非取消保持态 SPEC 弹窗不渲染恢复区块：打开 c-sched-set（ready、无 _cancelled_hold）弹窗，无「恢复运行」按钮，冻结等既有区块照常（回归）。出处：core/dashboard/static/src/pages/projects/components/SpecStatusModal.tsx:536（cancelledHold 判据不命中）；冻结区块 :588-599（nonTerminal 照常渲染）。 | pass | 0/5 | - |
| web-terminal-modal-no-resume-block | 负向·终态 SPEC 弹窗不渲染恢复区块：打开 c-sched-done（done 终态）弹窗，无「恢复运行」按钮，归档区块照常（回归）。出处：core/dashboard/static/src/pages/projects/components/SpecStatusModal.tsx:536（nonTerminal 判据不命中）、:571-585（done 归档区块）。 | pass | 0/4 | - |
| web-resume-confirm-degraded | 交互流程·确认后降级提示：ch-resume-degraded-web（无保留分支锚点）弹窗点击「恢复运行」→ 确认 → 返回 degraded:true → 独立 warning toast「无可保留分支，已降级全新重派」。出处：core/dashboard/static/src/pages/projects/components/SpecStatusModal.tsx:377-381（degraded 分支 message.warning）。 | pass | 0/4 | - |
| cli-assert-resume-state | 回归·恢复动作 STATE 落点逐字段断言（依赖 api-resume-hit 与 api-resume-degraded 已执行）：parse_state 读 scheduling-showcase STATE——ch-resume-hit 落 branch=fenix/ch-resume-hit、_recovery_resume:True、_cancelled_hold 归一 False、tester_run 清空、implementer_run 保留原锚点 impl-fixture-ch-hit、_retry_count/_merge_streak 归零、error 含「resume preserved branch」；ch-resume-degraded 落 branch=None、无 _recovery_resume、error 含「fresh dispatch」；拒绝场景零变更回归：ch-resume-nothold 仍 ready、ch-resume-frozen 仍 blocked、ch-resume-done 仍 done。出处：core/dashboard/data/admin_actions.py:705-718（命中续做集）、:721-745（降级集）、core/state_machine.py:728（携带 status 自动清 _cancelled_hold）。 | pass | 0/2 | - |
| web-resume-confirm-cancel | 交互流程·确认框取消不触发恢复：ch-resume-hold-web 弹窗点击「恢复运行」→ Modal.confirm 确认框弹出（标题「恢复运行 SPEC」、文案含「恢复会消耗一次实现尝试预算」与降级说明）→ 点击取消 → 修改状态弹窗保持打开、「恢复运行」按钮仍在、无任何「已复位 ready」消息（中间状态验证：API 未被调用）。出处：core/dashboard/static/src/pages/projects/components/SpecStatusModal.tsx:357-372（handleResume Modal.confirm 文案/按钮）。 | pass | 0/5 | - |
| web-resume-confirm-success | 交互流程·确认后恢复成功（保留分支续做）：ch-resume-hold-web 弹窗点击「恢复运行」→ 确认框点确认 → 真实调用 POST /api/spec-resume（禁止 mock 交付物端点）→ 成功 toast「已复位 ready，daemon 将在保留分支上续做」（非降级分支文案）；onDone 触发列表刷新（弹窗保持打开，恢复区块随刷新消失）。出处：core/dashboard/static/src/pages/projects/components/SpecStatusModal.tsx:373-390（onOk→resumeSpec→message.success :383）、services/dashboard.ts:499-503（resumeSpec POST 封装）。 | pass | 0/4 | - |

## 本轮场景集变更

场景集与持久化集一致，无变更。

