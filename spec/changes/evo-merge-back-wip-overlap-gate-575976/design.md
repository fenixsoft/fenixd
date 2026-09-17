# merge-back-wip-overlap-gate 设计

## 现状

- `core/worktree_manager.py`：`_list_dirty_tracked_files()`（:1408）提取主树脏 tracked；`_detect_wip_overlap`（:2052-2053）检测与分支改动重叠并仅写入 `MergeConflictInfo.wip_overlap` 供告警；`ensure_clean_tree()`（:1441）merge 前 autostash；`restore_after_merge()`（:1482）pop 冲突自愈（`git checkout -f HEAD` 丢弃 stash 版）。
- `core/pm_engine/dispatch.py`：读 `last_stash_pop_conflicts` / `last_stash_entry_fate` 并入告警文本。

## 改动设计

1. **前置阻塞**：merge-back 入口（`_detect_wip_overlap` 命中且非空）后，若 `MergeConflictInfo.wip_overlap` 非空，则：
   - 记录阻塞原因 + 重叠清单；
   - 产出 `stash_pop_conflict` 同款 major 告警但 `signal_type=mergeback_wip_overlap`，recommended_action 指向人工核对；
   - 默认阻塞（不自动 pop）；配置 `worktree.mergeback_auto_stash_overlap=true` 时改为自动收纳：重叠改动并入 autostash 条目（保留 `AUTOSTASH_MSG_PREFIX` 标记）并标记待回收，随后照常 merge。
2. **自愈保留但显式化**：pop 冲突自愈仍丢弃 stash 版，但告警必须逐文件列出被丢弃清单与找回命令（现状已具备，保留）；新增「丢弃前检查该文件是否为必要改动源」的提示（供人工核对）。
3. **序列化加固**：告警文本组装一律经 `_str_field`（json.dumps 兜底）——修复 66f815db/431f714c 已合入的防护在 dispatch 层全路径生效。

## 兼容与风险

- 无重叠路径零改动；阻塞仅在重叠场景生效，最坏退化为「当前自愈行为 + 更明显告警」。
- 自动收纳模式依赖 stash 栈 LIFO 正确性（既有 `_main_tree_lock` 串行锁已保证 guard 段原子）。