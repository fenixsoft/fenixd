# 验证报告：add-code-fix-manual-trigger

> ⚠️ 本报告由框架于 2026-09-22T11:58:00Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。
> 报告时效标记（判定本报告是否属上一轮）：合成源轮次指纹：report.json@2026-09-22T11:58:00.483210+00:00

## 结论：✅ 通过（verified）

**状态：verified — 17/17 场景通过，0 失败，0 错误（全部场景通过）**

全绿快道: 17/17 场景通过、0 失败 0 警告——无分类对象，跳过 judge 机械 verified

| 指标 | 数量 |
| --- | --- |
| 通过 | 17 |
| 失败 | 0 |
| 错误 | 0 |
| 产品 Bug | 0 |
| 本链增量 Token（输入） | 8.59M |
| 本链增量 Token（输出） | 0.08M |


## 场景结果

| 场景 | 描述 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- | --- |
| api-fix-run-unknown-project-404 | 「手动修复触发信号端点」项目不存在 404：对未注册项目 ghost-404-no-such 调 POST /api/code-review/fix-run 与 GET /api/code-review/fix-run-result 均 MUST 返回 404 （project not found），不写任何信号/结果文件（spec 手动修复触发信号端点；出处 core/dashboard/routes/code_review_routes.py:182-185、249-252）。 | pass | 0/3 | - |
| cli-fixture-signal-baseline-reset | live 链路基线复位（幂等夹具治理）：停掉 scheduling-showcase 遗留 daemon/supervisor，删除 code_fix_request.json / code_fix_request_result.json / code-review/items.jsonl，使夹具处于「stopped + 0 open 条目 + 无信号」确定基线（后续 live 消费将确定性落 no_open_items 拒绝、不派真实 agent 批；夹具由 .fenix/verify.yaml prepare 的 bin/fixture_scheduling_showcase.py 供给于 /root/scheduling-showcase）。出处 core/fenix_session.py:302-324（hosting_state）。 | pass | 0/5 | - |
| cli-checkpoint-override-bypasses-enabled | 「手动触发即临时授权」bypass 语义 + 既有路径回归（进程内验证，不派真实 agent）：enabled=false 时 checkpoint() 不传参 → disabled 且零副作用（不写进度文件，既有两路后台激活行为不变）；同一编排器 checkpoint(override_enabled=True) → triggered=true/dispatched、批选取 5/5 条、进度 running=true——临时授权只绕过总开关。（spec 手动触发即临时授权 总开关关闭时手动触发仍投递 + 既有后台激活路径行为不变；出处 core/code_fix.py:480-524、499）。 | pass | 0/6 | - |
| cli-checkpoint-override-preserves-guards | 「临时授权不授权跳过安全链」override_enabled=True 下其余守卫逐一生效（进程内）：在飞 code-fix- run → already_running；0 open 条目 → no_open_items；无 verify.yaml → regression_contract_missing（进度 blocked）；verify.yaml 缺 regression 段 → regression_section_missing（进度 blocked）——单飞/无条目/回归契约 fail-closed 均不因手动触发放宽。（spec 手动触发即临时授权 已有修复在跑时拒绝/无待修条目时拒绝/回归契约缺失时拒绝；出处 core/code_fix.py:503-577）。 | pass | 0/5 | - |
| cli-consume-function-contract | 「daemon 消费函数契约」进程内验证 _check_code_fix_requests（FenixDaemon.__new__ 最小装配 + monkeypatch PROJECT_ROOT，与 tests/test_code_fix_manual_trigger.py 同构）：spy 编排器收到 override_enabled=True；结果文件 request_created 回链信号 created；信号先读后删（消费后不存在）；编排器未装配 → orchestrator_missing 结果（不静默）；checkpoint 抛异常 → dispatch_exception 结果；损坏信号 JSON → 删除防卡死、不落结果、不触发 checkpoint。（spec 触发判定结果反馈 编排器未装配不静默 + 结果按时间戳回链；出处 fenixd.py:2433-2525）。 | pass | 0/10 | - |
| api-fix-run-stopped-400 | 「daemon 不可消费时的前置拦截」stopped → 400：项目存在但 daemon 未运行时 POST /api/code-review/fix-run?project=scheduling-showcase MUST 返回 400 且文案为 「daemon 未运行，请先启动 daemon」，不写信号（对齐 POST /api/code-review/run 消费方守卫；spec 手动修复触发信号端点；出处 core/dashboard/routes/code_review_routes.py:202-204）。 | pass | 0/2 | - |
| api-fix-run-result-default-empty | 「触发判定结果反馈」缺省态 MUST NOT 500：结果文件不存在时 GET /api/code-review/fix-run-result?project=scheduling-showcase 返回 200 + 空对象 （triggered/request_created 键均缺省，读侧兜底不抛错；spec 触发判定结果反馈；出处 core/dashboard/routes/code_review_routes.py:241-253、core/dashboard/data/code_review.py:67-82）。 | pass | 0/3 | - |
| cli-fixture-normalize-unmanaged | unmanaged 前置拦截编排：把 scheduling-showcase 归一为「裸 daemon 在跑、无 supervisor」（先停可能残留的受托管 daemon，再 python3 .fenix/fenixd.py 直启，与事故现场同构），归一后 hosting_state MUST 为 unmanaged（先例 fix-supervisor-hosting-chain cli-normalize-showcase-unmanaged 同款）。出处 core/fenix_session.py:302-324（hosting_state）。 | pass | 0/4 | - |
| api-fix-run-unmanaged-409 | 「daemon 不可消费时的前置拦截」unmanaged → 409：裸 daemon（无 supervisor）时 POST fix-run MUST 返回 409 且文案指明「未受 supervisor 托管」（信号无人消费会永久滞留），且不写信号（spec 手动修复触发信号端点；出处 core/dashboard/routes/code_review_routes.py:195-201）。 | pass | 0/2 | - |
| cli-fixture-stop-bare-seed-stale-result | 停裸 daemon + 播种陈旧结果：stop_daemon 收口裸 daemon（hosting 回 stopped），断言 unmanaged 409 未写信号（前置拦截零副作用），并播种陈旧残留结果文件 request_created=stale-previous-round——供下一场景验证「受理前预删旧结果 + request_created 回链」双重防御（spec 触发判定结果反馈：陈旧残留 MUST NOT 被当本次反馈；出处 core/dashboard/routes/code_review_routes.py:206-211）。 | pass | 0/4 | - |
| api-fix-run-managed-accept-200 | 「受理成功」managed 项目 POST fix-run 返回 200：先经 POST /api/projects/scheduling-showcase/start 经 supervisor 托管拉起 daemon（ok=true），再 POST fix-run MUST 返回 200 + {ok:true, requested_at:UTC ISO}（信号文件被原子创建，由 daemon 主循环 1s 粒度消费；spec 手动修复触发信号端点 受理成功；出处 core/dashboard/routes/code_review_routes.py:213-239、core/dashboard/routes/project_routes.py:92-120）。 | pass | 0/5 | - |
| cli-fix-run-consume-result-no-open-items | 「daemon 消费 + 结果反馈」live 闭环：受托管 daemon 主循环（1s 粒度）消费 code_fix_request.json（先读后删）→ checkpoint(override_enabled=True) → 因夹具 0 open 条目确定性拒绝 no_open_items → 原子写回结果文件。轮询 15s 断言：信号已删（被消费）、request_created 非陈旧播种值（受理前预删旧结果 + 回链新信号）、triggered=false、reason=no_open_items、message 为「当前没有待修复的 open 问题」、finished_at 存在。（spec 手动触发即临时授权 无待修条目时拒绝 + 触发判定结果反馈；出处 fenixd.py:2461-2525、fenixd.py:2420-2431 消息映射、core/code_fix.py:518-524）。 | pass | 0/7 | - |
| api-fix-run-result-live-passthrough | 「触发判定结果反馈」只读透传 live 结果：GET fix-run-result 返回 daemon 刚写回的 真实判定（triggered=false、reason=no_open_items、message 中文文案逐字透传），非 mock、非缺省态（spec 触发判定结果反馈 被拒原因可见；出处 core/dashboard/routes/code_review_routes.py:241-253）。 | pass | 0/5 | - |
| api-fix-run-double-post-conflict-409 | 「并发或残留未消费信号」O_EXCL 独占创建 → 409：daemon 在跑时连续两次 POST fix-run，第一次受理 200，第二次因信号文件已存在（尚未被 1s 粒度主循环消费）MUST 返回 409 「已有未消费的修复触发请求（请稍后重试）」且 MUST NOT 覆盖已有信号（并发第二次 POST 形态；出处 core/dashboard/routes/code_review_routes.py:218-222）。注：若首次信号恰在两次请求间隙被消费（约 1s 窗口的天然竞态），本场景将失真——重跑即可，非产品缺陷。 | pass | 0/4 | - |
| cli-fix-run-consume-second-signal-cleanup | 消费第二个信号并归净夹具（为前端场景铺路）：等待上一场景写入的信号被 daemon 主循环消费（≤15s 轮询至文件消失），断言结果文件仍如实记录 no_open_items 拒绝——手动触发可重复使用（一次信号 = 至多一批，拒绝不排队；spec What Changes）。出处 fenixd.py:2461-2525。 | pass | 0/4 | - |
| web-quality-tab-fix-run-button-and-actions | 「前端按钮」质量页签动作按钮组含「立即自动修复」：navigate 项目页质量分面 (hash 路由 ?tab=quality)，断言「立即自动修复」「全仓库审查」「当期提交审查」三按钮可见（动作按钮组新增成员、既有按钮回归）；idle 夹具（0 open 条目、无在跑修复链）下自动修复进度卡片不渲染（CodeFixProgressCard.tsx:124-132 契约：!running 且非终态 return null 不占布局；「常驻挂载」指组件挂载点常驻 QualityTab.tsx:759-763，非卡片 DOM 恒可见）；按钮不被遮挡可点。（spec 前端按钮与原因回显；出处 QualityTab.tsx:690-736、list.tsx:1322、routes.ts:25-28、config.ts:15）。【judge 原地修复 2026-09-22】原断言 element_visible 进度卡片与组件契约相反（idle 态必 return null），按契约修正为 element_not_exist，非弱化：同元素回归面保留、判定方向对齐产品契约。 | pass | 0/5 | - |
| web-quality-tab-fix-run-reject-message-toast | 「点击后受理并回显结果」端到端 UI 闭环：点击「立即自动修复」→ 前端调 fix-run 受理 → 1s 间隔轮询 fix-run-result（仅认 request_created 与本次 requested_at 一致的结果）→ daemon live 消费（夹具 0 open 条目确定性拒绝）→ message.warning 回显 daemon 文案「当前没有待修复的 open 问题」。该断言只能在回链匹配成功时通过——同时证明「陈旧残留 MUST NOT 被当本次反馈」的前端门控。（spec 前端按钮与原因回显 点击后受理并回显结果；出处 QualityTab.tsx:384-425（轮询与回链）、711-717（按钮）、fenixd.py:2420-2431（文案映射））。 | pass | 0/2 | - |

## 本轮场景集变更

场景集与持久化集一致，无变更。

