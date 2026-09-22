# merge-back Capability Spec

## 变更点

- `worktree_manager` merge-back 前：WIP 重叠检测命中（主树脏 tracked 与分支改动路径重叠）时，不再「只预警后照常 merge→pop」；升级为执行级前置处置——默认**自动收纳**（stash 主树重叠改动，合并后恢复），阻塞策略仅显式配置启用。
- `restore_after_merge` 自愈路径保留，但「丢弃 stash 版」MUST NOT 无条件发生：仅当树级 diff 证明 stash 版被合并结果完全取代时才 drop 条目，其余情形保留条目 + 记录去向并逐文件给出核对/找回指引。
- 新增 `signal_type=mergeback_wip_overlap` 告警：由 dispatch 层直发 admin store，且 MUST 收录进 `admin_monitor` 摄取白名单。

## 判定语义

- 主树脏 tracked 与分支改动无重叠（或主树干净）→ 行为逐字节不变（现行 autostash→merge→pop 路径）。
- 有重叠（默认收纳策略）→ 收纳重叠改动 → 照常 merge → 成功后恢复主树 WIP；pop 冲突时保留条目并记录去向，主树 MUST NOT 残留 UU 未合并态。
- 有重叠且显式配置阻塞策略 → merge-back 中止（不 stash、不 merge、不 pop），返回 `wip_gate_blocked=True`，产出 `mergeback_wip_overlap` major 告警等待人工处置。
- 阻塞 MUST NOT 计入 `_merge_fp`/`_merge_streak` 熔断记账，spec MUST NOT 因阻塞被自动 `transition("blocked")`。

#### 闸门作用域（MUST）

- 闸门判定的重叠集合 MUST 排除 `spec/changes/**`：该前缀既被 `ensure_clean_tree` 的 stash 显式排除（覆盖集合不一致会使收纳对它无效），又在主树长期脏（重叠检测按原样纳入会几乎阻塞每一次 merge-back）。该前缀的「主树脏 + 分支同改」沿用既有 `ensure_spec_committed` / `_commit_softened_declaration` 提交通道收口，本 SPEC MUST NOT 为它引入新的 stash/阻塞语义。

#### 策略默认值（MUST 明示）

- 默认策略 MUST 为自动收纳；阻塞 MUST 仅在显式配置时生效（理由：重叠 ≠ 冲突，`worktree_manager.py:2192-2194` 既有注释「不同 hunk 可自动合并」，以 block 为默认把可自动完成的合并转失败属净回归）。

#### stash 前缀隔离（MUST）

- 闸门收纳/保留条目所用前缀 MUST NOT 包含 `AUTOSTASH_MSG_PREFIX` 子串：`reclaim_stale_autostash`（`worktree_manager.py:1794`）以子串匹配栈顶并 pop，复用同前缀会让故意保留待找回的条目被 60s 巡检抢走并沿用丢弃策略。

#### 告警通路（MUST）

- `signal_type=mergeback_wip_overlap` MUST 收录进 `core/admin_monitor.py` 的 `STORED_SIGNAL_TYPES`（:257-275；未收录则摄取循环 :691 跳过，记录石沉大海），`SIGNAL_SEVERITY` 给 major，`SIGNAL_RECOMMENDATION` 给核对指引。
- 告警由 dispatch 层在 merge 结果处理的**失败/阻塞分支**直发（现有 `_report_stash_pop_conflict` 仅成功路径调用，阻塞路径无 emit 点）；`evidence` MUST 先序列化为 `str` 再入 record（dict 穿透会致 Administrator 唤起失败）。
