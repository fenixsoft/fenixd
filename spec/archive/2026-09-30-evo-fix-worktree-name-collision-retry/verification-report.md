# 验证报告：evo-fix-worktree-name-collision-retry

> ⚠️ 本报告由框架于 2026-09-24T10:30:03Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。
> 报告时效标记（判定本报告是否属上一轮）：合成源轮次指纹：report.json@2026-09-24T10:30:02.995284+00:00

## 结论：✅ 通过（verified）

**状态：verified — 6/6 场景通过，0 失败，0 错误（全部场景通过）**

全绿快道: 6/6 场景通过、0 失败 0 警告——无分类对象，跳过 judge 机械 verified

| 指标 | 数量 |
| --- | --- |
| 通过 | 6 |
| 失败 | 0 |
| 错误 | 0 |
| 产品 Bug | 0 |
| 本链增量 Token（输入） | 2.04M |
| 本链增量 Token（输出） | 0.02M |


## 场景结果

| 场景 | 描述 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- | --- |
| wtr-cross-lane-same-second-selfheal | 跨车道同秒撞名自愈：同 spec 的 planner-plan 与 implementer 同秒 create，后到者 worktree add -b 报 already exists 后在单次 create 内以单调时间戳（T+1）换名重试成功，两车道各得唯一分支、创建锁互不误删且无泄漏，无需 runner 层 sleep(5) 换 attempt 兜底（出处 core/worktree_manager/lifecycle.py:198-246 换名重试循环；交付测试 tests/test_dual_dispatch_and_freeze.py:163） | pass | 0/4 | - |
| wtr-retry-exhausted-fallback-lock-release | 重试耗尽回退现状：预建 T/T+1/T+2 三个同名分支耗尽 3 次创建尝试后 create 返回 None、释放本车道创建锁（重试可用），期间恰好 2 条换名 WARNING 且含新旧分支名；随后退出时间冻结以真实新时间戳 create 恢复成功，分支末段纯数字且严格大于预建值（出处 core/worktree_manager/lifecycle.py:230-256 放弃路径；交付测试 tests/test_dual_dispatch_and_freeze.py:123） | pass | 0/3 | - |
| wtr-lock-semantics-full-suite-regression | 锁语义回归网：全量跑 tests/test_dual_dispatch_and_freeze.py（25 例，覆盖 S2 并发唯一胜出/持锁不被误删/S3 失败快停/S4 冻结语义），确认换名重试改动零波及既有锁与冻结行为（出处 tests/test_dual_dispatch_and_freeze.py:99-484 全文件；本 SPEC 改动范围仅 core/worktree_manager/lifecycle.py） | pass | 0/4 | - |
| wtr-non-collision-failure-no-retry | 非重名失败不重试（独立探针，真实源码驱动）：mock git 层返回非 already exists 失败（Permission denied），create 不进入换名重试——仅 1 次 git 调用、无换名 WARNING、返回 None 且释放本车道锁；mock 退出后以真实时间戳重 create 恢复成功（出处 core/worktree_manager/lifecycle.py:230-231 非 already exists 直接 break；:249-255 失败语义） | pass | 0/8 | - |
| wtr-verifier-lane-collision-rename-contract | verifier 车道撞名换名 + 解析契约端到端（独立探针）：预建 fenix/verify-spec-v-<T> 分支制造真实 already exists，verifier create 冻结时间戳后换名至 verify-spec-v-<T+1>（分支名与目录名同名双换、目录真实存在），恰好 1 条含新旧分支名的 WARNING；分支名与 worktree 目录名经 queries 层 _spec_from_branch/_spec_from_worktree_name（core/worktree_manager/queries.py:28-59 rsplit+isdigit 契约）均解析回 spec-v（出处 core/worktree_manager/lifecycle.py:186-190 _names verifier 前缀） | pass | 0/12 | - |
| wtr-retry-boundary-lock-held-monotonic | 换名重试边界与锁持有（独立探针）：预建 T/T+1 两个同名分支使第 1、2 次创建尝试真实撞名，第 3 次（换名至多 2 次的边界）以 T+2 成功；spy 包装真实 git 调用证明 3 次尝试全程持有创建锁、成功后锁仍在册；2 条 WARNING 均带 attempt 序号且分别含新旧分支名；分支末段纯数字且恰为 T+2（时间戳单调），含连字符 spec 名 fix-b-path 经 queries 层 rsplit 契约解析无损（出处 core/worktree_manager/lifecycle.py:237 max(now, old+1) 单调；:241-246 WARNING 格式） | pass | 0/14 | - |

## 本轮场景集变更

当前稳定场景集共 12 个（第 1 轮）。

- 首轮写入 12 个场景

