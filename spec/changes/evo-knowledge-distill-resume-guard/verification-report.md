# 验证报告：evo-knowledge-distill-resume-guard

> ⚠️ 本报告由框架于 2026-10-10T17:51:15Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。
> 报告时效标记（判定本报告是否属上一轮）：合成源轮次指纹：report.json@2026-10-10T17:51:15.230620+00:00+run-result@mtime1791654675265676939

## 结论：✅ 通过（verified）

**状态：verified — 14/14 场景通过，0 失败，0 错误（全部场景通过）**

全绿快道: 14/14 场景通过、0 失败 0 警告——无分类对象，跳过 judge 机械 verified

| 指标 | 数量 |
| --- | --- |
| 通过 | 14 |
| 失败 | 0 |
| 错误 | 0 |
| 产品 Bug | 0 |
| 本链增量 Token（输入） | 5.70M |
| 本链增量 Token（输出） | 0.06M |


## 场景结果

| 场景 | 描述 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- | --- |
| r1-dispatch-persists-pending-ledger | R1 正向·入队即落盘：DistillManager.dispatch 单条派发后 <proot>/.fenix/knowledge-distill-pending.json 立即存在，结构 {"batches":[{"names":[归档名],"queued_at":ISO时间戳}]}；同批多归档合并为一条（不拆条）；台账写入无 tmp 残留（tmp+os.replace 原子回写）。出处 core/knowledge.py:942-964（dispatch 写点）、:972-987（_ledger_append 读-改-原子回写）、:907-917（_write_pending_ledger）、:859（PENDING_LEDGER_NAME）、core/fs_utils.py:27（atomic_write_text mkstemp+os.replace） | pass | 0/10 | - |
| r2-gate-rejected-paths-no-ledger | R2 异常路径·门控拒绝与回填期排队不写台账：归档目录缺失（archive-dir-missing）、knowledge.enabled=false（disabled）、回填台账有 pending（backfill-queued，真实登记 core.knowledge_backfill 回填台账）三条路径 dispatched=False 且 pending 台账文件不落地、进程内队列零积压、蒸馏 run 零启动。出处 core/knowledge.py:1293-1359（_gate_distill 门控链）、:1387-1413（dispatch_distill 入口）、tasks 1.2 | pass | 0/10 | - |
| r1-corrupt-ledger-failopen-dispatch-unblocked | R1 异常路径·台账缺失/非法 JSON/顶层非 dict/batches 非 list/条目形态不合规全部按空表 fail-open 不抛异常（合法条目保留、非法条目跳过）；损坏台账上派发不受阻且追加后恢复合法 JSON；清空后恢复入口返回 0 不误派。出处 core/knowledge.py:871-904（_read_pending_ledger fail-open 口径）、spec R1「台账文件缺失、损坏或不可读时按空表处理」 | pass | 0/10 | - |
| r1-atomic-append-interleaved-no-loss | R1 并发·原子回写不丢条目：批量入口（3 归档合并为一条）与单条入口经双线程经屏障交错并发入队，最终台账 4 个归档名一条不少（同批多归档一条 + 单条一条）；收尾清除后无 .tmp 残留。出处 core/knowledge.py:972-1007（_ledger_append/_ledger_remove 整文件重读-过滤-原子回写防并发丢条目）、tests 3.2「原子回写在并发入队下不丢条目」 | pass | 0/6 | - |
| r2-success-commit-removes-entry | R2 正向·成功收尾对账：批次产出经校验通过并真实 git 落库（提交文案 "[fenix] knowledge: distill <归档名>"）后，pending 台账条目移除，且不误登重试台账。出处 core/knowledge.py:1102-1107（成功收尾 _ledger_remove）、:804-834（_commit_output）、tasks 1.3、SPEC 验收「完成后文件中该条目消失」 | pass | 0/6 | - |
| r2-nochange-closeout-removes-entry | R2 回归·无变更也算成功收尾：校验通过但工作区无变更（_commit_output 返回空串=无需新增/修改页面）时批次同样收尾——pending 条目移除、不产生空提交、不误登重试台账（code-review 1e83848b80f1 口径）。出处 core/knowledge.py:820-827（nothing to commit 视为无变更返回 ""）、:1102-1107（commit 含空串即移除条目）、tasks 1.3「含无变更」 | pass | 0/6 | - |
| r2-giveup-discard-confirmed-removes-entry | R2 异常路径·放弃产出+清理确认：校验违规经 3 轮 run（1+MAX_FIX_ROUNDS=2 修正轮）仍未通过 → _give_up → 工作区半成品被回滚清理（_discard_output=True）→ pending 条目移除 + todo.md 登记失败原因；蒸馏写面 spec/ 恢复干净。出处 core/knowledge.py:1142-1151（修正轮耗尽放弃）、:1192-1204（_give_up 清理确认后 _ledger_remove）、tasks 1.3、SPEC 验收「或放弃清理后文件中该条目消失」 | pass | 0/8 | - |
| r2-stalled-paths-keep-entry | R2 异常路径·三滞留路径条目必须保留（不得静默清除）：①校验通过但自动提交失败（重试仍失败）②执行异常（批次执行链抛异常）③run 失败且回滚未确认（_discard_output=False，半成品滞留）——三者 pending 条目均保留，且 todo.md 重试台账注明「将由 daemon 重启续跑接管」（_RESUME_TAKEOVER_NOTE 接管口径）。出处 core/knowledge.py:1116-1134（提交失败滞留）、:1022-1035（worker 执行异常）、:1205-1223（回滚未确认保留）、:864（_RESUME_TAKEOVER_NOTE）、tasks 1.3、SPEC 验收「校验通过但提交失败：条目保留 + todo 台账照旧」 | pass | 0/11 | - |
| r2-merged-batch-union-clear | R2 回归·合并批次清除粒度：首批在飞期间同项目连续再入队两条 → worker 把积压整体摘下合并为一次 run（spawn 共 2 次而非 3 次，合并批提示词含两个归档路径）→ 收尾按本批 names 并集一次清除全部 3 条台账条目（防漏清陈旧条目引发重启后重蒸）。出处 core/knowledge.py:989-1007（_ledger_remove 并集交集匹配一次清除多条）、:1010-1035（_worker 串行消费+批量合并）、tasks 1.3 | pass | 0/8 | - |
| r3-recover-clear-then-redispatch | R3 正向·恢复顺序 MUST 先清空后入队：空台账/缺台账 recover_pending 返回 0 且不创建台账文件；seed 混合条目（门控放行 + 归档目录缺失）恢复后返回 1、台账先被清空再由 R1 写点重新落盘（放行条目 queued_at 刷新证明非残留旧文）、门控拒绝条目不复活；恢复日志「恢复跳过」与「恢复重派（1 批：…）」落 fenixd.knowledge 日志。出处 core/knowledge.py:1226-1282（recover_pending）、tasks 2.1、SPEC R3「先清空台账文件、再经恢复入口逐条重新入队」 | pass | 0/9 | - |
| r3-restart-resume-end-to-end | R3 端到端·daemon 重启续跑（两独立进程，状态仅经盘上台账传递）：步 A 独立解释器播种夹具工程并写入崩溃残留 pending 台账；步 B 全新 python 进程（模拟 daemon 重启）initialize 恢复链路——recover_pending 返回 1、条目重新落盘、恢复批次经 worker 消费完成入库提交（"[fenix] knowledge: distill <归档名>"）、完成后台账条目消失、日志含恢复重派记录；恢复动作只重新入队不执行蒸馏（实际 run 走既有 worker 串行消费）。出处 core/knowledge.py:1226-1282（recover_pending）、fenixd.py:654-678（daemon initialize 末尾接入）、SPEC 验收「构造 daemon 重启：新进程 initialize 后该批次被重新派发并完成入库提交，日志含恢复记录」 | pass | 0/9 | - |
| r3-initialize-wiring-daemon-only | R3 接线·恢复入口仅 daemon 启动路径接入：FenixDaemon.initialize 源码末尾经 core.knowledge 模块单例访问器调用 recover_pending，异常降级 WARNING（non-blocking）不阻塞 daemon 启动；恢复数>0 落「台账恢复重派 N 批」日志；dashboard --serve 入口（bin/fenix_dashboard.py）与 core/dashboard 全树零 recover_pending 引用（避免双进程竞争）；recover_pending docstring 写明「先清空后入队」顺序与 dashboard 不接入口径。出处 fenixd.py:654-678（接入点+non-blocking 兜底）、core/knowledge.py:1226-1236（先清空后入队 docstring）、tasks 2.2、SPEC R3「dashboard --serve 进程不做恢复」 | pass | 0/9 | - |
| r4-is-idle-distill-dimension | R4 行为矩阵·_is_idle 第六维度（蒸馏在飞保护）：基线空闲；蒸馏 worker 在飞（批次 run 阻塞中）→ 非空闲；消费完恢复空闲；进程内队列非空（worker 未起窗口）→ 非空闲；死台账在场（无 worker/队列）→ 仍空闲（死台账不钉住自愈）；管理器替身缺属性 → 按空闲不抛异常；内部状态不可读（非 AttributeError）→ 按非空闲（宁紧勿松）；管理器访问失败 → 按空闲；_is_idle 注释写明有界性依据（RUN_TIMEOUT_SECONDS×(1+MAX_FIX_ROUNDS)）与死台账口径。出处 fenixd.py:1632-1646（⑥蒸馏维度）、:1648-1678（_distill_lane_busy 容错分流）、tasks 2.3、SPEC 验收「蒸馏 worker 在飞时 _is_idle 返回 False；DistillManager 为替身/缺失时不抛异常」 | pass | 0/13 | - |
| deliverable-test-suite-green | 交付物测试套件全绿（tasks 3.1-3.4 用例载体）：pytest 运行交付物新测试文件 tests/test_knowledge_distill_resume.py（Deliverables kind: new）17 个用例全量通过——覆盖台账生命周期/容错与并发/恢复路径/_is_idle 蒸馏维度四组。命令只用 -v（禁与 -q 并列：pytest 9 下 -q 覆盖 -v 不打印 PASSED）；输出断言用实测稳定子串（<用例名> PASSED 与汇总行 17 passed，落盘前已实测照抄）。出处 spec/changes/evo-knowledge-distill-resume-guard/tasks.md Deliverables、tests/test_knowledge_distill_resume.py | pass | 0/11 | - |

## 本轮场景集变更

当前稳定场景集共 14 个（第 1 轮）。

- 首轮写入 14 个场景

