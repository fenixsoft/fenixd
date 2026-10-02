# fix-resume-base-branch-portability

## Why

2026-10-02 07:49 UTC，potplayer-base 因 stale_code_dangling_timeout 升级触发规划性重启，在飞实现 run impl-cimbar-airgap-transfer-1790925912-a1（25 分钟在途）被排水中断。框架的保全链路按设计完整走通：保全 sidecar 落盘、WIP 检查点提交成功（fenixd.log:569「WIP checkpoint committed (anchor 'drain-preserve')」，分支 fenix/cimbar-airgap-transfer-1790925912）。但重启后恢复续做闸门 `git rev-list --count main..{branch}`（core/state_machine.py:2685）硬编码 `main`——该仓库基线分支是 master、不存在 main、无 remote，rev-list 恒以 128 退出，判定回落「三处锚点均不可得」清空重建，启动清扫随即删 worktree 与分支，已提交的 WIP 检查点不可达，25 分钟在途工作灭失，继任 run 从零重做（482 轮 / $16.85）。

同型硬编码 `main..` 在 core 内共 6 处（state_machine.py:2685、worktree_manager/queries.py:579/721/745、agent_runner/prompt_builder.py:1966、agent_runner/runner.py:1958，其 docstring 见 :1937-1946），在非 main 主干仓库整体失效：续做判定不命中、分支命名空间枚举恒空、终态零提交门因 fail-open 恒放行、legacy 快照恒空。fenixd.py:105-135 的 `_preserve_base_branch`（code-review item ec528621b2ec）已示范正确解法（origin/HEAD 符号引用探测），但其 docstring 明言的同一事故模式至今仍可在 core 侧复现，且该实现无 remote 时回退常量 "main"，对本仓库形态依然失效。

## What Changes

- 新增 core 共享基线分支解析器 core/git_base_branch.py：origin/HEAD → 本地 main → 本地 master → 回退 "main"，带超时与按 project_root 缓存，不反向依赖 fenixd.py。
- core/state_machine.py `_resolve_preserved_branch`、core/worktree_manager/queries.py（find_branches_by_spec / has_pending_merge / pending_merge_since）、core/agent_runner/runner.py（终态零提交门）、core/agent_runner/prompt_builder.py（legacy 提交快照）统一改用共享解析器。
- fenixd.py `_preserve_base_branch`/`_ahead_commit_count` 收敛为委托共享解析器，消除无 remote 仓库 ahead 恒 0 的残留缺陷。
- 新增与扩展单测，覆盖 master 主干无 remote 仓库的中断恢复保留续做全链路。

## Capabilities

- resume-base-branch-portability

## Impact

- 影响模块：core/state_machine.py、core/worktree_manager/queries.py、core/agent_runner/runner.py、core/agent_runner/prompt_builder.py、fenixd.py、tests/。
- 行为变化仅限「此前因 rev-list 失败而必然走清空重建/恒放行/恒空」的非 main 主干仓库；main 主干仓库行为逐字节不变（解析结果同为 main）。
- 风险：基线误判会把零提交分支误判为有未合并提交——以 rev-list 实数 >0 为闸、解析彻底失败时维持各调用点既有 fail-closed/fail-open 语义兜底；既有 main 主干测试集全量保留作回归护栏。