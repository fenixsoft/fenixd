# design — fix-resume-base-branch-portability

## Context

事故链（2026-10-02，potplayer-base，均已回源核实）：stale_code_dangling_timeout 升级（fenixd.py:1730-1800）→ restart_request → 排水 50s 超时（fenixd.log:564-565）→ 保全 sidecar + WIP 检查点提交成功（fenixd.log:566,569；core/wip_checkpoint.py:130-142 仅在 commit 成功后留痕）→ 重启后 `_resolve_preserved_branch` 层 2 解析出分支（fenixd.log:588）但 rev-list 闸门 core/state_machine.py:2685 硬编码 `main..{branch}` 失败（该仓库 master 主干、无 main、无 remote，`git rev-list --count main..fenix/cimbar-airgap-transfer-1790927434` 实测 exit 128）→ 「三处锚点均不可得」清空重建（fenixd.log:589-590）→ 启动清扫删 worktree 与分支（core/worktree_manager/stale_sweep.py:90,165；worktree 已被 WIP 提交清干净故快照跳过，STATE.branch 已清故分支保护不命中）→ 25 分钟在途工作灭失，继任 run 482 轮/$16.85 重做。

硬编码扩散面（grep 已核）：core/state_machine.py:2685；core/worktree_manager/queries.py:579,721,745；core/agent_runner/prompt_builder.py:1966；core/agent_runner/runner.py:1937-1946（docstring 明言 fail-open）。fenixd.py:105-135 `_preserve_base_branch`（code-review item ec528621b2ec）已修复同类问题于保全统计一处，其 docstring 逐字描述了本事故模式；但无 remote 时回退常量 `"main"`（fenixd.py:105），对本仓库形态仍失效。

## Goals

- 中断恢复保留续做链路（state_machine 三层锚点 + worktree_manager 枚举 + legacy + wip-checkpoint）在任意主干命名仓库可用。
- main 主干仓库（fenixd 自身与绝大多数既有测试场景）行为零漂移。

## Decisions

- D1 单源新模块而非各自修补：core/git_base_branch.py 提供 `resolve_base_branch(project_root, timeout=...) -> str`，解析顺序 origin/HEAD → 本地 main → 本地 master → 回退 "main"。不复用 fenixd.py 实现——state_machine/queries 等 core 模块导入 fenixd 会成环；也不放进 worktree_manager mixin——state_machine 的闸门在 worktree_manager 为 None 时早退前也要用基线。本地 main/master 探测用 `git rev-parse --verify --quiet <ref>`（一次子进程、退出码判定），补齐 fenixd.py 版本「无 remote 即失效」的缺口（本事故仓库即无 remote）。
- D2 按调用点保留既有失败语义：state_machine 闸门与 queries 枚举维持 fail-closed（解析异常→按现行清空重建/返回空），runner 零提交门维持 fail-open（门自身故障不打断收口，runner.py:1937-1946 既有约定）。本 SPEC 只换基线来源，不重写任何闸门方向。
- D3 缓存与超时：进程内按 project_root 缓存（与 fenixd.py `_preserve_base_branch_cache` 同形），git 子进程统一 10-15s 超时，与 PRESERVE_AHEAD_COUNT_TIMEOUT_SECONDS 口径一致；恢复路径为启动一次性调用，无热路径压力。
- D4 测试以真实 tmp git 仓为夹具（git init 后把分支改名为 master / main 两种形态 + 可选 origin/HEAD 符号引用），直接在 master 形态下复刻「分支含 1 提交 → _resolve_preserved_branch 应保留」，锁死本事故回归。
- D5 fenixd.py 收敛而非删除：`_preserve_base_branch`/`_ahead_commit_count` 委托共享解析器，保留函数签名与调用点（fenixd.py:267,4703,4868），避免保全 sidecar 字段口径漂移。

## Risks

- 基线误判（如仓库同时有 main 与 master 且语义倒置）：解析顺序固定 origin/HEAD 优先，与现网主场景一致；残余风险限于「无 remote 且双主干并存」的少见布局，后果是保留判定口径取 main，与现行行为相同（现行是直接失败），不劣于现状。
- 行为面扩大：master 仓库此前恒走的清空重建/恒放行路径将开始真实生效（如零提交门开始拦截）——这是修复目的本身，但意味着这类仓库的 implementer 收口新增一道门；以锚点 B WIP 提交 + 退避续做（既有机制）承接，零提交门 docstring 已注明该兜底。
- 测试环境依赖 git 对初始分支名的支持差异：夹具统一用 `git init` + `git branch -m` 改名，不依赖 init 缺省分支名。