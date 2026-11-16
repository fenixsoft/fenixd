# Proposal: scenario-exec-tree-isolation

## Why

验证场景执行（pytest/cli 类）在无 serving worktree 条件时恒主树裸跑，与任意车道 merge-back/autostash 并发时，源码锚位类契约测试（inspect.getsource 按 co_firstlineno 切磁盘文件）确定性瞬态假失败。实证：add-platform-abstraction-layer 修复轮重验 18:07:26Z 启动于主树（无 worktree 创建行），18:11:15Z code-fix 车道 Autostash→Merged→Stash popped 恰在执行窗内改写 core/agent_runner/runner.py（mtime 18:11:15.374Z 秒级吻合），5 组 getsource 锚位断言全部错位到相邻函数，主树稳态复跑 2 passed 甄别为假失败；假失败压顶触发 judge_rerun_cap 6/5 假冻结（重执行 13/14 过的结果未被读取）+ 一轮 arbiter 处置。结构面：执行根决策 pipeline.py:2707-2722 仅取 serving 缓存 wt_path 否则回退主树（verify_engine/runner.py:75-77），serving.py:1415-1428 纯 cli 场景集明文不建 serving worktree，本项目 config static_scope: main——所有验证轮（首轮/judge 轮/重验轮）恒主树裸跑；judge 轮 worktree 仅是派发载体非执行隔离。暴露面：merge-back 频次 11-08=5、11-09=6、11-10=18 次/天，full-regression 运行窗约 13 分钟/轮；共用决策点的还有排程重验（escalation.py:2770）与 unfreeze 重验。锚位脆弱面存量真实：tests/ 中 getsource 用法 15+ 处。

## What Changes

- 执行树隔离：执行根决策点为「无 serving worktree 条件且执行集含 pytest/cli 类场景」创建一次性快照 worktree 作为执行根（引擎 scenario_root 入参已就绪），执行后清理；快照不可行时回退主树并留痕。三缝（scenario-repaired 重入、排程重验、unfreeze 重验）共用同一决策点一并覆盖。
- 合回互斥：merge-back 启动前探测验证执行在飞（进程内 _main_tree_lock 同 daemon 可探测+Autostash 日志边沿），在飞则有界等待/推迟，超时放行并告警留痕；不改 WIP 重叠 precheck 既有语义。
- 锚位失败稳态复跑：全量回归类场景出现源码锚位类断言失败时，对失败用例子集自动做一次稳态复跑，复跑通过按瞬态留痕处理（不计 fail、不驱动 judge 重跑）；arbiter 已实证人工版（主树复跑 2 passed）。

## Impact

- Affected specs: verify-infra（新能力页）
- Affected code:
  - core/pm_engine/verification/pipeline.py（执行根决策+锚位稳态复跑）
  - core/worktree_manager/mergeback.py（验证在飞探测与有界推迟）
  - tests/test_scenario_exec_tree_isolation.py（新增单测）