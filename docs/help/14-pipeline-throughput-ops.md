# 14 管道吞吐运维（并发、merge 预检与重启排水）

本文面向运维/管理员，说明影响管道吞吐的三个配置面：派发并发槽位、merge-back 前置预检、重启排水窗口。改任何一项都只涉及项目运行时配置 `.fenix/config.yaml`（模板见 `.fenix/config.template.yaml`），改完约 30 秒配置热更新生效，无需重启 daemon。

## 并发槽位（agents.max_concurrent）

**现状缺省**：代码缺省值 5（`core/pm_engine/dispatch/queue.py`），模板推荐值 5。

**查看当前生效值**：`.fenix/config.yaml` 的 `agents.max_concurrent` 键；未写该键即用代码缺省 5。

**人工调整**（编辑 `.fenix/config.yaml`）：

```yaml
agents:
  max_concurrent: 5   # 显式配置优先于代码缺省；写 3 即回到旧并发
```

**上调前的资源前提自查**：

- **worktree 磁盘**：每个并发实现 run 一个独立 worktree，约占 N × 仓库大小。上调前确认 `worktree.base_dir` 所在盘剩余空间充足。
- **网关并发压力**：N 路并发 run 会放大模型网关的并发请求与长尾。框架侧已有瞬断熔断与 failover 治理兜底，但网关侧配额需自行确认。
- **回归锁串行化**：多个 run 同时到达收尾回归检查点时，由 full-suite.lock 主机级互斥锁串行执行（等待上限 600s、超时 skip），并发上调不改变回归互斥语义，只增加锁排队时长。

**回退**：把 `.fenix/config.yaml` 的 `agents.max_concurrent` 改回原值（如 3）或删除该键（回到代码缺省），等待热更新生效即可。正在飞的 run 不受影响。

## merge-back 前置预检（merge-back-precheck）

**行为**：merge-back 发起前计算「主树 WIP 脏文件集 ∩ 分支触碰文件集」，交集非空时**不发起 merge**，发人工升级告警（含交集文件清单与两侧来源），spec 保持可重试状态。人工清理主树 WIP（`git add/commit` 或 `git stash push`）后重新放行该 spec（ready 重派）即可继续 merge-back。

**策略配置**（`worktree.mergeback_wip_overlap_policy`）：

- 缺省（未配置）：`escalate`——交集非空即拦截升级人工；
- 显式 `auto`：保留旧自动收纳语义（重叠改动 stash 收纳，merge 后恢复；pop 冲突时保留条目并记录去向）；
- 显式 `block`：并入升级出口（与 escalate 同为拦截）。

**逃生门**（`worktree.merge_precheck_bypass`，缺省 false）：`true` 时跳过预检直接 merge（紧急推送用），冲突时按既有 merge 失败路径处理。用完建议改回 false——它跳过的是对用户未提交改动的保护。

**误拦（假阳性）处置**：交集判据是保守的（不同 hunk 本可自动合并的重叠也会被拦）。确认无真实冲突时，清理/提交主树 WIP 后重试，或临时开逃生门。

## 重启排水窗口（agents.run_drain_max_seconds）

**现状缺省**：60 秒（代码缺省，`core/config.py` 的 `get_run_drain_max_seconds`）。专管 daemon restart（`.fenix/restart_request` 触发）时等待在飞 run 收尾的时长上限；常规停机仍走 `admin.shutdown_drain_seconds`（缺省 1800）语义不变。

**协调规则**：`agents.run_drain_max_seconds` MUST ≤ `admin.shutdown_drain_seconds`——supervisor 的 SIGKILL 等待 = `shutdown_drain_seconds + 120s` 余量，满足不等式即保证排水窗口不会被强杀截断。两者均显式配置且违反时配置加载直接报错；只显式调大 run_drain 时读取面按 `min(run_drain, shutdown)` 夹紧。`shutdown_drain_seconds=0`（快速停机）时 restart 联动为不排水。

**人工调整**（编辑 `.fenix/config.yaml`）：

```yaml
agents:
  run_drain_max_seconds: 600   # 给长排水留裕量（如知道在飞 run 接近收尾）
```

**restart 时发生什么**：daemon 收到 restart_request → 停止新派发 → 向每个在飞 run 广播一次 checkpoint 信号（写 `.fenix/runs/<run_id>.checkpoint.json` 旗标，促使实现侧尽快落盘进度声明收尾；不识别该信号的 run 不受影响）→ 等待至多 `run_drain_max_seconds` → 超窗的 run 按既有路径强杀并保全分支续做。

**排查**：排水起止与广播清单见 daemon 日志 `Drain: planned restart ...` / `Drain finished after ...` 两行；广播旗标写入失败逐 run 记 WARNING（不影响排水）。

## 相关文档

- [配置参考](09-config.md)：全键参考与合并规则
- [调度与治理规则](06-governance.md)：预算、重试、告警分级、熔断
- [保障机制](07-safeguards.md)：merge-back 闸门与告警分级
