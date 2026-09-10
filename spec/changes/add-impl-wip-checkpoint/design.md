# add-impl-wip-checkpoint 设计

## Context

2026-09-09 事故链（逐环已核实）：restart_request → supervisor SIGTERM daemon → 当时排水配置 `shutdown_drain_seconds: 0` → 在飞 implementer（63min，10 文件未提交）被杀 exit 143 → 新 daemon `recover_interrupted` → `_recovery_preserve_spec`（state_machine.py:820，09-05 上线）因**分支零提交**降级清空重建 → 第二轮从零 39.9min/$17.90。

现有恢复机械（不重建，直接复用）：
- 保留分支 + `claude --resume` 续做：`_recovery_preserve_spec` → dispatch `_recovery_resume` → `run_implementer(pre_wt_path=...)`（dispatch.py:632-656）
- worktree 三态载体解析：`resolve_resume_site`（worktree_manager.py:3076，在场/重建/降级）
- 排水 + sidecar 元数据保全：`drain_wait`（runner.py:3520）+ `_preserve_interrupted_runs`（fenixd.py:1010，写 `.fenix/interrupted_runs.json`，进程存活时执行，只登记不提交）
- 并行终止协议：SIGTERM → interrupted 标记 → ≤10s grace → SIGKILL（liveness.py:640）

排水配置已修（0→1800，daemon 热更新 + supervisor restart 时实时重读，零重启生效），消除了最常见入口；本 SPEC 关闭剩余两个丢失面。

## Goals / Non-Goals

**Goals**
- 中断时刻（两类锚点）分支上必有可恢复提交 → recovery-resume 高价值路径自动接管
- 主树历史零 WIP 污染（塌缩）
- 失败降级不阻塞既有收口/重试链路

**Non-Goals**
- 不改瞬断判定本身（shutdown-kill 误判 provider-transient 的守卫另行处理；锚点 B 依赖的 transient_retry 路径保持现状）
- 不改 merge-back 合并语义（仍普通 merge）
- 不做 agent 侧自主周期提交（prompt/hook 层，另行评估）
- 不新增配置键、不做 Dashboard UI

## Decisions

### D1：checkpoint = 提交，锚点放框架控制且 worktree 可证明静默的时刻

备选与取舍：
- *agent 侧每 tasks.md 条目提交*：语义边界干净但靠自觉、需守卫基建，且无法覆盖锚点场景（进程被杀时 agent 不知道要提交）。不做。
- *runner 定时强提交*：与 agent 写盘竞态（半成品提交），且与 agent 自身 git 操作撞车。不做。
- **选定**：只在 (A) 所有 agent 进程终止完成后、(B) 子进程已退出的退避 sleep 前——两处 worktree 静默可证明，零竞态。

### D2：锚点 A 时序——提交在进程死后、cleanup_orphans 之前

`_preserve_interrupted_runs` 发生在排水超时、进程**仍存活**时（只写 sidecar），彼时提交有写竞态。选定插入点：

```
fenixd.shutdown():
    drain_wait 超时 → _preserve_interrupted_runs(remaining)   # 存活时：元数据
    → wait_for_running_agents()                               # 全部进程死亡
    → 【锚点 A】对 preserved_wts 逐个 WIP 提交                # 新增，静默窗口
    → _v2_stop_all()
    → cleanup_orphans(protected=preserved_wts)
```

空变更（`git status --porcelain` 为空）跳过提交。

### D3：锚点 B 时序——transient_retry 记录写后、sleep 前

runner.py attempt 循环瞬断路径（~2090）：`append_run_line(transient_retry)` 之后 `time.sleep(backoff)` 之前，对当前 attempt 的 worktree 提交。守护事故中「16:06:47 排重试 → 16:07:06 recovery 重派」的 19s 窗口。无 worktree 载体（pre_wt_path 为 None 且本 attempt 未建 wt）时跳过。

### D4：塌缩放 merge_back 前的成功收口 choke point

merge-back 是普通 merge（worktree_manager.py:1834），WIP 提交会进主树历史。选定：成功收口进入 merge_back 前识别分支上全部 `fenix(wip):` 前缀提交，`git reset --soft <merge-base>` 后以塌缩前最终提交消息重建成单提交（soft reset 不触碰工作区，文件内容逐字节不变）。
备选（接受 WIP 入史）实现更简单但污染主树历史与归档可读性，不选；改 merge-back 为 squash 影响所有分支语义，不选。
塌缩自身幂等：无 `fenix(wip):` 提交时零动作，常规成功路径逐字节现行行为。

### D5：WIP 提交消息契约

`fenix(wip): checkpoint <anchor> <spec>`（anchor ∈ `drain-preserve` / `transient-backoff`），机器可识别前缀供 D4 塌缩扫描与人工审计。提交尊重 worktree gitignore（`git add -A` 天然排除 ignored）。

### D6：失败降级风格对齐 `_preserve_interrupted_runs`

git 操作 15s 超时；失败 WARNING 留痕（spec/branch/错误摘要）继续收口——WIP 提交是尽力而为的保全增强，任何失败不改变现行行为。

### D7：无配置化

锚点无条件下生效。理由：行为是纯保全增强、无资源争议；新配置键按项目约束必须带 Dashboard UI，成本不成比例。

## Risks / Trade-offs

- [锚点 A 在 daemon 退出序列内新增 git 操作，极端情况下拖慢关停] → 15s 超时 + 保全集通常 ≤ 并发上限（3），最坏 45s，远小于 supervisor SIGKILL 窗口（1920s）
- [塌缩改写分支历史，若 merge-back 失败重入会重复塌缩] → 塌缩幂等（重入时 WIP 已不在，零动作）；soft reset 仅在 merge_back 尝试前执行，失败不产生半塌缩状态
- [`git add -A` 把 agent 的无关临时文件提交进 WIP] → gitignore 已排除 .fenix/dist；临时文件本就在实现分支工作区内，塌缩后与常规最终提交内容一致，无净污染
- [锚点 B 的 WIP 提交改变 attempt 重试起点（重试时工作区已 clean）] → 实现者 prompt 本就要求基于工作区现状工作；`claude --resume` 续跑会话对 git 状态无假设；风险极低，回归覆盖
- [fast-track / repair lane 与 implementer 共用 attempt 循环] → 塌缩 choke point 对所有 lane 统一生效（都是 merge_back 前收口）；锚点 B 按 worktree 载体有无自然分派

## Migration Plan

单仓库内行为增强，无数据迁移。回滚 = revert 对应提交（锚点/塌缩均为独立可逆代码路径，不涉及状态文件 schema 变更）。

## Open Questions

- 塌缩的最终确认在 ready 门评审（D4 推荐 soft-reset 塌缩 vs 备选接受入史）——由本 design 推荐方案进入实现，若评审改选备选，仅需去掉塌缩步骤，锚点部分不受影响。
