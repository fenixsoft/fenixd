## ADDED Requirements

### Requirement: 产物前缀判定的默认作用域

系统 SHALL 提供构建产物路径判定器，其**默认**（未配置时）判定集合 MUST 等于框架
现行有效集合：包级常量 `DEFAULT_ARTIFACT_PREFIXES`，当前值为
`("core/dashboard/static",)`。

默认判定语义（未配置 `worktree.build_artifact_paths` 时）MUST 与既有
`_is_build_artifact_path()` 逐字节一致：路径以默认前缀开头、且其下任一层级含
`dist` 目录（`dist` MUST NOT 为末段）即视为产物。

#### Scenario: 默认前缀下 dashboard 产物判定为真

- **WHEN** 判定路径 `core/dashboard/static/v3/dist/assets/a.js`（未配置任何前缀）
- **THEN** 判定 MUST 为真

#### Scenario: 默认前缀下根级 dist 判定为假

- **WHEN** 判定路径 `dist/index.html` 或 `dist/assets/a.js`（未配置任何前缀）
- **THEN** 判定 MUST 为假（默认集合不含根级产物）

#### Scenario: 默认前缀下 dist 为末段时判定为假

- **WHEN** 判定路径 `core/dashboard/static/dist`（`dist` 为末段，非目录层级）
- **THEN** 判定 MUST 为假

### Requirement: 项目级产物前缀与通配配置

系统 SHALL 支持通过配置 `worktree.build_artifact_paths`（字符串列表）扩展产物
判定集合。配置项 MUST 支持两种形态：

1. **目录前缀**：不含 `*` 且 MUST 以 `/` 结尾 —— 路径以该串开头即判定为产物；
2. **文件通配**：含 `*` —— 以 `fnmatch.fnmatchcase` 匹配**完整相对路径**
   （MUST NOT 只匹配 basename）。

配置项 MUST 经规范化后生效，非法项 MUST 被丢弃并记 WARNING，MUST NOT 使判定器
构造失败：

- 非字符串项（数字/None/嵌套结构）MUST 丢弃；
- 不含 `*` 且未以 `/` 结尾的项 MUST 丢弃（防 `dist` 误匹配 `dists/`）；
- 绝对路径或含 `..` 路径段的项 MUST 丢弃（仓库外/越界路径非本项目产物）；
- 全部项非法或配置为空列表 → 判定集合 MUST 等于默认集合。

#### Scenario: 目录前缀生效

- **WHEN** 配置 `worktree.build_artifact_paths: ["dist/"]`，判定路径
  `dist/index.html`
- **THEN** 判定 MUST 为真

#### Scenario: 文件通配生效且限定完整路径

- **WHEN** 配置 `worktree.build_artifact_paths: ["fenix-newtab-*.zip"]`，判定
  路径 `fenix-newtab-v1.0.0.zip`
- **THEN** 判定 MUST 为真

#### Scenario: 通配不匹配任意深度的同名文件

- **WHEN** 配置 `worktree.build_artifact_paths: ["*.zip"]`，判定路径
  `src/vendor/pkg.zip`
- **THEN** 判定 MUST 为假。`*` MUST NOT 跨 `/`：`fnmatch.fnmatchcase` 的 `*`
  语义是「匹配任意字符（含 `/`）」，故实现 MUST 在其之上追加约束——模式**不含**
  `/` 时 MUST NOT 命中含 `/` 的路径（本场景）；模式**含** `/` 时按完整相对路径
  匹配（可命中多层路径）

#### Scenario: 未以斜杠结尾的前缀被丢弃

- **WHEN** 配置 `worktree.build_artifact_paths: ["dist"]`
- **THEN** 该项 MUST 被丢弃并记 WARNING，判定集合 MUST 回退默认——路径
  `dists/a.js` MUST NOT 被判为产物

#### Scenario: 越界路径被丢弃

- **WHEN** 配置 `worktree.build_artifact_paths: ["../other-repo/dist/", "/abs/dist/"]`
- **THEN** 两项 MUST 均被丢弃，判定集合 MUST 回退默认

#### Scenario: 配置形态非法时回退默认而非报错

- **WHEN** `worktree.build_artifact_paths` 的值为字符串（非列表）或 `[123, None]`
- **THEN** 判定器构造 MUST NOT 抛异常，判定集合 MUST 等于默认集合

### Requirement: 产物判定调用路径全部改用实例判定器

系统 SHALL 让以下 4 条调用路径消费**实例级**判定器（含项目配置），MUST NOT 继续
直接消费包级自由函数：

1. `_rehearse_merge_from_branch`：语义冲突分类（`non_artifact` 计算）；
2. merge 冲突后分类：`self_heal_applicable` 与 `has_semantic_conflict` 判定；
3. `_resolve_build_artifact_conflicts`：产物对齐 HEAD 与 stray 移除；
4. `_artifact_paths(ref)`：某 ref 下产物路径集合枚举；
5. `_rebuild_dist_after_merge` 的 `src_touched` 判定（`dist_conflicts.py:277`；
   其首子句 `p.startswith(DASHBOARD_STATIC_ROOT)` 保持不变——重建触发作用域不在
   本 SPEC 范围）。

包级 `_is_build_artifact_path` MUST 保留为「默认判定」别名并继续导出（既有测试
引用零改动），其实现 MUST 委托默认判定器。

#### Scenario: 预演闸对配置产物放行

- **WHEN** 主树与分支在 `dist/index.html` 冲突，且 `dist/` 已在
  `worktree.build_artifact_paths` 中
- **THEN** `_rehearse_merge_from_branch` MUST 返回 `None`（放行现行真合并流程），
  MUST NOT 返回 `rehearsed=True` 的语义冲突

#### Scenario: 预演闸对语义路径仍拦截

- **WHEN** 主树与分支在 `src/panels/notes/NotesApp.tsx` 冲突
- **THEN** MUST 返回 `rehearsed=True` 的 `MergeConflictInfo`，且 `conflict_paths`
  MUST NOT 含配置声明的产物路径

#### Scenario: 包级别名保持默认语义

- **WHEN** 直接调用包级 `_is_build_artifact_path("dist/index.html")`
- **THEN** MUST 返回 False（默认集合不含根级产物，与配置无关）

### Requirement: WIP 重叠集合排除配置产物

系统 SHALL 让 `_detect_wip_overlap()` 的重叠集合排除配置声明的产物路径——主树产物
的未提交改动 MUST NOT 进入重叠集合。

`spec/changes/**` 的既有排除 MUST 保留（两者语义不同，MUST NOT 合并为一条规则）。

#### Scenario: 产物脏改动不计入重叠

- **WHEN** 主树有未提交的 `dist/index.html` 与 `fenix-newtab-v1.0.0.zip`，分支
  同时改动这两个路径，且两者均已在 `worktree.build_artifact_paths` 中
- **THEN** `_detect_wip_overlap` 返回的清单 MUST NOT 含这两个路径；若无其他重叠
  文件，MUST 返回空列表（闸门不触发、MUST NOT stash）

#### Scenario: 语义文件重叠仍计入

- **WHEN** 主树有未提交的 `src/panels/notes/NotesApp.tsx`，分支同改该文件
- **THEN** `_detect_wip_overlap` 返回的清单 MUST 含该路径（闸门照常按
  `worktree.mergeback_wip_overlap_policy` 处置）

#### Scenario: spec/changes 排除不被产物配置影响

- **WHEN** 主树长期脏的 `spec/changes/foo/tasks.md` 与分支同改，且
  `worktree.build_artifact_paths` 未声明该路径
- **THEN** 该路径 MUST 仍被排除出重叠集合（既有语义保持不变）

### Requirement: merge-back 前置丢弃重叠产物

系统 SHALL 在 merge-back 的 guard 段 stash **之前**，把 WIP 重叠集合中判定为配置
产物的部分对齐 HEAD（`git checkout HEAD -- <path>`），使其不进入 stash、不参与
`stash pop`，从而不产生产物类 `last_stash_pop_conflicts` 与随之而来的
`stash_pop_conflict` 告警。

> 依据：`ensure_clean_tree()`（`core/worktree_manager/mergeback.py:100`）在闸门
> 放行后**无条件**卷走全树 tracked 脏改动（`stash_guard.py:85-97`），闸门只决定
> stash 条目前缀与 `wip_overlap` 上报内容——故「只把产物移出重叠集合」不足以
> 阻止产物被 stash 与 pop 冲突。

- 对齐 MUST 只作用于重叠集合（主树脏 tracked ∩ `merge-base..branch` 改动）中
  判定为产物的路径。
- 主树**独有**、分支未触碰的产物脏改动 MUST NOT 被对齐——它们 MUST 仍走既有
  stash/pop 往返回到主树。
- 对齐 MUST 与 `_resolve_build_artifact_conflicts` 的「产物无条件对齐 HEAD」
  同语义（产物是 `src` 的投影，merge 后由构建重建）。
- 对齐 MUST 逐路径容错：单路径失败 MUST NOT 放弃其余路径、MUST NOT 阻塞
  merge-back、MUST NOT 跳过 stash；失败路径 MUST 回落到现行行为（并入重叠集合、
  照旧 stash），即失败方向 MUST 与现行行为一致。
- 上报的 `wip_overlap` 与 `worktree.mergeback_wip_overlap_policy=block` 的阻塞
  判定 MUST 只基于对齐后的语义集合。

#### Scenario: 纯产物重叠不产生 stash 与告警

- **WHEN** 主树脏 tracked 仅含 `dist/index.html` 与 `fenix-newtab-v1.0.0.zip`，
  分支同改这两路径，且两者均已在 `worktree.build_artifact_paths` 中
- **THEN** 两者 MUST 被对齐 HEAD；`wip_overlap` MUST 为空、闸门 MUST NOT 阻塞；
  merge-back 完成后 `last_stash_pop_conflicts` MUST 为空（无产物进 stash、无 pop
  冲突、无 `stash_pop_conflict` 告警）

#### Scenario: 语义重叠仍走既有 stash 与告警

- **WHEN** 主树脏 tracked 含 `src/panels/notes/NotesApp.tsx`，分支同改该文件
- **THEN** 该路径 MUST NOT 被对齐，MUST 进入 `wip_overlap`，按
  `worktree.mergeback_wip_overlap_policy` 处置；pop 冲突时照旧产生
  `stash_pop_conflict` 告警（既有语义不被本 SPEC 放宽）

#### Scenario: 主树独有产物改动不被丢弃

- **WHEN** 主树脏 tracked 含 `dist/index.html`，但分支**未**改动该路径
- **THEN** 该路径 MUST NOT 被对齐，MUST 走既有 stash/pop 往返并最终回到主树

#### Scenario: 对齐失败回退现行行为

- **WHEN** 对某产物路径执行 `git checkout HEAD -- <path>` 返回非 0（或超时）
- **THEN** 该路径 MUST 并入 `wip_overlap`（照旧被 stash），merge-back MUST NOT
  因对齐失败而阻塞或跳过 stash
