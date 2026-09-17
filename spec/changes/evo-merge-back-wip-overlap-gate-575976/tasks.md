## Deliverables

```yaml
- path: core/worktree_manager/mergeback.py
  kind: modify
- path: core/pm_engine/dispatch/queue.py
  kind: modify
- path: core/admin_monitor.py
  kind: modify
- path: core/dashboard/static/src/pages/activities/index.tsx
  kind: modify
- path: tests/test_worktree_merge_guard.py
  kind: modify
```

## 1. 落地校验

- [ ] 1.1 core/worktree_manager.py：merge-back 前 WIP 重叠命中升级为执行级前置处置——**默认策略 = 自动收纳（stash）**，阻塞策略仅显式配置（`worktree.mergeback_wip_overlap_policy=block` 或等价开关）启用；阻塞时返回携带 `wip_gate_blocked=True` 的可区分失败（不 stash、不 merge、不 pop，主树零污染）与重叠清单
- [ ] 1.2 core/worktree_manager.py：**闸门作用域**——重叠判定集合 MUST 排除 `spec/changes/**`（与 `ensure_clean_tree` 的 `:(exclude)spec/changes`（:1559）覆盖集合一致）；该前缀长期脏（实测主树 34 个脏 tracked `spec/changes/**`）且被 stash 排除，纳入闸门会分别导致「收纳无效」与「几乎每次 merge-back 阻塞」；其脏由既有 `ensure_spec_committed` / `_commit_softened_declaration` 收口，本 SPEC 不新增语义
- [ ] 1.3 core/worktree_manager.py：收纳/保留条目所用 stash 前缀 MUST NOT 包含 `AUTOSTASH_MSG_PREFIX` 子串（`reclaim_stale_autostash` 以子串匹配栈顶并 pop，:1794；复用会让 60s 巡检抢走故意保留的条目）
- [ ] 1.4 core/worktree_manager.py：pop 冲突路径删除「**无条件**丢弃 stash 版」可能路径，保留既有「树级 diff 证明被合并结果完全取代才 drop」判定（`_drop_superseded_stash_entry`，:1676），保留条目 + 写 `last_stash_entry_fate`，主树 MUST NOT 残留 UU 未合并态；被丢弃/保留文件逐文件列出核对提示与找回命令
- [ ] 1.5 core/pm_engine/dispatch.py：**阻塞路径旁路熔断**——`wip_gate_blocked=True` 时跳过 `_merge_fp`/`_merge_streak` 记账、跳过 ready 降级、跳过 repair 通道（对照 `rehearsed=True` 豁免，:1090-1096）；两处 merge 结果处理站点（:1083 主通道、:2796 `_reconcile_and_merge` fast-track）均须覆盖，spec 保持 in-flight
- [ ] 1.6 core/pm_engine/dispatch.py：新增 `_report_mergeback_wip_overlap` 并在 `not merge_ok` 分支（阻塞路径）直发 admin 告警——`signal_type=mergeback_wip_overlap`、severity major；**告警发出点在 dispatch 层**（worktree_manager 只回报状态），成功收纳路径的文案扩展并入既有 `_report_stash_pop_conflict`（:1669-1770）；文案含重叠清单、策略、`git stash list`/`git show <sha>:<file>` 找回命令与处置指引
- [ ] 1.7 core/pm_engine/dispatch.py：告警组装经 `_str_field` 序列化兜底——该 helper 实现在 `core/agent_runner/prompt_builder.py:40`（dispatch 层无此 helper），按导入或本地同语义实现处理，`evidence` 一律先转 `str`（dict 穿透 `str.replace` 会致 Administrator 唤起失败）
- [ ] 1.8 core/admin_monitor.py：`STORED_SIGNAL_TYPES` 收录 `mergeback_wip_overlap`（:257-275），否则摄取循环 :691 跳过、记录石沉大海；`SIGNAL_SEVERITY` 给 major（缺省即 major，:776）、`SIGNAL_RECOMMENDATION` 给核对指引
- [ ] 1.9 core/dashboard/static/src/pages/activities/index.tsx：`SIGNAL_LABEL`（:64）加 `mergeback_wip_overlap` 标签映射
- [ ] 1.10 闸门自身异常（git 命令失败/超时）退化为现行行为：不阻塞、不新增 stash、不误拦合并

## 2. 测试

- [ ] 2.1 tests/test_worktree_merge_guard.py：新增用例——重叠 + 阻塞策略 → merge-back 中止且返回 `wip_gate_blocked=True`、主树保持可写且无文件被丢弃、无 stash 被创建
- [ ] 2.2 tests/test_worktree_merge_guard.py：新增用例——默认（收纳）策略下重叠改动被收纳并成功 merge，未提交内容可在 stash 中找到且 merge 后主树 WIP 已恢复
- [ ] 2.3 tests/test_worktree_merge_guard.py：新增用例——仅 `spec/changes/**` 重叠（主树 tasks.md 脏 + 分支同改）→ 闸门不阻塞、不收纳，沿用现行行为
- [ ] 2.4 tests/test_worktree_merge_guard.py：新增用例——无重叠 / 主树干净时 merge-back 行为与既有用例逐字节一致（回归无破坏）
- [ ] 2.5 tests/test_pm_engine_dispatch_fixes.py：阻塞路径 → admin_alerts 出现 handled=false 的 `mergeback_wip_overlap` 记录（description 含重叠清单与找回命令），且 `_merge_streak` 未累计、spec 未被 `transition("blocked")`（连续两次阻塞亦然）
- [ ] 2.6 回归：`tests/test_pm_engine_dispatch_fixes.py`、`tests/test_worktree_stray_and_identical.py`、`tests/test_worktree_merge_guard.py` 既有用例全绿（尤其 `last_stash_pop_conflicts` 语义与 `_drop_superseded_stash_entry` 判定不被破坏）
