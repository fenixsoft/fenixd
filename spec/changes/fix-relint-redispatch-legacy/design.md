# Design: fix-relint-redispatch-legacy

## Context

`_redispatch_tasks_relint`（`core/pm_engine/dispatch.py`）是 tasks.md 收口复检违规的处置入口。违规成因是把勾选行写坏（典型：`sed` 转义使 `- [x] 1.1` 变成 `^- [x] 1.1`），**首轮的实现工作完全有效**，只是 tasks.md 格式有误。

处置现状：不合并、不推进 → `status=ready` + `error` 写违规明细 + `_retry_count` 递增 → `_enqueue_front(implementer)`。

**缺口**：处置过程中**没有 `register_legacy` 登记**。对照 `_redispatch_for_missing`（交付物守卫缺件打回）：

```python
_wm = self._pm.agent_runner.worktree_manager
_branch = getattr(result, "branch", None)
if _branch and hasattr(_wm, "register_legacy"):
    _wm.register_legacy(spec_name, None, _branch)
```

后果：重派时 `worktree_manager.create` 的 `_take_reusable_worktree` 找不到该 spec 的遗产 → 新建 worktree、从 main HEAD 起新分支 → **首轮分支的已提交成果无人认领、无 prompt 注入**，整支搁浅。

### 相关事实（实测）

| 事实 | 位置 |
|---|---|
| relint 调用点持有 `result`（含 `branch`） | `dispatch.py` full 车道 relint 分支（`getattr(result, "branch", None)` 已在同处用于 `_tasks_md_relint_from_branch`） |
| `register_legacy(spec_name, worktree_path, branch)` 支持「仅分支模式」（`worktree_path=None`） | `worktree_manager.py` |
| `_take_reusable_worktree` 认领条件：遗产在册 且 `reuse==True` 且目录/分支可用 | `worktree_manager.py` |
| 成功收工时 worktree 已被 `cleanup(success=True)` 清理，仅分支留存 | `runner.py` 成功路径 |
| fast-track 车道的 relint 处置走 `_keep_fast_track_worktree`（已有现场保留） | `dispatch.py` 的 `_run_fast_track_flow` |

## Goals / Non-Goals

**Goals:**

- `_redispatch_tasks_relint` 在重派前登记分支遗产，使首轮成果可被下一轮继承。
- 四条打回路径的遗产登记一致性有机械可验的断言（防同类缺口再现）。

**Non-Goals:**

- 不改 relint 的判定逻辑（`_tasks_md_relint_from_branch` / `_tasks_md_relint_from_worktree`）。
- 不改 fast-track 车道（其现场保留机制已存在）。
- 不引入新的 worktree 保留机制——`partial` 收敛不成立形态的 worktree 保留由 `fix-redispatch-loop-governance` 覆盖。

## Decisions

### D1：签名扩展（保持向后兼容）

`_redispatch_tasks_relint(self, spec_name, relint, *, agent_type="implementer", run_id="")` → 新增可选参数承载分支线索：

```
def _redispatch_tasks_relint(
    self, spec_name: str, relint: list, *,
    agent_type: str = "implementer", run_id: str = "",
    branch: str | None = None,
) -> None:
```

- **为什么用 `branch` 而非传整个 `result`**：处置函数只需分支名；传 result 会把 agent 结果结构的耦合面扩大（该函数当前不依赖 `AgentRunResult`，保持这一点便于单测直接调用）。
- 调用点补 `branch=getattr(result, "branch", None)`。
- 既有调用（fast-track 车道不经本函数）与测试无需改动。

### D2：登记时机与条件

登记 MUST 发生在**状态写回与重派之前**（与交付物守卫同序），使 `_legacy` 在下一轮 `create` 时已在册。

条件（与交付物守卫同型，fail-open）：

```
if branch and hasattr(wm, "register_legacy"):
    wm.register_legacy(spec_name, None, branch)
```

- `worktree_path` 传 `None` → **仅分支模式**（成功收工后 worktree 已清理，只剩分支）。
- 分支缺失时静默跳过，MUST NOT 抛异常（处置链路不得因登记失败中断）。
- 登记自身异常 MUST 被捕获降级为 WARNING（与其它非阻塞处置一致）。

### D3：与 `fix-redispatch-loop-governance` 的关系

| 机制 | 覆盖形态 | 手段 |
|---|---|---|
| `fix-redispatch-loop-governance` D4 | `partial` 且收敛不成立 | **保留 worktree 现场**（runner 侧前置判定） |
| 本变更 | relint 违规打回 | **登记分支遗产**（dispatch 侧，仅分支） |

二者语义正交（一个保现场、一个保分支线索），MUST NOT 互相覆盖。`_take_reusable_worktree` 对同一 spec 只保留最新一份遗产（覆盖式更新），故两条机制若同时命中同一轮，以**后登记者为准**——实现时 MUST 确认顺序不会导致现场丢失（worktree 模式遗产含路径，仅分支模式路径为空；以 worktree 模式为准更保守）。

### D4：一致性断言

新增断言覆盖「适用打回路径均登记遗产」：

- 逐条断言：交付物守卫打回后 `_legacy` 在册且可认领（既有）；relint 打回后同样在册且可认领（本变更）。
- 以「遗产在册 + `_take_reusable_worktree` 可认领」为可观测判据（而非断言「调用了某函数」），使实现重构不破坏断言语义。

### D5：不使用绝对行号锚定

## Risks / Trade-offs

- **[风险] 遗产覆盖式更新导致现场丢失** → 缓解：D3 明确两条机制的关系与优先级；实现时确认登记顺序。
- **[风险] 认领到坏现场（tasks.md 仍坏）** → 缓解：继承的是**分支**（含已提交的正确代码），下一轮在此基础上修 tasks.md 即完成——这正是本变更的收益；且 relint 复检在下一轮仍会跑，坏格式不会因继承而被放行。
- **[风险] 与治理 spec 改同一文件** → 缓解：`depends_on` 串行。

## Migration Plan

1. 阶段 1：签名扩展 + 调用点传 branch + 登记逻辑。
2. 阶段 2：测试（relint 打回后遗产可认领 + 无分支安全跳过 + 一致性断言）。
3. 阶段 3：全量回归比对基线。

回滚：单 commit 可整体回退。

## Open Questions

无。
