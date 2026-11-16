# Design: scenario-exec-tree-isolation

## 背景锚点

- 执行根决策：core/pm_engine/verification/pipeline.py:2955-2967（仅取 serving 缓存 wt_path）；引擎入参已就绪 core/verify_engine/runner.py:63-77 scenario_root；cli_assertions.py:65-66 已有「worktree 轮」语义。
- 不建 serving 的明文：core/pm_engine/verification/serving.py:1462-1469（纯 cli 场景集不建 serving worktree，prepare 在主树执行）；本项目 config static_scope: main。
- judge 轮 worktree 是派发载体：core/agent_runner/runner.py:1502→_prepare_worktree:4489，与场景执行隔离无关（条目①「复用首轮语义」的口径修正依据）。
- 合回互斥信号：core/worktree_manager/mergeback.py:157/177/208/212 全程持进程内 _main_tree_lock（threading.Lock，与验证管线同 daemon 进程）；Autostash 日志边沿与 stale_code 检测（本案 18:11:37Z 实证感知主树 mtime 漂移）。
- 稳态复跑聚合点：pipeline.py:3072「[阶段2] 完成」一带；人工版实证=arbiter 档案「主树复跑 2 passed」。
- 同缝决策点：escalation.py 排程重验（:51-66 `_reverify_timers` 定时器）与 arbiter unfreeze 清零重试（:925-931）均回走同一阶段2执行根决策。

## 方案

1. 执行树隔离：执行根决策点对 pytest/cli 执行集建一次性快照 worktree（git worktree 本地操作，秒级），执行后清理；沿用既有 serving worktree 的产物准备路径解决 build artifacts 不在 git 的问题，不可行则回退主树并留告警。full-regression（10291 用例/约 350s）快照成本先测量后启用。快照基线固定为主树 HEAD 干净基线：主树未提交 WIP SHALL NOT 进入快照（不 stash、不改写主树现场），与既有主树 WIP 归因单源语义对齐；纯 cli 轮既有「prepare 在主树执行」（serving.py:1462-1469）与快照执行根形成分叉，快照轮的 prepare/依赖供给落点须显式约定（deps 为 venv 级可共享，prepare 步骤产物须落快照或证实在主树无害）。
2. 合回互斥方向选「合回让验证」：验证是长执行、合回是短临界区，合回有界推迟代价小；探测=进程内在飞信号（优先）+日志边沿兜底；有界等待+超时放行告警，防死锁。
3. 稳态复跑只重跑失败用例子集（失败清单/pytest --lf 形态），一次为限；触发条件收窄到源码锚位类断言形态（getsource/行号错位特征），防遮蔽真实锚位缺陷。

## 风险

- 快照 worktree 缺 build artifacts 改变测试行为——必须走既有产物准备路径或明确只隔离读侧源码，测试套件冒烟先行。
- 互斥有界等待超时后仍并发——超时放行+告警留痕，与稳态复跑互为兜底。
- 稳态复跑遮蔽真实缺陷——限锚位类断言形态+一次为限+留痕可审计。
- 快照内全量套件的既有环境陷阱：basetemp 固定落 `<root>/.fenix/pytest-basetemp`（bin/run_full_suite.py:61-67、tests/conftest.py:165 会话级隔离自清），worktree 路径形态有 argv 守卫误击秒败 exit 3 的历史 run 教训在案——快照轮冒烟 MUST 先覆盖 worktree 全量套件形态复检。