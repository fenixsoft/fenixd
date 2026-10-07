# Design: add-killpg-self-guard

## Context

2026-10-07 两起同构团灭事故（-9 与 -15 信号变体，ftrace 取证发送者=pytest 主进程自身）：测试替身 proc 的 pid 怪值流入产品清场代码，`os.getpgid(pid)` 解析到 pytest 自身进程组或 `os.killpg(proc.pid)` 直传命中宿主组，全量套件被杀。替身怪值逐个修是打地鼠（pid=0 修了 `test_knowledge_backfill.py`，`test_codefix_digest_metrics.py` 仍存），需要产品侧统一守卫。

## 全量清场击杀点盘点（grep `os.killpg` 排除探活 `killpg(_, 0)`）

| 形态 | 文件:行 |
|------|---------|
| getpgid 解析型（传成员 pid） | `core/regression.py:737,753`、`core/proc_utils.py:238,246`、`core/adjudication_narrative.py:267,285`、`core/v2_dev_server.py:375,385,396`、`core/knowledge_backfill.py:817`、`core/knowledge.py:543`、`core/worktree_manager/dist_conflicts.py:159,170`、`core/dashboard/ocr_status.py:166,177`、`core/dashboard/routes/architecture_routes.py:535,678,710`、`core/dashboard/session_manager.py:345,405`、`core/hook_engine.py:208`（getpgid 内联） |
| 组长直传型（传独立成组组长 pid） | `core/agent_runner/liveness.py:1056,1063`、`core/agent_runner/maintenance_runs.py:3099,3106,3110` |

探活 `os.killpg(pgid, 0)`（adjudication_narrative/serving_registry/regression 收尾探活）**不在守卫范围**。

## Goals / Non-Goals

- **Goals**：统一守卫助手 + 全部清场击杀点收口；SIGTERM→宽限→SIGKILL 序列语义逐位不变；fail-closed 静默降级；存量替身怪值（`test_codefix_digest_metrics.py` pid=0）修正。
- **Non-Goals**：不改任何「杀整树防孤儿」的业务语义；不动 `os.kill`（单 pid）击杀；不追查 -15 的具体触发测试（独立取证线，另案推进）；不给守卫加配置开关（永远开启）。

## Decisions

### D1. 守卫助手单点收口在 `core/proc_utils.py`

```python
def guard_killpg(target_pid, sig, *, caller: str, resolve: bool = False) -> bool:
    """守卫版 killpg：拒绝击杀调用者自身所在进程组。

    resolve=True：target_pid 为组内成员 pid，先 os.getpgid 解析 pgid；
    resolve=False：target_pid 为独立成组组长 pid，直接作 pgid。
    返回 True=信号已发出；False=守卫拒绝（自身组）或组不存在（ESRCH 语义）。
    """
```

- 解析失败的既有语义分支（ProcessLookupError/OSError → 清场函数按「组已不存在」静默返回）保持——守卫**只新增**「解析结果 == `os.getpgid(0)`」这一个拒绝分支。
- 守卫拒绝时 WARNING 日志（含 caller 标识与目标 pgid），返回 False；调用方对 False 的处理与既有 ESRCH 分支一致（各点已有），不新增控制流。

### D2. 收口是机械替换，语义逐位不变

各点把最后一跳 `os.killpg(pgid, sig)` 换成 `guard_killpg(..., caller="<module>.<func>", resolve=<按形态>)`；SIGTERM→宽限→SIGKILL 序列、探活补刀、异常捕获**逐行不动**。getpgid 内联点（hook_engine.py:208）同步改为 resolve 型调用。**探活 `killpg(_, 0)` 与探活后判断逻辑不改**。

### D3. 分三个里程碑（full 模式分段）

1. **M1 守卫助手 + 高危面**：`proc_utils.py` 助手 + `regression.py`/`proc_utils.py` 自身收口（全量回归门正是受害者路径）+ 守卫单测 + `test_codefix_digest_metrics.py` 怪值修正。
2. **M2 agent_runner 面**：`liveness.py`、`maintenance_runs.py`（组长直传型收口）+ 对应用例。
3. **M3 其余面 + 全量验证**：`v2_dev_server`/`adjudication_narrative`/`knowledge*`/`dist_conflicts`/`ocr_status`/`architecture_routes`/`session_manager`/`hook_engine` + grep 断言测试（core 下清场击杀点 MUST 全部经守卫）+ 全量回归绿。

### D4. 守卫测试用真实进程组验证

用 `subprocess.Popen(start_new_session=True)` 造真实独立组验证「正常清场行为不变」；用替身/`os.getpgid(0)` 断言「自身组被拒绝且留 WARNING」。不 mock `os.killpg` 的拒绝路径断言（真实语义优先，与 2026-10-07 事故取证口径一致）。

## Risks / Trade-offs

- **面广改漏**：M3 的 grep 断言测试（`assert no bare os.killpg( in core except guard`）防回归漂移；允许的例外清单显式枚举（探活调用点）。
- **守卫误拦**：业务上不存在「合法清理自身组」场景（清场永远针对子进程组），误拦面为零。
- **解析型 vs 直传型混淆**：resolve 参数在调用点显式传，code review 时逐点核对形态；D1 docstring 写明两种形态判据。

## Open Questions

（无）
