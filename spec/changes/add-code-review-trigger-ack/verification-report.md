# 验证报告：add-code-review-trigger-ack

> ⚠️ 本报告由框架于 2026-09-24T03:01:26Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。
> 报告时效标记（判定本报告是否属上一轮）：合成源轮次指纹：report.json@2026-09-24T02:57:21.160547+00:00

## 结论：❌ 未通过（Bug Found）

**状态：bug-found — 19/20 场景通过，1 失败，0 错误（1 个真实产品 Bug）**

20 场景：19 PASS / 1 FAIL（cli-consume-branches-inprocess，2 条断言失败聚合同根因 1 个 bug）。产品缺陷：fenixd.py:2480-2483 投递主路径先 submit 后落 started，worker 快速失败的 failed 三态被 started 受理回执覆盖（无池兜底路径 2484-2488 顺序正确可对齐修复）；进程内复现坐实写入序列。其余 19 场景（夹具基线/只读端点缺省态与 404/损坏容错/透传/窗口守卫 409 与陈旧放行 400/running 守卫让位/前端受理等待端到端/live 闭环回链/单测回归）全部通过。

| 指标 | 数量 |
| --- | --- |
| 通过 | 19 |
| 失败 | 1 |
| 错误 | 0 |
| 产品 Bug | 1 |
| 本链增量 Token（输入） | 3.68M |
| 本链增量 Token（输出） | 0.07M |


## 真实产品 Bug

### BUG-01（severity=major）· json_output

- 关联场景：cli-consume-branches-inprocess
- 描述：code-review 手动触发判定回链：worker 快速失败（manifest 为空 / manifest 收集异常）落盘的 failed 三态结果被随后的 started 受理回执覆盖，最终结果文件错误停留为 started，违反 spec D2「failed 三态 MUST 落盘可读」契约，前端将把失败误显示为「审查已受理，正在启动」
- 根因：fenixd.py:2480-2483 投递主路径先 submit(_worker_with_flag) 再落 started 受理回执；worker 快速失败（manifest_empty/manifest_error）时其 failed 落盘先于 started 发生，随即被主线程 started 覆盖。进程内复现写入序列 [('failed','manifest_empty'),('started',None)]，最终 status=started。无池兜底路径 fenixd.py:2484-2488 已是先 started 后执行的正确顺序，主路径未对齐；修复方向：把 started 落盘移到 submit 之前
- 证据（场景 cli-consume-branches-inprocess 结构化证据，引用）：
  - failed_assertions: [{"type": "json_output", "path": "manifest_empty_failed", "expected": true, "actual": false}, {"type": "json_output", "path": "manifest_error_failed", "expected": true, "actual": false}]
  - screenshots: []
  - first_failed_step: 步骤1(run) 分支f/g：worker 内联执行落 failed 后，fenixd.py:2483 主线程紧接着落 started 受理回执覆盖之，最终结果文件 status=started（复现写入序列 [('failed','manifest_empty'),('started',None)]）


## 场景结果

| 场景 | 描述 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- | --- |
| cli-fixture-baseline-reset | 夹具基线复位（幂等夹具治理）：停掉 scheduling-showcase 遗留 daemon/supervisor，删除 code_review_request.json / code_review_request_result.json / .fenix/code-review/manifest-*.json / .fenix/runs/code-review-*.jsonl，使夹具处于「stopped + 无信号 + 无审查产物（progress.running=false）+ 无回链结果」确定基线（夹具由 .fenix/verify.yaml prepare 的 bin/fixture_scheduling_showcase.py 供给于 /root/scheduling-showcase）。出处 core/fenix_session.py:329/431（start/stop_daemon）、core/fenix_session.py:302-324（hosting_state）。 | pass | 0/6 | - |
| api-run-result-default-and-404 | 「结果只读端点」缺省态与未知项目：结果文件不存在时 GET /api/code-review/run-result?project=scheduling-showcase 返回 200 + 缺省态（requested_at/status 为 null，MUST NOT 500，形态对齐 _api_code_review_fix_run_result）；对未注册项目 ghost-proj-404 同端点返回 404。出处 spec code-review-trigger-ack「结果只读端点」、core/dashboard/routes/code_review_routes.py:321-333（fix-run-result 形态先例）。 | pass | 0/4 | - |
| cli-consume-branches-inprocess | 「daemon 回链写侧」消费函数七分支进程内契约（FenixDaemon.__new__ 最小装配 + monkeypatch PROJECT_ROOT/hosting_state/collect_manifest，与 tests/test_code_fix_manual_trigger.py 先例同构）：①守卫全过+submit 成功 → started、requested_at 回链信号、reason=null、单飞旗标保持置位（复位义务在 worker 收尾）；②单飞在跑 → dropped/already_running 中文 message、旗标不变；③hosting=stopped/unmanaged → dropped 区分 daemon_not_running/daemon_unmanaged；④submit 抛异常 → failed/submit_error 且既有单飞复位逻辑保持（旗标复位）；⑤manifest 为空 → failed/manifest_empty；⑥collect_manifest 抛异常 → failed/manifest_error；⑦全部落盘后 .fenix 无 *.tmp 原子写残留；信号文件各分支均被消费（先读后删）。出处 fenixd.py:2266-2413（_check_code_review_requests 控制流）、spec D2 三态落盘点位表。 | failed（已修正） | 2/22 | product-bug |
| cli-seed-corrupt-result-file | 播种损坏回链结果：向 .fenix/code_review_request_result.json 写入非 JSON 文本（daemon 处于 stopped，无消费方干扰），为读侧「损坏不 500」断言供夹具。 | pass | 0/3 | - |
| cli-pytest-code-review-tests | 交付物单测回归：运行 python3 -m pytest tests/test_code_review.py -v --tb=short（实现方按任务 4.1/4.2 新增的回链写侧三态/原子性/读侧缺省态/窗口守卫三分支单测随存量用例一并执行），断言退出码 0 全绿。出处 spec/tasks.md 4.1-4.2。 | pass | 0/2 | - |
| api-run-result-corrupt-default | 「结果只读端点」损坏容错：结果文件为损坏 JSON 时 GET run-result 仍返回 200 + 缺省态（requested_at/status 为 null），MUST NOT 500。出处 spec「结果只读端点」Scenario: 结果缺失返回缺省态。 | pass | 0/3 | - |
| cli-seed-dropped-result-fixture | 播种合法回链结果：覆盖写入 status=dropped、reason=already_running、固定 requested_at=seed-req-20260924-001、中文 message、finished_at 的结果文件，为只读透传断言供夹具。 | pass | 0/5 | - |
| api-run-result-passthrough-dropped | 「结果只读端点」原样透传：结果文件存在且为合法 JSON 时，GET run-result 原样返回其内容（status=dropped、reason=already_running、requested_at 与 message 逐字一致）。出处 spec「结果只读端点」Scenario: 结果可读。 | pass | 0/5 | - |
| cli-seed-fresh-started-result | 播种新鲜 started 回链结果：覆盖写入 status=started、reason=null、finished_at=当前 UTC（新鲜，距今 <<900s），且确认无审查产物（progress.running=false），构成「已受理但 run 未开始」受理窗口态。 | pass | 0/5 | - |
| api-ack-window-fresh-started-409 | 「触发端点受理窗口守卫」窗口内重复触发被显式拒绝：先 POST /api/projects/scheduling-showcase/start 拉起受托管 daemon，再 POST /api/code-review/run（query project + body scope=full）——回链结果 started 且 progress.running=false 且 finished_at 新鲜，MUST 返回 409 + 稳定错误码 code_review_ack_pending。出处 spec「触发端点受理窗口守卫」Scenario: 窗口内重复触发被显式拒绝、fenixd 任务 2.3、core/dashboard/routes/code_review_routes.py:91-146（既有守卫序）。 | pass | 0/4 | - |
| cli-ack409-sideeffects-and-seed-running | 409 零副作用断言 + 运行中夹具播种：断言 409 拒绝未写信号文件（.fenix/code_review_request.json 不存在）且回链结果未被触碰（仍为播种的 started 内容）；随后删除结果与旧产物，写入 manifest-code-review-<now>.json + 非终态 .fenix/runs/code-review-<now>.jsonl（mtime 新鲜）并进程内复核 core.code_review.read_progress 判 running=true，再播种新鲜 started 结果——为既有 running 守卫先命中场景供夹具。出处 core/code_review.py:740-816（read_progress running 判据：末行 type 非终态 + mtime 未超 stale 阈值）。 | pass | 0/6 | - |
| api-guard-running-precedence-409 | 「窗口守卫让位既有错误码」：progress.running=true（播种产物）时 POST /api/code-review/run，既有 running 守卫先命中，MUST 返回 409 + code=code_review_running（而非 code_review_ack_pending），既有守卫判定口径不变。出处 spec「触发端点受理窗口守卫」Scenario: run 已开始时守卫让位既有错误码、core/dashboard/routes/code_review_routes.py:113-117（running 守卫）。 | pass | 0/2 | - |
| cli-prep-stale-and-stop | 陈旧结果夹具编排：停掉夹具 daemon（hosting 归 stopped），删除播种的运行中产物（progress 复位 running=false），把回链结果覆盖为 started + finished_at=距今 1000s（>900s 新鲜度窗口）的陈旧值，进程内复核 read_progress.running=false 与陈旧播种读回一致。 | pass | 0/4 | - |
| api-ack-window-stale-passthrough-400 | 「陈旧结果不锁死触发」：回链结果 finished_at 距今超过 900 秒时 POST /api/code-review/run，窗口守卫 MUST 放行（不返回 code_review_ack_pending）——请求穿过窗口守卫后命中托管守卫（daemon stopped）返回 400「daemon 未运行」，证明陈旧 started 结果不永久锁死手动触发。出处 spec「触发端点受理窗口守卫」Scenario: run 结束后陈旧结果不锁死触发、design D3 新鲜度必要性的论证。 | pass | 0/2 | - |
| web-quality-tab-review-buttons-baseline | 质量页签动作按钮基线（交互候选前置态）：navigate 项目页质量分面（hash 路由 ?tab=quality），断言「全库审查」「当期审查」「自动修复」三按钮可见且触发按钮为可点（enabled）态、运行中进度卡片不存在（空状态：无审查在跑时 MUST NOT 渲染卡片）、无控制台错误。出处 core/dashboard/static/src/pages/projects/components/QualityTab.tsx:799-823（三按钮）、:845-860（progress?.running 门控卡片）。 | pass | 0/7 | - |
| cli-prep-e2e-clean-result | 端到端前置清理：删除回链结果文件与信号文件残留（陈旧播种值不参与端到端轮询匹配），断言两文件均不存在。 | pass | 0/3 | - |
| api-start-managed-confirm-clean | 端到端托管启动：POST /api/projects/scheduling-showcase/start 经 supervisor 托管拉起 daemon（ok=true），GET run-result 复核缺省态（requested_at=null）——干净基线进入前端受理等待态端到端场景。出处 core/dashboard/routes/project_routes.py（项目 start 端点）、add-code-fix-manual-trigger 先例同编排。 | pass | 0/4 | - |
| web-trigger-ack-flow-card-takeover | 「前端受理等待与分派反馈」端到端主链路：点击「全库审查」→ POST 200 后进入受理等待态——既有「已受理，daemon 将开始执行」假承诺 toast MUST NOT 出现，两个审查触发按钮在受理等待期间保持禁用（独立 ackPending 门控），随后轮询读到 started、progress.running=true 时既有「审查进行中」进度卡片自动接管展示（2s 进度轮询交接，无需额外操作）。该断言链只有在「requested_at 回链匹配本次触发 + started→running 分派」全部成立时才通过。出处 spec「前端受理等待与分派反馈」Scenario: started 后卡片接管/等待期间不可重复触发、QualityTab.tsx:410-417（handleTrigger 现状）、:799-813（触发按钮）、:845-860（进度卡片）。 | pass | 0/7 | - |
| cli-live-consume-started-closedloop | 「触发判定结果回链落盘」live 闭环：受托管 daemon 主循环（1s 粒度）真实消费上场景点击写入的信号 → 投递成功落 started 结果。轮询 25s 断言：信号文件已删（被消费）、结果 status=started、reason=null、requested_at 为新鲜 UTC ISO 回链（非任何播种标记值）、finished_at 存在。出处 spec「触发判定结果回链落盘」Scenario: 受理投递成功、fenixd.py:2266-2413。 | pass | 0/7 | - |
| cli-fixture-cleanup-stop-daemon | 夹具收尾：停掉 scheduling-showcase 受托管 daemon（后台审查 worker 随进程终止不再干扰其他验证），断言 hosting_state 归 stopped——夹具复位可复验。 | pass | 0/2 | - |


## 断言级豁免清单

以下失败断言被归类为非产品缺陷（不记产品 Bug），逐条列出供人工复核豁免是否掩盖真实缺陷（场景级一句话归因不足以复核）。

无非 product-bug 的被豁免失败断言。
