# spec-merge-rehearsal

## ADDED Requirements

### Requirement: 真合并前预演闸

`merge_back_from_branch` 在执行真合并（stash/merge/abort 序列）之前，MUST 先以 `git merge-tree --write-tree` 做只读预演。预演零冲突时，现行真合并流程 MUST 逐字节不变（含 autostash 收拢、guard 锁、产物自愈、push 语义）。预演自身 MUST NOT 修改主树与分支的任何状态。

#### Scenario: 零冲突预演放行

- **WHEN** 分支与 main 无潜在冲突
- **THEN** 现行真合并流程原样执行，merge 结果与行为同现状无差异

#### Scenario: 预演零副作用

- **WHEN** 预演执行完成（无论结论如何）
- **THEN** 主树无未合并条目、无 MERGE_HEAD、无 stash 栈变化、工作区干净

### Requirement: 语义冲突零污染直通 repair

预演检出冲突且分类含语义文件（`has_semantic_conflict`）时，MUST 跳过 stash/merge/abort 全序列（主树零污染），以结构化结果（冲突路径清单 + 分类）返回调度层；调度层 MUST 直接进入既有 repair 通道（载体现状三态判定不变），该路径 MUST NOT 写入 `_merge_fp`/`_merge_streak`、MUST NOT 将 spec 降级 ready——spec 保持 in-flight，冲突由 repair agent 在实现分支内把 main 合入解决。fp 熔断语义保留给 repair 后 re-merge 失败链（既有 `_repair_round` 轮次上限继续兜底）。

#### Scenario: 语义冲突直通 repair

- **WHEN** fast-track/implementer 收尾 merge-back 预演检出含 src 语义文件的冲突
- **THEN** 主树未被 stash/merge/abort 触碰，repair agent 直接在实现分支上派发，spec 状态未经过 ready 降级，`_merge_streak` 无增量

#### Scenario: repair 轮次上限仍兜底

- **WHEN** 直通 repair 连续超过 `_repair_round` 上限仍无法消化冲突
- **THEN** 回退现行 fallback 重派路径（prompt 注入冲突上下文），不产生无限 repair 循环

### Requirement: 产物冲突保持现行自愈

预演检出全部冲突均为构建产物/ignored-DU 路径时，MUST 放行进入现行真合并流程，由既有产物自愈（对齐 HEAD、从 src 重建）收口，行为与现状一致。

#### Scenario: 产物冲突走自愈真合并

- **WHEN** 预演检出冲突且全部路径属于产物目录
- **THEN** 真合并照常执行，产物自愈完成 merge，不派发 repair

### Requirement: git 版本探测回退

框架 MUST 在进程内一次性探测 `git merge-tree --write-tree` 可用性（git ≥ 2.38）；不支持时 MUST 跳过预演闸、整体回退现行行为，并记一次性 WARNING。

#### Scenario: 旧版 git 回退

- **WHEN** 运行环境 git 版本不支持 `merge-tree --write-tree`
- **THEN** merge_back_from_branch 按现行行为执行（无预演），日志含一次性 WARNING，不反复探测
