# ADR-256：分支相对基线的未合并提交判定单源经共享解析器，禁止调用点自定基线

date: 2026-10-08
status: accepted

## Context

2026-10-02 potplayer-base 事故：master 主干、无 remote 的仓库中，规划性重启排水后的保全链路完整走通（sidecar 落盘、WIP 检查点提交成功），但恢复续做闸门硬编码 `main..<branch>`，rev-list 恒以 128 退出，判定回落「三处锚点均不可得」清空重建，启动清扫删 worktree 与分支，25 分钟在途工作灭失，继任 run 482 轮/$16.85 重做。排查确认同型硬编码 `main..` 在 core 内共 6 处（恢复续做闸门、分支枚举/待合并判定、终态零提交门、legacy 快照），非 main 主干仓库整体失效：续做判定不命中、枚举恒空、零提交门 fail-open 恒放行、legacy 快照恒空。同时存在另外两套并行基线口径——fenixd 保全统计的 origin/HEAD 探测（无 remote 时回退常量 main，对本事故仓库形态仍失效）与 branch_guard 的 `baselines=["main"]` 候选循环（master 主干无 remote 恒 None、零变更哨漏报空转）。基线口径分叉使「框架在什么仓库形态下可用」取决于各调用点各自怎么写。

## Decision

- 框架所有「分支相对基线的未合并提交数」类判定 MUST 经共享解析器 `core/git_base_branch.py::resolve_base_branch` 取基线，解析顺序固定：origin/HEAD 符号引用 → 本地 main → 本地 master → 回退常量 `"main"`。后续新增的同类判定（ahead 计数、pending 判定、零提交/零变更哨、快照枚举）不得自建基线来源、不得硬编码主干名，一律 import 共享解析器。
- 单源落地为新 core 模块：不复用 fenixd.py 实现（state_machine/queries 等 core 模块导入 fenixd 会成环），也不放进 worktree_manager mixin（state_machine 的闸门在 worktree_manager 为 None 时早退前也要用基线）。本地分支探测用 `git rev-parse --verify --quiet` 一次子进程判定，补齐「无 remote 即失效」缺口。
- 失败语义分层不随迁移重写：解析器自身吞异常恒回退常量、不抛错、无 None 返回；各闸门的 fail-closed/fail-open 方向由替换后的 git 查询自身维持——本裁定只换基线来源，不改变任何闸门方向。
- 解析器带 git 子进程统一超时与按 project_root 进程内缓存；恢复路径为启动一次性调用。

## Consequences

- main 主干仓库（fenixd 自身与既有测试主场景）解析结果同为 main、rev-list 同参，行为逐项零漂移。
- 非 main 主干仓库的行为面开始真实生效：恢复保留续做可命中、分支枚举可命中、零提交门开始拦截、零变更哨恢复侦测、保全 ahead 计数为实数——其中零提交门从恒放行变为真实门，是修复目的本身。
- 后续任何基线类判定的新接入点被本裁定约束为单源消费，防止第三套口径再分叉。
- 残余风险限于「无 remote 且 main/master 并存且语义倒置」的少见布局：解析取 main，后果与修复前（直接失败）相比不劣于现状。
