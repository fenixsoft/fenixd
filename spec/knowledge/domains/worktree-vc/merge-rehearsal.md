<!-- knowledge: capability=merge-rehearsal rev=1 sources=spec/archive/2026-09-11-add-merge-tree-rehearsal -->

# 合并预演与语义冲突直通修复

真合并前的只读预演闸：用 `git merge-tree` 提前发现冲突，语义冲突零污染直通 repair，产物冲突放行自愈。

## 现行规则

- 真合并前预演闸：`merge_back_from_branch` 在执行真合并（stash/merge/abort 序列）之前 MUST 先以 `git merge-tree --write-tree` 做只读预演；预演零冲突时真合并流程逐字节不变（含 autostash 收拢、guard 锁、产物自愈、push 语义）。
- 预演零副作用：预演无论结论如何，主树无未合并条目、无 MERGE_HEAD、无 stash 栈变化、工作区干净。
- 语义冲突零污染直通 repair：预演检出冲突且分类含语义文件（`has_semantic_conflict`）时，跳过 stash/merge/abort 全序列（主树零污染），以结构化结果（冲突路径清单 + 分类）返回调度层，调度层直接进入既有 repair 通道；该路径不写 `_merge_fp`/`_merge_streak`、不将 spec 降级 ready——spec 保持 in-flight，冲突由 repair agent 在实现分支内把 main 合入解决。fp 熔断语义保留给 repair 后 re-merge 失败链，`_repair_round` 轮次上限继续兜底（超限回退 fallback 重派，prompt 注入冲突上下文，不产生无限 repair 循环）。
- 产物冲突放行自愈：预演检出冲突且全部为构建产物/ignored-DU 路径时，放行进入真合并流程，由既有产物自愈（对齐 HEAD、从 src 重建）收口，不派发 repair。
- git 版本探测回退：进程内一次性探测 `git merge-tree --write-tree` 可用性（git ≥ 2.38）；不支持时跳过预演闸、整体回退无预演行为，记一次性 WARNING，不反复探测。

## 溯源

- 2026-09-11 add-merge-tree-rehearsal — 新增真合并前只读预演闸、语义冲突零污染直通 repair（不记指纹不降级）、产物冲突放行自愈与旧版 git 一次性探测回退
