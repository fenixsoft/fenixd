# specs/resume-base-branch-portability/spec.md

## ADDED Requirements

### Requirement: 基线分支可移植解析

框架所有「分支相对基线的未合并提交数」类判定 MUST 经共享解析器 `core/git_base_branch.py::resolve_base_branch` 取基线分支，解析顺序：`git symbolic-ref --short refs/remotes/origin/HEAD`（去 `origin/` 前缀）→ 本地存在 `main` → 本地存在 `master` → 回退常量 `"main"`。每次 git 子进程调用 MUST 带超时；结果按 project_root 缓存；模块 MUST NOT 导入 fenixd.py。

#### Scenario: master 主干无 remote 仓库解析为 master

WHEN 仓库基线分支为 master、不存在 main 分支、且无任何 remote 时调用 resolve_base_branch
THEN 返回 "master"，且不抛出异常、不产生超时重试风暴

#### Scenario: origin/HEAD 在场时优先

WHEN 仓库存在 origin/HEAD 符号引用且指向 origin/main
THEN 返回 "main"，与 fenixd.py 现行为一致

#### Scenario: 非 git 目录回退常量

WHEN project_root 不是 git 仓库或全部探测命令失败
THEN 返回 "main"（与现 PRESERVE_AHEAD_BASE_BRANCH 回退一致），调用方按既有失败语义收口

### Requirement: 恢复续做判定跨基线分支成立

`core/state_machine.py::_resolve_preserved_branch` 的 rev-list 非空闸门 MUST 以共享解析器的基线替换硬编码 `main..{branch}`；解析器彻底失败（返回 None 语义之外的异常路径）时 MUST 维持现行清空重建的 fail-closed 行为。

#### Scenario: master 基线仓库中被排水中断且 WIP 提交在场的 spec 走保留续做

WHEN 仓库基线为 master，spec 实现 run 被规划性重启排水中断、其分支含 1 个未合并 WIP 提交、STATE.branch 缺失且在册 worktree 可解析出该分支
THEN _resolve_preserved_branch 返回该分支与非空载体，_recovery_preserve_spec 写入 `_recovery_resume: True` 与 branch，恢复日志为「Recovering interrupted SPEC … resume continuation」，不出现「三处锚点均不可得」清空重建

#### Scenario: 分支确无未合并提交时仍清空重建

WHEN 候选分支相对解析出的基线 rev-list 计数为 0（真零提交形态）
THEN 维持现行清空重建路径与 WARNING 留痕，不因基线替换引入误保留

### Requirement: 分支命名空间枚举与待合并判定跨基线成立

`core/worktree_manager/queries.py` 中 find_branches_by_spec 的候选剔除/排序、has_pending_merge、pending_merge_since 的 `main..<branch>` 计算 MUST 改用共享解析器基线；解析失败时维持现行 fail-closed（返回空/None）语义。

#### Scenario: master 基线仓库的第三层锚点枚举可命中

WHEN master 基线仓库中某 spec 的 worktree 已清理、仅剩含未合并提交的实现分支，恢复进入分支命名空间枚举层
THEN find_branches_by_spec 返回该候选（rev-list 计数基于 master 计算 >0），恢复日志出现「经分支命名空间枚举回落」

#### Scenario: main 基线仓库行为不变

WHEN 仓库基线为 main（现行主场景）
THEN 枚举、排序、pending_merge_since 返回值与替换前逐项一致（既有测试全绿）

### Requirement: 终态零提交门与遗产快照跨基线成立

`core/agent_runner/runner.py::_check_terminal_no_commit_gate` 与 `core/agent_runner/prompt_builder.py` 的 legacy 提交快照 MUST 改用共享解析器基线；门的 fail-open 语义（门自身故障不打断正常收口）MUST 保留。

#### Scenario: master 基线仓库零提交且 dirty 的实现收口被拦

WHEN master 基线仓库中 implementer run 终态时分支相对 master 零新提交且 worktree dirty 取证非空
THEN 抛出携带 `[terminal-no-commit]` 前缀的 AgentArtifactGateError 进入既有退避重试通道（替换前该门因 rev-list 失败恒放行）

#### Scenario: 遗产快照可采集提交清单

WHEN master 基线仓库触发 recovery legacy 现场采集
THEN `git log --oneline <基线>..branch` 基于解析基线执行并返回提交快照，不再因 unknown revision 恒空