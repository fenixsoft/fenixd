# codefix-release-consume-todo-block

## Why

evo-add-codefix-failure-registration-closeout（07592e49）的核销回路 consume_resolved_failed_batches 按注册表记录驱动（core/code_fix.py:1379 从 fix-failed.json 记录过滤 pending、再按记录定位 todo 登记块），而 release_failed_batch（:1135-1194）解除时整批删除记录且函数体零 todo 引用——两条生命周期终点无交接，「已解除但未核销」的登记块成孤儿。实证（2026-10-08）：1791442427 批 8 条目 21:13 全部 resolved，20:41 带外解除删记录后登记块无人核销，且登记正文已在 00:15-00:34 窗口损毁成裸标题壳（当前 todo.md:78 只剩标题行）——比 closeout proposal.md:5 记录过的「正文损毁成裸标题」病理更糟，人工连排查线索都没有。核查（evolution run evo-1791477251）另发现同链缺口：新链启动的预算内自动释放 release_retryable_failed_batches 不写 fix-failed-release.jsonl 留痕（:1084-1132 函数体零 _append_release_trace 引用），1791424850、1791433426 两批的解除动作在留痕审计中不可见。评审修正（2026-10-09）：该路径自 0eb2745a（2026-09-23，code-review item 931df4af59cc）起为「打标墓碑」而非删记录（:1094-1101，released=true 保留在册），在档 3 条 released=true 记录均已 consumed_at——既有 consume 闭环（:1370-1371 明言对账范围含墓碑）已覆盖其登记核销，故本变更对该路径只补留痕、不接核销动作（见 design 决策 3）。

## What Changes

- release_failed_batch：整批删除注册表记录成功后的同一调用序列内，best-effort 同步核销 todo.md 对应登记块——复用 `_rewrite_todo_entry_consumed` 的重写式核销，注记写明解除时刻与 fix-failed-release.jsonl 留痕行；仅整批删除触发核销，部分解除（收缩，:1177-1180，剩余条目仍在册仍跳过）不核销、留待既有 consume 闭环；核销定位 needle 须整行精确匹配（行尾锚），防同批子集与「清单为其前缀扩展」的他批登记块误命中（对齐 `_close_retry_exhausted_alerts` :1258 后缀锚先例）；todo 锁与 fix-failed 锁是两把锁、不做嵌套，OSError 容错同 `_append_todo_entry` 口径。
- release_retryable_failed_batches（预算内自动释放）经 _append_release_trace 补 fix-failed-release.jsonl 留痕（released_by=auto-budget），消除「自动释放零留痕」；不接 todo 核销动作——墓碑机制下记录保留在册、既有 consume 闭环已覆盖（design 决策 3），且预算内记录未达登记阈值本无登记块。
- fix-failed-release.jsonl 留痕行增补 todo 块处理结果字段（consumed / not_found），使「解除未核销」可从留痕审计。
- 登记块已损毁成裸标题壳时按标题兜底移除（复用 :1336-1337 既有逻辑，不新造）。

## Impact

- Affected specs: code-fix-batch-selfheal（MODIFIED：登记生命周期终点对齐——release 与 consume 两路径交汇）
- Affected code:
  - core/code_fix.py：release_failed_batch（:1135-1194）、release_retryable_failed_batches（:1084-1132）、_append_release_trace（:1214-1242）；复用不改：_rewrite_todo_entry_consumed（:1289-1346，needle 加整行精确锚）、_close_retry_exhausted_alerts
  - 沿用 .fenix/.todo.md.lock 与 .fix-failed.json.lock 既有双锁惯例，不新增锁、不嵌套
- Tests:
  - tests/test_codefix_failure_registration_closeout.py 扩展（解除→同步核销、自动释放同权、todo 写失败容错、裸标题壳兜底）
- 风险：低——核销动作幂等、best-effort 不阻断解除主流程；不改变解除语义与重试预算。