# 验证报告：evo-add-todo-marker-commit-on-write

> ⚠️ 本报告由框架于 2026-10-04T20:03:39Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。
> 报告时效标记（判定本报告是否属上一轮）：合成源轮次指纹：report.json@2026-10-04T20:03:38.620381+00:00+run-result@mtime1791144218696006631

## 结论：✅ 通过（verified）

**状态：verified — 13/13 场景通过，0 失败，0 错误（全部场景通过）**

全绿快道: 13/13 场景通过、0 失败 0 警告——无分类对象，跳过 judge 机械 verified

| 指标 | 数量 |
| --- | --- |
| 通过 | 13 |
| 失败 | 0 |
| 错误 | 0 |
| 产品 Bug | 0 |
| 本链增量 Token（输入） | 3.95M |
| 本链增量 Token（输出） | 0.08M |


## 场景结果

| 场景 | 描述 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- | --- |
| todo-marker-tracked-single-commit-clean | tracked 项目单点写路径（accept/reject/delete 复用的缺省提交开关形态）：write_todo_marker 写入 tracked 的 .fenix/todo.md 后就地产生恰一枚提交，HEAD 仅含 .fenix/todo.md，工作区对该文件无未提交改动，提交信息为「[fenix] evolution: 自进化标记回写 <日期>」前缀（出处 core/evolution.py:914-919 提交触发与 920-1007 _commit_todo_marker，spec 场景「tracked 项目写入后产生单提交」） | pass | 0/7 | - |
| todo-marker-commit-pathspec-scoped | 提交带 pathspec 限定：索引里并发暂存的其他文件（模拟 merge-back/守卫自动化产物的 README.md）不被卷进标记提交、提交后仍留在暂存区、不出现在 HEAD（出处 core/evolution.py:988-995 `git commit -m <msg> -- .fenix/todo.md`，design「commit 不带 pathspec 会把索引里并发暂存的其他内容卷进本提交并随 push 外泄」） | pass | 0/6 | - |
| todo-marker-untracked-nongit-skip | untracked 两种形态跳过提交且不报错：git 仓库但 todo.md 未被跟踪（零提交仓库，ls-files 输出为空）与目录非 git 仓库（ls-files 非零退出）——标记写入成功、不产生提交、不向调用方报错（出处 core/evolution.py:940-958 ls-files 判定与未 tracked 跳过分支，spec 场景「untracked 项目跳过提交」） | pass | 0/7 | - |
| todo-marker-index-lock-degrade | 提交失败降级（spec 场景「提交失败降级」）：并发 git 进程持有的 .git/index.lock 在场时 git add 失败，写入不回滚（标记内容已落 todo.md）、不向调用方抛错（write_todo_marker 仍返回 True）、无新提交，待下一次写入再尝试（出处 core/evolution.py:960-976 add 失败降级分支与 design「提交失败（含 index.lock 竞争）捕获异常降级为日志留痕」） | pass | 0/5 | - |
| todo-marker-push-failure-degrade | push 失败降级（spec 场景「提交失败降级」push 部分）：仓库未配置 remote 时 push 失败仅降级 WARNING 不重试，本地提交已产生、仅含 .fenix/todo.md，write_todo_marker 仍返回 True（本地提交不受 push 失败影响）（出处 core/evolution.py:999-1007 push 降级分支，形态与 core/self_review.py:1974 _commit_todo 同策略） | pass | 0/5 | - |
| todo-marker-rewrite-noop-benign | 幂等重写回归点：同一标记重复写入（原地更新、内容无变化）时第二次写入仍报成功，且不产生重复提交（commit 返回「nothing to commit」按良性 no-op 识别留痕，提交数保持 1 枚增量）（出处 core/evolution.py:996-1003 良性无变更两形态识别分支；幂等原地更新语义见 write_todo_marker docstring core/evolution.py:862-864） | pass | 0/6 | - |
| todo-marker-batch-analyzed-deferred-merged | 批量路径逐条不提交（tasks 1.2/1.3 主链路）：一轮 ingest_item 落两条 analyzed 条目只写标记不产生任何提交（避免逐条提交风暴），编排层批末 commit_todo_marker 将两条标记合并为恰一枚提交、HEAD 仅含 .fenix/todo.md、文件含两条「自进化：」标记（出处 core/evolution.py:1272/1281/1296 commit=False 与 core/agent_runner/maintenance_runs.py:1094-1102 批末按项目合并提交） | pass | 0/9 | - |
| todo-marker-batch-pending-defers-commit | 批量路径 pending 分支不逐条提交（tasks 1.2「ingest_item 内部 4 处调用必须传关闭」的第四处）：一轮 ingest_item 落两条 pending 条目（stub 草稿落盘与 lint 通过）只写标记不产生任何提交，批末 commit_todo_marker 合并为恰一枚提交（出处 core/evolution.py:1301 ingest_item pending 分支调用点与 design「ingest_item 内部 4 处调用（evolution.py:1141/1150/1165/1170）必须传关闭」、maintenance_runs.py:1094-1102） | pass | 0/8 | - |
| todo-marker-batch-multiproject-separate-commits | 一轮涉及多个项目按项目各一次提交、不存在跨项目单提交：两个 tracked 项目批量写标记（commit=False）均不产生提交，批末对每个项目各触发一次合并提交，每枚提交仅含本项目的 .fenix/todo.md（出处 core/evolution.py:1009-1030 commit_todo_marker 按 project_path/project_name 入口、maintenance_runs.py:1100-1102 对 sorted(marker_projects) 逐项目调用，design「一轮可涉及多个项目，不存在跨项目单提交」） | pass | 0/11 | - |
| todo-marker-batch-commit-noop-unresolvable | 批末合并提交边界路径：无未提交改动时良性 no-op 返回 False 且不报错不产生提交；项目名经 registry 解析失败（未注册名）与未提供项目参数均返回 False 不抛错；非 git 项目跳过且不抛错（出处 core/evolution.py:1009-1030 commit_todo_marker 前置判定与 940-958 未 tracked 跳过、996-1003 良性无变更识别） | pass | 0/7 | - |
| todo-marker-write-failure-no-commit | 异常路径：条目在 todo.md 中定位不到（用户改过标题/删过条目）时标记回写返回 False、todo.md 内容不被改动、且不触发提交、不向调用方抛错（出处 core/evolution.py:893-899 apply_marker_to_lines 返回 None 分支与 914-915 仅写入成功才提交的门槛） | pass | 0/5 | - |
| todo-marker-delivered-tests-green | 交付测试全绿：tests/test_evolution_todo_marker_commit.py 全部 12 例 PASSED（含 :260 参数化展开 2 项）——恰一枚提交且工作区干净 / pathspec 防卷入并发暂存 / untracked 与非 git 跳过 / index.lock 竞争降级不抛错 / push 失败降级 commit 保持 / 批末合并提交 / 无变更 no-op / 非 git 批量跳过 / 项目解析失败参数化 2 例（出处 tests/test_evolution_todo_marker_commit.py:92-234 测试清单，断言文案与 -v 输出实测对齐） | pass | 0/12 | - |
| todo-marker-affected-suite-regression | 回归保护：引用 ingest_item/write_todo_marker/commit_todo_marker/run_evolution 的 6 个既有测试文件（self_evolution、evolution_clear_todo、evolution_bg_wait_ceiling、evolution_product_salvage、daily_self_review、facade_delegation_contract）共 252 例全通过，提交开关与批末合并提交未破坏既有回写/编排/门面委托行为（基线实测 2026-10-05 于实现分支：252 passed，544 subtests passed） | pass | 0/2 | - |
