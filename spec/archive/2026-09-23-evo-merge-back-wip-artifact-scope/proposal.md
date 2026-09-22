# Proposal: merge-back-wip-artifact-scope

## Why

「构建产物路径判定」`_is_build_artifact_path()`（`core/worktree_manager/__init__.py:74`）
只有一条硬编码规则：路径以 `core/dashboard/static/` 开头、且其下任一层级含 `dist`
目录。该判定被复用在 **4 条语义不同的调用路径**上（merge 预演闸、merge 冲突自愈、
WIP 重叠闸门、dist 清账），因此对「构建产物在仓库根」的项目形态完全失效。

**本项目（fenix-desktop）正是这种形态**：`vite.config.ts` + `scripts/package.sh`
把扩展产物输出到**仓库根级 `dist/`**（tracked、未被 .gitignore 忽略），发布包
`fenix-newtab-v1.0.0.zip` 亦在仓库根。对这两个路径，`_is_build_artifact_path()`
恒返回 `False` —— 产物被当作**语义内容**处置。

实测两处后果：

1. **噪声级（已发生 2 次纯产物形态）**：`_detect_wip_overlap()` 用「主树脏
   tracked ∩ merge-base..branch 改动」求交，主树一份未提交的旧构建产物即命中 →
   合并 guard 段 stash → merge-back 后 `stash pop` 与分支侧新产物冲突 → 自愈保
   HEAD、**条目判为「未取代」而保留**，并直发一条 `severity=major` 的
   `stash_pop_conflict` 告警唤起 Administrator。逐次实证（fenix-desktop
   `.fenix/admin_alerts.json`）：
   - quick-links-standalone-sync：`conflict_files` 4 文件（`dist/index.html`、
     `fenix-newtab-v1.0.0.zip`、`src/components/PanelFrame.tsx`、`src/index.css`）；
   - stock-standalone-sync：`conflict_files` 2 文件（`dist/index.html`、
     `fenix-newtab-v1.0.0.zip`），`wip_overlap` 4 路径**全为产物**；
   - （框架自身 evo-admin-signal-consolidation 的 `core/admin_store.py` 是真实源码
     冲突——`conflict_files` 与 `wip_overlap` 均**只**含语义文件，非本形态。）

   **决定修法的机制事实**：真正把主树改动卷进 stash 的**不是闸门**，而是
   `mergeback.py:100` 的 `ensure_clean_tree()`——它在闸门放行后**无条件**对全树
   tracked 脏改动执行 stash（路径集 `.` + `:(exclude)spec/changes`，
   `stash_guard.py:85-97`）；闸门只决定「stash 条目前缀」
   （`WIP_GATE_STASH_PREFIX` vs `AUTOSTASH_MSG_PREFIX`）与 `wip_overlap` 的上报
   内容。因此**仅把产物移出重叠集合不足以切断链路**：产物照样被 stash、照样在 pop
   时与分支侧新产物真冲突，`last_stash_pop_conflicts` 照样被填
   （`mergeback.py:107-111`）→ `queue.py:930` 照样直发 major 告警
   （`rollback.py:142-159`）。stock-standalone-sync 那个 2 文件形态（重叠集全为
   产物）正是如此：排除后 `wip_overlap=[]`，但两文件仍在主树脏 tracked 中，仍被
   autostash 卷走。故本 SPEC MUST 使产物的「可丢弃」语义在 **stash 之前**落地
   （见 What Changes 第 3 条）。

   两次纯产物形态的 stash 版**零独有内容**（管理员逐项核对：产物差异仅为旧引用
   vs 新引用，stash 版已被合并结果完全取代），告警纯属误报，却各消耗一轮
   Administrator run。注意 quick-links 那次的冲突清单还含两个源文件（其内容与
   分支已提交版一致）——**该形态属语义重叠，其告警不受本 SPEC 影响**，本 SPEC
   只根治「重叠集全为产物」的形态。

2. **损失级（尚潜伏）**：`_resolve_build_artifact_conflicts()` 的产物自愈分支
   （`git checkout HEAD -- p` 对齐 → 重建）与 `_rehearse_merge_from_branch()` 的
   `non_artifact` 语义冲突分类都依赖同一判定。主树产物脏改动与分支改动一旦在同一
   hunk **真冲突**，该冲突会被判为 **semantic** —— 纯产物问题被送进 repair 通道
   （无谓的重派/评审循环），而不是走既有的产物自愈。

**判定方向的风险不对称**：「误判为产物」（噪声、可自愈）与「漏判产物」（送进语义
通道、阻塞）代价不同。因此本 SPEC 不选「按构建命令猜产物目录」（弱规则在存在性
校验类场景会误伤真实源码文件），而选**严格可配置的产物前缀**：默认值等于框架现行
有效集合（`core/dashboard/static`），产品项目须显式声明自己的产物根。

## What Changes

- **新增产物路径判定器模块 `core/worktree_manager/artifact_paths.py`**：把
  `_is_build_artifact_path` 从「全局常量 + 单条硬编码规则」改为「**每个
  WorktreeManager 实例持有一组可配置前缀 + 一组包级默认前缀**」的判定器。
  - 默认前缀（包级常量，向后兼容）：`core/dashboard/static`（现行唯一有效规则）；
  - 实例前缀由构造参数注入，来源为配置 `worktree.build_artifact_paths`
    （字符串列表 + 文件后缀通配形态，如 `dist/`、`*.zip`）；
  - 判定语义：路径匹配任一前缀/后缀即视为产物；**配置为空/缺失/非法时回退默认值**
    （判定器自身故障 MUST NOT 让产物判定变宽或失效）。
- **全部产物判定调用点改用实例判定器**（`mergeback.py:310/546/548`、
  `dist_conflicts.py:71/123/277/374`——含 `_rebuild_dist_after_merge` 的
  `src_touched` 判定）：不再从包命名空间导入自由函数，改走
  `self._artifacts.is_artifact(...)` / `paths_in(...)` / `non_artifacts_in(...)`
  实例方法。
- **merge-back guard 段前置丢弃重叠产物**（切断误报链路的必要一步）：
  `_wip_overlap_gate()` 在 `ensure_clean_tree()` **之前**，把 WIP 重叠集合中判定
  为产物的子集对齐 HEAD（`git checkout HEAD -- <p>`，与
  `_resolve_build_artifact_conflicts` 的「产物无条件对齐 HEAD」同语义），使其不再
  脏、不进 stash、pop 无产物冲突 → 从源头消除「产物 → stash → pop 冲突 → 误报
  major 告警」。**只作用于重叠子集**（主树独有、分支未触碰的产物改动仍走既有
  stash/pop 往返，MUST NOT 被丢弃），对齐失败逐路径容错并回退现行行为（并入重叠
  集合、照旧 stash/告警），MUST NOT 阻塞 merge-back。
- **`fenixd.py` 注入配置**：`worktree.build_artifact_paths` 解析后随既有
  `mergeback_wip_overlap_policy` 一并传入 `WorktreeManager` 构造。
- **`.fenix/config.template.yaml` 补默认值段**（含注释说明本项目的推荐值形态）。
- **Dashboard 配置面**：`core/dashboard/data/config_admin.py` 的 `worktree` 缺省
  字典与受管键/来源标注落点补 `build_artifact_paths`；`VerifyPanel.tsx` 与
  `dashboard.ts` 增加该键的只读展示（说明其语义与当前生效值）。
- **测试**：新增前缀判定矩阵单测；补 merge 语义冲突分类与 WIP 重叠闸门在「根级
  `dist/` 属产物」配置下的行为断言。
- **存量告警**：本次 SPEC 不自动清理历史 `stash_pop_conflict` 告警（属 admin store
  历史记录，由 Administrator 处置闭环）；`fenix-desktop` 主树残留的产物脏改动由
  后续 hook/打包流程自然收敛。

## Capabilities

### New Capabilities

- `wip-artifact-scope`：构建产物路径判定的**作用域可配置性** —— 默认前缀集合、
  项目级前缀/后缀配置语义、判定器接口与故障回退、以及五个消费点（merge 预演闸 /
  merge 冲突自愈 / dist 清账 / WIP 重叠闸门 / **merge-back guard 段 stash 前的
  产物前置对齐**）对该判定的消费契约。

### Modified Capabilities

- `stashpop-conflict-treatment`（已归档 2026-09-14）：其「merge-back 前 WIP 重叠
  预检」的判定集 MUST 排除配置声明的产物路径，且被排除的产物 MUST 在 guard 段
  stash **之前**对齐 HEAD —— 产物既不进重叠集合、也不进 stash，从源头消除
  「产物重叠 → stash → pop 冲突 → 误报告警」链路。（仅移除重叠集合不足以切断
  该链路：`ensure_clean_tree` 仍会无条件卷走全树脏 tracked，见 Why 的机制事实。）

## Impact

- **代码**：`core/worktree_manager/artifact_paths.py`（新增）、
  `core/worktree_manager/__init__.py`（默认前缀常量与 re-export）、
  `core/worktree_manager/mergeback.py`、`core/worktree_manager/dist_conflicts.py`、
  `core/worktree_manager/lifecycle.py`（构造参数）、`fenixd.py`（注入）。
- **配置与前端**：`.fenix/config.template.yaml`、
  `core/dashboard/data/config_admin.py`、
  `core/dashboard/static/src/pages/settings/components/VerifyPanel.tsx`、
  `core/dashboard/static/src/services/dashboard.ts`（构建产物由 `npm run build` 重建）。
- **测试**：新增 `tests/test_worktree_wip_artifact_scope.py`；
  调整 `tests/test_worktree_stray_and_identical.py` 相关断言。
- **风险**：判定变宽会把**语义改动误判为产物**并被静默丢弃（历史事故家族
  `fix-mergeback-stashpop-silent-loss`）——故默认值只含框架现行有效路径，产品项目
  须显式声明；配置解析失败一律回退默认（保守）。另一风险是 `dist/` 前缀若过宽会
  把 `dist/` 下的**手写源码**（本仓库不存在，但形态上可能）误判——由「前缀必须含
  目录分隔符、后缀通配必须带 `*`」的校验约束把误配拦在配置写入侧。
