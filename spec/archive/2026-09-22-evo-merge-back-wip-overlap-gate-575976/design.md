# merge-back-wip-overlap-gate 设计

> **同源草案关系（MUST 先收敛）**：`spec/changes/evo-merge-back-wip-overlap-gate/`（capability `worktree`，`.spec.yaml` created 2026-09-16）与本目录为**同一需求的同源草案**，两者在「默认策略」上互相矛盾（本目录默认阻塞，sibling 默认自动收纳）。实现前 MUST 收敛为一份：以本文件的默认策略与约束为基准（默认自动收纳、阻塞仅显式配置启用），避免出现两套语义不同的 merge-back 闸门。

## 现状（行号已按当前主树核对）

- `core/worktree_manager.py`：
  - `AUTOSTASH_MSG_PREFIX`（:40）autostash 条目前缀。
  - `_list_dirty_tracked_files()`（:1490-1523）提取主树脏 tracked 清单——**不排除** `spec/changes`。
  - `ensure_clean_tree()`（:1525-1575）merge 前 autostash，stash pathspec 显式 `:(exclude)spec/changes`（:1559）。
  - `_detect_wip_overlap(branch)`（:2208-2260）检测与分支改动重叠，**只写 `MergeConflictInfo.wip_overlap` 供告警、不阻断**（命中仅记 WARNING：「warning only, merge proceeds」）；调用点 :2195。
  - `merge_back_from_branch()`（:2155）`_main_tree_lock` 内串行：预演闸 → `_detect_wip_overlap` → `ensure_clean_tree` → 真合并 → finally `restore_after_merge`。
  - `restore_after_merge()`（:1577+）pop 冲突自愈：对 UU 文件 `git checkout -f HEAD -- <file>` **丢弃 stash 版工作区内容**、`git reset` 清 UU；条目仅在树级 diff 证明被合并结果完全取代时 drop（`_drop_superseded_stash_entry`，:1676）。
  - `reclaim_stale_autostash()`（:1757-1795）周期巡检（60s）：**主树干净 + 栈顶条目名含 `AUTOSTASH_MSG_PREFIX` 子串**（:1794）时 pop，冲突沿用上述自愈丢弃策略。
- `core/pm_engine/dispatch.py`：
  - merge 结果处理站点两处：`dispatch.py:1083`（主通道）与 `dispatch.py:2796`（`_reconcile_and_merge`，fast-track 通道）。
  - 失败分支：预演语义冲突以 `rehearsed=True` 豁免（:1090-1096）→ 其余 `not merge_ok` 一律做指纹熔断记账 `_merge_fp`/`_merge_streak`（:1100-1152），`streak >= agents.merge_breaker_threshold`（默认 2）即 `transition(spec, "blocked")` 冻结。
  - 成功分支：`_report_stash_pop_conflict`（:1669-1770）经 `AdminStore.append` 直发 `signal_type=stash_pop_conflict` major 告警——**仅成功路径调用（:1210）**，失败/阻塞路径当前无任何 emit 点。
- `core/admin_monitor.py`：`STORED_SIGNAL_TYPES` 白名单（:257-275）；不在白名单的 signal 记录在摄取循环被 `continue` 跳过（:691）——落 store 后无人摄取（先例事故见 :267-274 注释「信号石沉大海」）。
- `core/dashboard/static/src/pages/activities/index.tsx`：`SIGNAL_LABEL` 映射（:64）。
- `_str_field`（json.dumps 兜底）实现在 `core/agent_runner/prompt_builder.py:40`，**dispatch 层无此 helper**。

## 改动设计

1. **前置处置入口（默认自动收纳，阻塞仅显式配置启用）**
   - 在 `merge_back_from_branch` 的 guard 锁内、`ensure_clean_tree` 之前，`_detect_wip_overlap` 结果升级为执行级前置（不再是「只预警」）。
   - **默认策略 = 自动收纳（stash）**：以可识别前缀 stash 主树重叠改动 → 照常 merge → 成功即恢复；pop 冲突时保留 stash 条目（仅「树级 diff 证明被合并结果完全取代」才 drop）并记录去向 `last_stash_entry_fate`。
   - **阻塞策略仅 `worktree.mergeback_wip_overlap_policy=block`（或等价布尔开关）显式配置时生效**：返回携带 `wip_gate_blocked=True` 的可区分失败（不 stash、不 merge、不 pop，主树零污染），并派发 `mergeback_wip_overlap` 告警。
   - 理由（regression 约束）：**重叠 ≠ 冲突**——`worktree_manager.py:2192-2194` 既有注释明示「不同 hunk 可自动合并」；以阻塞为默认会把当前能自动完成的 merge-back 转成失败，属净回归。
2. **闸门作用域 MUST 与 autostash 可覆盖集合一致（排除 `spec/changes/**`）**
   - `_list_dirty_tracked_files` 不排除 `spec/changes`，而 `ensure_clean_tree` 的 stash 显式 `:(exclude)spec/changes`（:1559）→ 原样复用会同时得到两种失效：收纳对 `spec/changes/**` **无效**（不在 stash 里，merge 仍可能被 `local changes would be overwritten` 拒绝）、阻塞对该前缀则**几乎每次都触发**（实测当前主树即有 34 个脏 tracked `spec/changes/**` 文件，`git status --porcelain`）。
   - 约定：闸门判定的重叠集合 = 脏 tracked ∩ 分支改动 ∩ **非 `spec/changes/**`**；该前缀的「主树脏 + 分支同改」由既有提交通道 `ensure_spec_committed` / `_commit_softened_declaration` 收口，本 SPEC MUST NOT 为它引入新的 stash/阻塞语义。
3. **阻塞路径 MUST NOT 落入 merge 熔断**
   - 阻塞是「前置拦截」而非「merge 失败」；若原样返回失败，两处结果处理站点会对同一指纹连续记账，`streak >= 2` 即把 spec 冻结为 `blocked`（框架对被冻结 spec 无自动回程）——比现状更差。
   - 约定：阻塞返回 MUST 携带 `wip_gate_blocked=True`，dispatch 两处站点（:1083、:2796）MUST 据此跳过 `_merge_fp`/`_merge_streak` 记账与 ready 降级，保持 spec in-flight 并只发告警等待人工处置；先例：`rehearsed=True` 走同类豁免（:1090-1096）。
4. **告警通路（归属与白名单，MUST）**
   - 归属：`worktree_manager` 只负责检测/处置并回报 `MergeConflictInfo`（`wip_overlap`、`wip_gate_blocked`）；**admin 告警由 dispatch 层直发**——新增 `_report_mergeback_wip_overlap(spec_name, merge_info)`，在 `not merge_ok` 且 `wip_gate_blocked` 时调用（成功收纳路径可复用既有 `_report_stash_pop_conflict` 的文案扩展）。现状 `_report_stash_pop_conflict` 仅在成功路径调用（:1210），阻塞路径无 emit 点，必须新增。
   - 白名单：`signal_type=mergeback_wip_overlap` MUST 收录进 `core/admin_monitor.py` 的 `STORED_SIGNAL_TYPES`（:257-275），否则 :691 直接跳过 → 记录落 store 后无人摄取、Administrator 不唤起（即本 SPEC 的「显式告警」目标落空）。`SIGNAL_SEVERITY` 给 `major`（缺省即 major，:776）、`SIGNAL_RECOMMENDATION` 给核对指引；前端 `activities/index.tsx` 的 `SIGNAL_LABEL`（:64）加一行标签。
   - 文案 MUST 含：spec 名、重叠文件清单、策略（阻塞/已收纳）、找回命令（`git stash list` / `git show <sha>:<file>`）、处置指引（提交或 stash 主树改动后再合）。
5. **前缀隔离（MUST，与既有巡检隔离）**
   - 收纳/保留条目所用前缀 MUST NOT 包含 `AUTOSTASH_MSG_PREFIX` 子串：`reclaim_stale_autostash` 以子串匹配栈顶并 pop（:1794），复用同前缀会让「故意保留待人工找回」的闸门条目被 60s 巡检抢走并沿用丢弃策略，去向记录随即失真。
6. **「保留 stash 版」的确定语义（MUST）**
   - = **保留 stash 条目 + 记录去向**（`last_stash_entry_fate`，经既有 admin 告警消费点 `dispatch.py:1706-1762`），**不是**把主树留在 UU 未合并态（后者致 index 半合并、index.lock 满、后续 git 写操作瘫痪——:1590-1595 既有不变量）。
   - MUST NOT 删除既有「树级 diff 证明完全取代才 drop」的正确判定（`_drop_superseded_stash_entry`，:1676）；「杜绝静默丢弃」落为「删除**无条件**丢弃路径 + 去向可见」，并逐文件列出核对提示。
7. **序列化加固**：dispatch 层无 `_str_field`（实现在 `core/agent_runner/prompt_builder.py:40`）。约定：新增告警组装从该模块导入该 helper（或本地实现同语义函数），`evidence`/`context` 一律先序列化为 `str` 再入 record，防止 dict 穿透 `str.replace` 致 Administrator 唤起失败（fix-alert-evidence-render-crash 先例）。

## 阻塞/收纳后的恢复路径（MUST 明示）

- 收纳策略（默认）：无人工介入，merge-back 照常完成；WIP 在 merge 后恢复，pop 冲突被丢弃的文件逐文件列出去向与找回命令。
- 阻塞策略（显式配置）：spec 保持 in-flight（不入熔断），人工处置 = 提交或 stash 主树重叠改动后重新放行该 spec；放行通道沿用既有 ready 重派（必要时应把主树 WIP 清干净，或改用默认收纳策略）。

## 兼容与风险

- 无重叠 / 主树干净：零改动，行为逐字节不变。
- 有重叠但不同 hunk（可自动合并）：默认收纳下行为与现状连续（收纳→合并→恢复），仅告警文案更明确；仅显式配置 block 时才转为阻塞。
- 自动收纳依赖 stash 栈 LIFO 正确性（既有 `_main_tree_lock` 串行锁已保证 guard 段原子），且前缀与 `reclaim_stale_autostash` 隔离（见设计 5）。
- 风险兜底：闸门自身异常（git 命令失败/超时）MUST 退化为现行行为（不阻塞、不新增 stash），不得因闸门故障误拦合并。
