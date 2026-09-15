# 验证报告：fix-verdict-read-failclosed

> ⚠️ 本报告由框架于 2026-09-09T15:02:33Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。

## 结论：✅ 通过（verified）

**状态：verified — 10/10 场景通过，0 失败，0 错误（全部场景通过）**

全绿快道: 10/10 场景通过、0 失败 0 警告——无分类对象，跳过 judge 机械 verified

| 指标 | 数量 |
| --- | --- |
| 通过 | 10 |
| 失败 | 0 |
| 错误 | 0 |
| 产品 Bug | 0 |
| 本链增量 Token（输入） | 8.39M |
| 本链增量 Token（输出） | 0.06M |


## 场景结果

| 场景 | 描述 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- | --- |
| gate-copyback-intercepts-invalid-json | runner 产物硬门拷回前置：worktree 侧 judge 写入裸换行非法 JSON（复刻 add-verify-contract-autodraft 事故签名 Invalid control character），拷回先行门检随后拦截，走瞬态退避重试通道，run 不判 success；主树同路径已被本轮 worktree 产物覆盖（spec：硬门校验本轮实际产出 / worktree 侧写入不再绕过门检） | pass | 0/3 | - |
| gate-valid-artifact-passes | runner 产物硬门拷回前置正向：worktree 侧写入合法 bug-found 结果文件 → 拷回主树 → 门检校验 status ∈ 白名单通过 → run 判 success，拷回产物存在于主树（runner.py:1924-1933 拷回先行、_check_agent_result_artifact 门检随后） | pass | 0/2 | - |
| gate-freshness-rejects-stale | runner 产物硬门新鲜度：主树存在上一轮写入的合法结果文件（mtime 远早于本轮启动），本轮 judge 未产出任何结果文件 → 门检因 mtime 早于本轮启动而失败（归因含『早于本轮启动』）→ 走瞬态退避重试，run 不判 success（spec：陈旧残留文件被新鲜度拦截；runner.py:3144-3151 mtime 下界校验） | pass | 0/2 | - |
| gate-status-whitelist-enforced | runner 产物硬门 status 白名单：顶层 status='success'（verdict 语义错位）不在白名单内 → 门检拦截附实际值（归因含『不在白名单』与『success』）；verified/bug-found/plan-ready/scenario-repaired 四值均通过门检返回 None（spec：语义错位 status 被门检拦截 + D3 白名单单一来源；runner.py:3153-3167） | pass | 0/3 | - |
| read-corrupt-json-retry-block | 三阶段读侧 fail-closed：裁决结果文件 summary 字符串含未转义换行（复刻 Invalid control character at: line 25 column 402 事故签名）→ 不晋级 verified → 重派 judge 一次（run_planner judge 被调用 ≥2 次）复读仍不可读 → spec blocked（error 含『不可读』与解析错误原文『Invalid control character』）→ critical 告警 verdict_result_unreadable（evidence 含错误原文）→ on_spec_verified 与 on_spec_bug_found 均未调用（不派生 fix）（spec：裸换行破坏裁决文件） | pass | 0/2 | - |
| read-unknown-status-retry-block | 三阶段读侧 fail-closed：status='success' 白名单外 → 重派 judge 一次复读仍白名单外 → spec blocked（error 含『success』）→ 不晋级 verified（spec：status 白名单外同路径；verification.py:1568-1617 retry-then-block 分支） | pass | 0/2 | - |
| read-retry-fix-chain | 三阶段读侧重试成功路径：首次裁决不可读（parse）→ 重派 judge 复读返回合法 bug-found → 正常走 fix 链（on_spec_bug_found 恰一次被调用，不晋级 verified）（spec：重试产物合法时按其 status 正常路由 bug-found → fix 链） | pass | 0/2 | - |
| read-valid-routes-regress | 三阶段合法裁决路由不回归：合法 verified → verified/done；合法 scenario-repaired → 冻结记账恰一次后重入再次裁决 → verified 收敛；全绿快道（0失败 0 警告）机械写回 status=verified + mechanical=true → 读侧真实读取 ok → verified（spec：合法裁决路由不回归 + 全绿快道回归；verification.py 全绿快道机械写回读侧不回归） | pass | 0/4 | - |
| legacy-failclosed-all | legacy 路径同门 fail-closed：结果文件裸换行非法 JSON → blocked（error 含『不可读』与『parse』）+ verdict_result_unreadable critical 告警；status='success' 属当前 spec → 白名单外 blocked（error 含『success』）；文件缺失 → blocked + 告警；合法 bug-found → 正常流转 bug-found 且告警零调用（spec：legacy 不可读结果不洗白 + legacy 路径同门，四项全覆盖；不重派整轮 verifier、任何路径不发生 → verified 转换） | pass | 0/5 | - |
| direct-codepath-verify | 直接行为级验证：独立于 pytest 夹具驱动真实框架代码路径——planner_result_status_whitelist 常量内容（D3 单一来源 4 值），_read_verifier_result 缺失/裸换行非法 JSON/unknown-status/白名单内四值 ok 三态 + foreign-stamp 拦截，_check_agent_result_artifact 缺失/空文件/非法 JSON/陈旧残留/白名单外/白名单内 6 路径 + 非 planner 类型忽略，planner-judge.md JSON 合法转义契约（D7）（脚本路径 .history/verify-verdict-failclosed/verify.py，cwd 相对验证树根即 worktree 根） | pass | 0/15 | - |

## 本轮场景集变更

当前稳定场景集共 10 个（第 1 轮）。

- 首轮写入 10 个场景

