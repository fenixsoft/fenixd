# add-codefix-failure-registration-closeout

## Why

add-code-fix-batch-failure-selfheal（已归档）达上限失败批的「待人工排查」登记与告警是一次性写入、永不更新：实测 2026-10-07 两批登记（告警 a99a3b5b21cb、7f71a053bf1b）对应的 13 个被跳过条目已于当日 11:41:32Z 全部终态，两条告警却挂了一天以上 handled=false；人工解除接口 release_failed_batch 被交互会话带外调用（11:03:46Z，释放 13 条）在 fenixd.log/hook_audit 零留痕，事后排查只能靠会话考古。存量 spec 的 design R4 已显式把「永久跳过条目的收敛」留待「凭观测另立 SPEC」，本观测已到位。次生证据还表明 todo.md 自由文本登记脆弱（本次登记正文在后续 todo.md 重写中损毁成裸标题），核销落点必须是结构化字段而非原位注记。

## What Changes

- fix-failed.json 失败记录增结构化核销字段（consumed_at/consumed_note/open_remaining）；核销判定=对台账逐 id 对账、被跳过条目全部终态即置核销；挂两处——批收尾/合回核销点后即时检查、新链启动既有簿记块周期兜底；台账读取失败按空集 fail-open。
- 核销时同步收口对应 code_fix_retry_budget_exhausted 告警（复用 AdminStore.mark_signal_handled，action_taken 附终态分布）；部分终态只更新 open_remaining 不收口；重复核销幂等。
- release_failed_batch 增结构化留痕日志（释放记录数+item_ids 摘要，经 daemon logger），消除带外调用零留痕。
- todo.md 消费侧弱化为重写式核销行或整块移除（持同锁），不依赖原位追加注记。

## Impact

- Affected specs: code-fix-batch-selfheal（MODIFIED：补 design R4 deferred 的登记闭环消费侧）
- Affected code:
  - core/code_fix.py：record_failed_batch/release_failed_batch/_append_todo_entry/_write_retry_exhausted_alert 及批收尾核销点、链边界簿记块
  - 复用不改：core/admin_store.py mark_signal_handled；todo.md 写沿用 .fenix/.todo.md.lock 同锁惯例
- Tests:
  - tests/test_code_fix.py 扩展；新增 tests/test_codefix_failure_registration_closeout.py
- 风险：低——核销为幂等只增记账动作，fail-open 不阻断主流程；不改重试预算与跳过语义。