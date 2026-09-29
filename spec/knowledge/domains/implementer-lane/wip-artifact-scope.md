<!-- knowledge: capability=wip-artifact-scope rev=2 sources=spec/archive/2026-09-23-evo-merge-back-wip-artifact-scope,spec/archive/2026-09-23-fix-artifact-paths-hardcoded-default -->

# WIP 产物范围判定

构建产物路径的判定语义与配置契约——判定集合完全由项目配置声明（框架不内置任何默认产物路径），以及 merge-back WIP 重叠闸门对配置产物的排除与 stash 前置对齐。

## 现行规则

- 判定完全配置驱动：构建产物路径判定器（`ArtifactPathMatcher`）的判定集合完全由配置声明。未配置 `worktree.build_artifact_paths` 且未声明 `worktree.has_build_artifacts` 时判定集合为空，`is_artifact()` 对任意路径返回假（「未裁决」语义，触发起草通路，见 [artifact-path-declaration](artifact-path-declaration.md)）。框架自身仓库的产物路径与其它项目一样须显式配置声明，不享有硬编码豁免。
- 配置形态（`worktree.build_artifact_paths`，字符串列表，两种形态）：
  - 目录前缀：不含 `*` 且 MUST 以 `/` 结尾——路径以该串开头即判为产物；
  - 文件通配：含 `*`——以 `fnmatch.fnmatchcase` 匹配**完整相对路径**（不只匹配 basename）；模式不含 `/` 时 MUST NOT 命中含 `/` 的路径，模式含 `/` 时按完整相对路径匹配（可命中多层）。
- 规范化与容错：非字符串项、不含 `*` 且未以 `/` 结尾的项（防 `dist` 误匹配 `dists/`）、绝对路径或含 `..` 路径段的项一律丢弃并记 WARNING；配置形态非法（非列表等）判定器构造不抛异常；全部项非法或配置为空列表 → 判定集合为空（不回退任何默认集合）。
- 消费点一律用实例判定器：merge 预演闸语义冲突分类（`non_artifact`）、merge 冲突后自愈分类、产物对齐 HEAD 与 stray 移除、ref 下产物路径集合枚举、dist 重建的 `src_touched` 判定，全部消费实例级判定器（含项目配置），不消费包级自由函数。
- WIP 重叠集合排除配置产物：`_detect_wip_overlap()` 的重叠集合（主树脏 tracked ∩ merge-base..branch 改动）排除判定为产物的路径，主树产物的未提交改动不进入重叠集合；`spec/changes/**` 的既有排除独立保留，不与产物排除合并为一条规则。
- merge-back guard 段 stash 前置对齐：在 guard 段 stash **之前**，把重叠集合中判定为产物的子集对齐 HEAD（`git checkout HEAD -- <path>`），使其不进 stash、不参与 `stash pop`，从而不产生产物类 `last_stash_pop_conflicts` 与 `stash_pop_conflict` 告警。约束：
  - 只作用于重叠集合；主树独有、分支未触碰的产物脏改动 MUST NOT 被对齐，仍走既有 stash/pop 往返回到主树；
  - 逐路径容错：单路径对齐失败不放弃其余路径、不阻塞 merge-back、不跳过 stash，失败路径回落现行行为（并入重叠集合、照旧 stash）；
  - `wip_overlap` 上报与 `mergeback_wip_overlap_policy=block` 的阻塞判定只基于对齐后的语义集合。

## 关键行为

merge-back 触发 → WIP 重叠计算时排除配置产物 → 重叠产物在 stash 前对齐 HEAD（产物是 src 的投影，merge 后由构建重建）→ 纯产物重叠不产生 stash、pop 冲突与 major 告警；语义文件重叠照常走既有闸门与告警链路。

## 溯源

- [2026-09-23 2026-09-23-evo-merge-back-wip-artifact-scope](spec/archive/2026-09-23-evo-merge-back-wip-artifact-scope/) — 产物判定改为实例化可配置判定器（时带内置默认集合），五消费点改用实例判定器；WIP 重叠集合排除配置产物；merge-back guard 段 stash 前置对齐重叠产物
- [2026-09-23 2026-09-23-fix-artifact-paths-hardcoded-default](spec/archive/2026-09-23-fix-artifact-paths-hardcoded-default/) — 废除内置默认判定集合，判定完全配置驱动；未配置从「回退默认」改为「未裁决（恒非产物）」；空/非法配置的回退目标改为空集合
