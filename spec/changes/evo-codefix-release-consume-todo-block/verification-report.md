# 验证报告：evo-codefix-release-consume-todo-block

> ⚠️ 本报告由框架于 2026-10-08T17:51:42Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。
> 报告时效标记（判定本报告是否属上一轮）：合成源轮次指纹：report.json@2026-10-08T17:51:42.256936+00:00+run-result@mtime1791481902290831760

## 结论：✅ 通过（verified）

**状态：verified — 13/13 场景通过，0 失败，0 错误（全部场景通过）**

全绿快道: 13/13 场景通过、0 失败 0 警告——无分类对象，跳过 judge 机械 verified

| 指标 | 数量 |
| --- | --- |
| 通过 | 13 |
| 失败 | 0 |
| 错误 | 0 |
| 产品 Bug | 0 |
| 本链增量 Token（输入） | 2.88M |
| 本链增量 Token（输出） | 0.03M |


## 场景结果

| 场景 | 描述 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- | --- |
| release-full-batch-consumes-todo-block | 人工整批解除→登记块同步核销：带外不传 logger 直调 release_failed_batch 整批删除记录成功后，同一调用序列内 best-effort 核销 todo.md 登记块（注记写明解除时刻与 fix-failed-release.jsonl 留痕行指引），留痕行 todo_result=consumed、released_records=1，档案清空（spec/code-fix-batch-selfheal/spec.md:29-32；core/code_fix.py:1327-1357） | pass | 0/12 | - |
| release-partial-shrink-keeps-todo-block | 部分解除（收缩）不核销登记块：两批登记（[a,b] 与 [c]）共存时仅解除 [a]，记录收缩为 [b] 在册、两块登记块均原样保留、无核销注记，留痕行 todo_result=not_found、released_records=0（剩余条目留待既有 consume 闭环）（spec/code-fix-batch-selfheal/spec.md:34-37；core/code_fix.py:1309-1311） | pass | 0/10 | - |
| release-needle-exact-line-no-prefix-false-match | 核销 needle 整行精确匹配：本批 [a] 与他批 [a,b]（清单为本批的前缀扩展）共存，整批解除 [a] 只核销本批块，他批块不被子串包含误命中重写（对齐 _close_retry_exhausted_alerts 后缀锚先例），留痕 todo_result=consumed（spec/code-fix-batch-selfheal/spec.md:32；core/code_fix.py:1522-1524） | pass | 0/8 | - |
| auto-budget-release-trace-without-todo-touch | 预算内自动释放留痕：release_retryable_failed_batches 打标墓碑释放预算内记录（released=true 在册、fail_count 保留），达上限记录保持跳过、其登记块不被动；留痕 released_by=auto-budget、todo_result=not_found；二次调用幂等返回 0（spec/code-fix-batch-selfheal/spec.md:39-42；core/code_fix.py:1236-1245） | pass | 0/14 | - |
| release-todo-write-failure-not-blocking | todo 写失败不阻断解除主流程：todo.md 置为目录（读/写必 OSError）时整批解除照常落盘（档案清空、返回 1），核销 best-effort 失败不上穿，留痕行 todo_result=not_found 保证「解除未核销」可审计（design.md 权衡；core/code_fix.py:1272-1274、1536-1539） | pass | 0/6 | - |
| release-bare-title-shell-fallback-removal | 登记块已损毁成裸标题壳：正文丢失仅剩标题行时整批解除按既有兜底按标题移除残骸，他批完整登记块原样保留，留痕 todo_result=consumed（spec/code-fix-batch-selfheal/spec.md:44-47；core/code_fix.py:1527-1530） | pass | 0/7 | - |
| release-trace-unconditional-without-logger | 带外无 logger 调用留痕照写：零命中调用（空档案、空 item_ids）无条件追加一行结构化留痕（released_records=0、item_ids=[]、released_by=manual、todo_result=not_found、released_at 非空）；传入 logger 的调用另写一行 daemon 日志（补充通道，留痕不受影响）（spec/code-fix-batch-selfheal/spec.md:24-27；core/code_fix.py:1378-1423） | pass | 0/11 | - |
| consume-all-terminal-consumes-and-closes-alert | 被跳过条目全部终态后自动核销：consume_resolved_failed_batches 对账发现记录条目全部 resolved 即写入 consumed_at+终态分布注记+open_remaining=0，对应 code_fix_retry_budget_exhausted 告警经 mark_signal_handled 收口（action_taken 附「2 resolved / 0 ignored」），todo 登记块重写为核销注记（spec/code-fix-batch-selfheal/spec.md:9-12；core/code_fix.py:1542-1640） | pass | 0/10 | - |
| consume-partial-terminal-resync-open-remaining | 部分终态同步剩余 open 数：对账时条目仅部分终态则只更新 open_remaining、不核销不收口（告警未 handled、登记块原样、无 consumed_at）；剩余条目终态后二次对账补齐核销闭环（spec/code-fix-batch-selfheal/spec.md:14-17；core/code_fix.py:1595-1605） | pass | 0/10 | - |
| consume-repeat-idempotent | 重复核销幂等：已核销记录（有 consumed_at）再次被对账命中时跳过不重写——二次调用返回 0、consumed_at 值不变、todo 文件逐字节不变（核销注记不重复）、告警保持已 handled 不重复收口（spec/code-fix-batch-selfheal/spec.md:19-22；core/code_fix.py:1572） | pass | 0/8 | - |
| consume-ledger-read-failure-fail-open | 台账读取失败不阻断主流程：items.jsonl 位置替换为目录（read 抛 OSError→降级检出）时按空集 fail-open 跳过本轮核销——不误判全终态、不写 consumed_at、告警保持未 handled、不抛异常（spec/code-fix-batch-selfheal/spec.md:49-52；core/code_fix.py:1575-1583） | pass | 0/5 | - |
| consume-needle-exact-line-prefix-regression | 核销 needle 整行锚加固同惠既有 consume 路径（回归点）：记录 [a] 与 [a,b] 共存、仅 a 终态时 consume 只核销 [a] 登记块，[a,b] 块原样保留且 open_remaining 同步为 1，前缀扩展清单不被误重写（design.md 决策 5；core/code_fix.py:1522-1524） | pass | 0/8 | - |
| closeout-test-suite-green | 测试交付物回归：pytest -v 运行 tests/test_codefix_failure_registration_closeout.py 全绿（exit 0、21 passed），本 SPEC 新增用例（整批解除核销/部分解除不核销/前缀锚不误命中/auto-budget 留痕/todo 写失败容错/裸标题壳兜底/带外留痕字段）在列且 PASSED（tasks.md 2.1） | pass | 0/9 | - |

## 本轮场景集变更

当前稳定场景集共 13 个（第 1 轮）。

- 首轮写入 13 个场景

