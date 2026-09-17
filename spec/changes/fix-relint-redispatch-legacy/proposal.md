# Proposal: fix-relint-redispatch-legacy

## Why

`core/pm_engine/dispatch.py::_redispatch_tasks_relint` 的 tasks.md 收口复检违规处置是**四条打回路径中唯一不注册分支遗产的一条**：

| 打回路径 | 是否注册分支遗产 | 位置 |
|---|---|---|
| 交付物守卫缺件（`_redispatch_for_missing`） | ✅ 有 | `dispatch.py:2429-2431` |
| repair fallback | ✅ 有 | `dispatch.py` repair 通道 |
| 零变更哨 | — （分支零提交，无遗产可登） | — |
| **tasks.md relint 违规（`_redispatch_tasks_relint`）** | ❌ **无** | `dispatch.py:2478-2518` |

后果：relint 违规打回后，spec 回 `ready` 重派 implementer，而**首轮的分支成果既无 `register_legacy` 登记、也无 prompt 注入**——新一轮从 main 新建 worktree、不知道上一轮分支存在，首轮已提交的全部工作**整支搁浅**（只能靠人工从 `git branch` 里翻出来）。

这与 `fix-robustness-edge-cases` 事故是同一族漏洞的另一条路径：**「run 层成功但 spec 层判失败」时成果不被继承**。事故里的实例是收敛判定读源缺陷（已修），本条是 relint 打回缺遗产登记——若当初触发的是 relint 而不是收敛判定，成果同样会全丢。

relint 违规的真实成因（`sed` 转义把 `- [x]` 写成 `^- [x]`）意味着**首轮的实现工作完全有效**，只是 tasks.md 的格式被写坏——这种「工作有效、格式有误」恰好是**最该继承现场**的形态。

## What Changes

- `_redispatch_tasks_relint` MUST 在重派前**注册分支遗产**（`worktree_manager.register_legacy(spec_name, None, branch)`，仅分支模式——与交付物守卫同款），使后继 run 能经 `_take_reusable_worktree` 认领同一分支、继承已提交成果。
- 调用点 MUST 把 `result.branch`（或 `result.worktree_path`）传入处置函数——现有签名只接 `relint` 与 `run_id`，MUST 扩展（保持向后兼容：新增可选参数）。
- 分支为空时（`branch` 缺失/非法）MUST 安全跳过登记（fail-open，不阻断重派）——与交付物守卫的 `if _branch and hasattr(...)` 同型。
- fast-track 车道（`_run_fast_track_flow` 的 relint 处置，走 `_keep_fast_track_worktree`）已有现场保留，MUST NOT 受本变更影响。

## Capabilities

### New Capabilities

- `redispatch-artifact-succession`: 重派时的成果继承契约——四条打回路径 MUST 一致登记分支遗产（或以显式理由说明为何不适用），MUST NOT 存在「工作有效但成果搁浅」的路径。

### Modified Capabilities

（无）

## Impact

- **代码**：`core/pm_engine/dispatch.py`（`_redispatch_tasks_relint` 签名与登记逻辑、full 车道调用点）。
- **API**：零变化（内部处置函数；新增可选参数保持既有调用兼容）。
- **并行约束**：本变更与 `fix-redispatch-loop-governance` **同改 `dispatch.py` 的重派分支**——已登记 `depends_on`，待其收口后执行。
- **测试**：新增 relint 打回后遗产可认领的测试；补四条打回路径的遗产登记一致性断言。
- **运行时**：改 `dispatch.py`，daemon 需重启生效。
