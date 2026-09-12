## Context

fast-track 死活的唯一判据是 `_run_fast_track_flow`（dispatch.py:1944）读到的 `.fenix-run-result.json`。读取链 `_read_implementer_result`（engine.py:724）按「活跃 worktree → 主树共享 `.fenix/.fenix-run-result.json`」回退；共享文件是跨 spec 单例，任何 spec 成功都会由 runner 拷回覆盖（runner.py:2310，无条件写）。

当前死亡语义：`ft_result is None` → 一律判「run 死亡」→ 预算豁免 + reset ready + 自动重派。此判据不查实现分支是否已有提交。add-main-tree-deps-provision run1 提交 5 个 commit 仍被判死亡重派即由此：结果文件缺失时，回退读到的共享文件是上一 spec（add-spec-content-integrity-gate）的残留，stamp 守卫正确 ignore → 返回 None → 走死亡路径，5 个已提交 commit 被丢弃。

约束：`result.branch` 仅在 `result.success` 为真时填充（runner.py:2644）；失败/中断 run 的 branch 为空。

## Goals / Non-Goals

**Goals:**

1. 结果文件缺失时，凡实现分支已有提交的 fast-track run 不再被当死亡重派，成果保留并 merge。
2. 缺失的 verdict 由完整模式 verifier 补齐（不合成、不架空 fail-closed 门），随后走既有 verified→done 门。
3. 主树共享结果文件的读取收紧为 fail-closed，关闭「无 stamp 残留被误采信」的洞，并清理已消费残留。

**Non-Goals:**

- 不引入 runner 层 fast-track 产物硬门（对齐 planner 的 `_check_agent_result_artifact`）——那会把失败改成原地退避重试，语义不同，本次不做。
- 不改 full 车道 implementer 的死亡/零变更路径（其成功路径已由 `_implementer_zero_change` 的 rev-list 判定覆盖分支零提交场景）。
- 不做结果文件 schema 变更、无数据迁移、无 UI。

## Decisions

**D1 — 提取 `_branch_has_commits` helper，复用 rev-list 判定。**
在 verification.py 提取 `_implementation_branch_has_commits(result)`（`git rev-list --count main..<branch>` > 0），并让 `_implementer_zero_change`（verification.py:2508）与之共用判定；`result.branch` 为空或 rev-list 失败一律返回 False（conservative → 走重派，不吞风险）。
- 备选：在 dispatch 死亡路径内联 rev-list。—— 拒绝：重复逻辑，`_implementer_zero_change` 已有同款判定，应单一来源。

**D2 — 死亡路径分流：有提交 → merge + 升级补验证。**
在 `_run_fast_track_flow` 的 `ft_result is None` 分支，先跑 D1 判定：
- 有提交：调用 `_reconcile_and_merge(spec_name, result)` 合并；成功后改写 `.spec.yaml` mode→full 并 `_enqueue(spec_name, "verifier")`（复用 `_escalate_to_full_mode` 的 mode-改写 + enqueue 语义，抽成可复用方法或新增变体，触发因「结果文件缺失」而非 bug-found）；merge 失败沿用 `_reconcile_and_merge` 既有处置（保留 worktree + 重派/熔断）。
- 无提交/无 branch：走现有 `_handle_fast_track_failure`（死亡豁免 + reset ready + 重试），原封不动。

关键语义：此路径 merge 发生在**无** `_hard_check_fast_track` 的状态（无结果文件可校验）；框架侧逐场景 fail-closed 校验被**整体移交**给完整模式 verifier 的既有门（verify.yaml 契约 + verdict evidence），不损失校验强度（完整模式 verifier 较 fast-track 硬校验更严格）。
- 备选 A（合成 `verdict=passed`）：拒绝——架空验证门，漏 bug 风险（用户已明确否）。
- 备选 B（blocked 交人工）：拒绝——保守但保留人工，用户已选 merge+补验证。

**D3 — 主树共享文件 stamp 守卫收紧为 fail-closed。**
`_read_implementer_result` 对主树 fallback 文件：把「`stamped and stamped != spec_name` 才 ignore」改为「`stamped != spec_name`（含 None/空/非字符串）即 ignore」。关闭无 stamp 残留被误采信为当前 spec 结果的 fail-open 洞。worktree 文件同规则收紧（worktree 复用为同 spec，stamp 应严格匹配）。
- 备选：仅对主树 fallback 收紧、worktree 维持宽松。—— 拒绝：worktree 复用也可能带旧 spec 残留，统一收紧更稳。

**D4 — 消费后清理共享文件，锚定「快照落盘后」单点。**
删除点 = 采信消费 + `_write_impl_result_snapshot` 落盘 per-spec 快照之后（fast-track 与 implementer 成功收口各自单点）。删除失败仅 WARNING（fail-open），残留由 D3 严格校验兜底拒绝。不在 `_read_implementer_result` 内删（一读即删会误伤多读者，verifier/门禁仍可能读同一文件）。

## Risks / Trade-offs

- [死亡分流误判有提交 → 漏掉「实现内容其实错误」] → 缓解：merge 后补的完整模式 verifier 有 verify.yaml 契约 + verdict evidence 双重 fail-closed 门，比 fast-track `_hard_check_fast_track` 更严格；verdict=bug-found 走既有打回/升级链路。
- [rev-list 失败或 branch 为空时漏放行] → 缓解：D1 判 False 一律走重派（conservative fail-open），绝不因判定器故障放行。
- [merge 成功但 enqueue verifier 失败/verifier 未补出 verdict] → 缓解：spec 停留 implemented，由既有 verifier 重试/监测机制兜底；不 return 到 done。
- [共享文件删除与多读者竞态] → 缓解：删除锚定快照落盘后单点，且 stamp 严格校验兜底；删除失败 fail-open。
- [D3 收紧可能使某些合法但 stamp 缺失的旧结果文件被拒] → 评估：当前写入侧（agent 结果契约）一律带 spec stamp，legacy 无 stamp 文件本就不该被采信；收紧方向正确。

## Migration Plan

- 纯代码变更，无数据迁移。回滚 = revert 提交，行为退回到「结果文件缺失一律重派」。
- 无配置键新增（不涉及 Dashboard UI 能力）。