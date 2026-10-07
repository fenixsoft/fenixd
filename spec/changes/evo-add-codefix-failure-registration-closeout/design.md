# Design

## 上下文

core/code_fix.py 现状：record_failed_batch（:623）入档并按 fail_count 预算重派；_append_todo_entry（:1285-1325）一次性写 todo 登记（持 .fenix/.todo.md.lock，与 evolution.py 有锁契约）；_write_retry_exhausted_alert（:2584-2620）写 code_fix_retry_budget_exhausted 告警；release_failed_batch（:1020-1061）只改 fix-failed.json；release_retryable_failed_batches（:975-1017）只打墓碑。批收尾/合回核销点：:5348（mark_ignored）、:5503（mark_resolved）、:4302（延迟批合回），其后已有 _chain_bump 链级计数惯例可平行插入。链边界簿记块 :3525-3541（新链启动集中做失败档案簿记）。告警收口：core/admin_store.py:637 mark_signal_handled（可附 action_taken）、:622 mark_handled。台账读取：read_items。

## 方案

1. 记录扩展：fix-failed.json 失败记录增 consumed_at/consumed_note/open_remaining（向后兼容：缺键视为未核销）。核销判定=对 read_items 逐 id 对账，登记条目全部终态（resolved/ignored）即置核销。
2. 挂钩两处：批收尾/合回核销点（:5348/:5503/:4302）后即时检查；新链启动簿记块（:3525-3541）加第三个调用做周期兜底。对账失败按空集 fail-open，不阻断主流程。
3. 告警收口：核销时按记录内 branch/tip_sha/item_ids 匹配未 handled 的 code_fix_retry_budget_exhausted 告警，调 AdminStore.mark_signal_handled，action_taken 附「N resolved / M ignored」终态分布；部分终态只更新 open_remaining；幂等（已 handled 不再动）。
4. release 留痕：release_failed_batch 接受可选 logger，调用后写一行结构化日志（释放记录数+item_ids 摘要）；daemon 内调用路径传入 logger，使带外经 daemon 的调用可见。
5. todo 消费侧：核销时持 .todo.md.lock 将登记块重写为单行「已于某时刻被后续批消化（终态分布）」或整块移除（含裸标题残骸场景），不依赖原位追加注记；OSError 容错与 _append_todo_entry 同口径（不阻断主流程）。

## 测试

- 新增 tests/test_codefix_failure_registration_closeout.py：全终态→核销+告警收口+todo 重写一次完成；部分终态→保留 open_remaining 不收口；重复核销幂等；release 留痕断言；台账读取失败 fail-open。
- 扩展 tests/test_code_fix.py（TestRetryBudget/TestFailureLockRelease 处）：登记写入/核销改写与 evolution 写者的锁竞争回归。
- 回滚：核销为只增记账动作，回滚即停止对账调用；记录缺键按未核销处理，无迁移负担。