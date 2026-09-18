# Design: merge-back-wip-artifact-scope

## Context

### 现状代码事实（已核实）

`core/worktree_manager/__init__.py:63-79`：

```python
DASHBOARD_STATIC_ROOT = "core/dashboard/static/"

def _is_build_artifact_path(path: str) -> bool:
    """构建产物路径判定：static 根下任一层级 dist 目录内的文件。"""
    if not path.startswith(DASHBOARD_STATIC_ROOT):
        return False
    parts = path[len(DASHBOARD_STATIC_ROOT):].split("/")
    return len(parts) >= 2 and "dist" in parts[:-1]
```

调用点（`grep` 实证，排除 `.claude/worktrees/` 下的副本）：

| 文件:行 | 语义 | 判定为假时的后果 |
|---|---|---|
| `mergeback.py:310` | merge 预演闸：`non_artifact` 非空即判语义冲突 → 直通 repair 通道 | 纯产物真冲突被送进 repair 循环 |
| `mergeback.py:546/548` | merge 冲突后分类：`self_heal_applicable` / `has_semantic_conflict` | 产物自愈不适用 → abort + 分类为语义 |
| `dist_conflicts.py:71` | `_resolve_build_artifact_conflicts`：产物冲突无条件对齐 HEAD | 不进入自愈分支，返回 False |
| `dist_conflicts.py:123` | 清账：分支侧干净 add 的 stray 产物移除 | 旧产物残留累积 |
| `dist_conflicts.py:277` | `_rebuild_dist_after_merge`：`src_touched` 判定（static 根下**非**产物路径） | 判定与实例口径脱钩（首子句仍以 `DASHBOARD_STATIC_ROOT` 限定作用域，见 Non-Goals） |
| `dist_conflicts.py:374` | `_artifact_paths(ref)`：列出某 ref 下的产物路径集 | 集合为空，对齐/移除全失效 |

`mergeback.py:172` `_detect_wip_overlap()` 用「主树脏 tracked ∩
`merge-base..branch` 改动」求交，只排除 `spec/changes/**`，**不含产物排除**。

`mergeback.py:96-102` merge-back guard 段：闸门 `_wip_overlap_gate()` 之后
**无条件**调用 `ensure_clean_tree()`——「主树改动是否被卷进 stash」由
`ensure_clean_tree` 决定（路径集 `.` + `:(exclude)spec/changes`，
`stash_guard.py:85-97`），闸门只决定 stash 条目前缀与 `wip_overlap` 上报内容。

### 本项目形态（fenix-desktop）

- 产物根：仓库根级 `dist/`（`vite.config.ts` 构建输出，tracked）；
- 发布包：仓库根 `fenix-newtab-v1.0.0.zip`（`scripts/package.sh` 产出，tracked；
  `scripts/upload_release_to_cos.py` 钩子每次 done/pushed 重打包）；
- 结果：上述 4 个调用路径对本仓库的产物**全部判定为假**。

## Goals / Non-Goals

**Goals**

- 产物判定作用域可配置：项目可声明自己的产物根（前缀）与产物文件（后缀通配）。
- 默认行为与现行逐字节兼容（未配置的项目零行为变化）。
- 消除**纯产物**形态的「产物重叠 → guard 段 stash → pop 冲突 → 误报 major
  告警」链路（含 D3b 的「stash 前置丢弃重叠产物」）。语义文件重叠仍按既有语义
  告警（不是本 SPEC 的目标，见 D3b 实证）。
- 判定器故障（配置非法/解析异常）一律**回退默认**，绝不放宽判定。

**Non-Goals**

- 不改 `_heal_unmerged_files` / `_drop_superseded_stash_entry` 的自愈与 drop 语义。
- 不引入「按构建命令自动推断产物目录」的启发式（弱规则在存在性校验类场景会误伤
  真实源码文件）。
- 不自动清理历史 `stash_pop_conflict` 告警与主树存量产物脏改动。
- 不改 `mergeback_wip_overlap_policy`（auto/block）语义与其默认值。
- **不改产物的「重建触发作用域」**：`_rebuild_dist_after_merge` 的 `src_touched`
  与 `_run_dist_build` 仍以 `DASHBOARD_STATIC_ROOT`（`core/dashboard/static`）
  限定（`dist_conflicts.py:230/277`）。故「产物在仓库根」的项目（如 fenix-desktop）
  merge 后**不会**被框架自动重建产物，须由项目自身构建 hook（如
  `scripts/upload_release_to_cos.py` 的 done/pushed 重打包）刷新——本 SPEC 不为其
  新增重建通道。

## Decisions

### D1：判定器独立成模块，实例持有前缀集合

新增 `core/worktree_manager/artifact_paths.py`，导出：

```python
DEFAULT_ARTIFACT_PREFIXES = ("core/dashboard/static",)   # 框架既有有效集合

def normalize_artifact_patterns(raw) -> list: ...
    """把配置值规范化为 (kind, pattern) 列表；非法项丢弃并记 WARNING。"""

class ArtifactPathMatcher:
    """产物路径判定器（每实例一份，线程内只读）。"""
    def __init__(self, patterns=None, defaults=None): ...  # defaults=None → DEFAULT_ARTIFACT_PREFIXES
    def is_artifact(self, path: str) -> bool: ...
    def paths_in(self, paths) -> list: ...        # 过滤出产物
    def non_artifacts_in(self, paths) -> list: ... # 过滤出语义路径
```

**为什么独立模块而非继续用包级自由函数**：判定语义从「全局常量」变为「实例状态」，
继续放在 `__init__.py` 会把配置解析引入包导入路径并制造 import 环
（`mergeback`/`dist_conflicts` 已从本包命名空间解析常量，见其模块头注释）。
新模块只依赖标准库（`pathlib`/`fnmatch`），可被任何调用方安全导入。

**包级 `_is_build_artifact_path` 保留**：作为「默认判定」的向后兼容别名
（`core/worktree_manager/__init__.py` 继续导出，`tests/test_characterization_giant_classes.py`
等既有引用零改动），其实现改为委托 `ArtifactPathMatcher(DEFAULT_ARTIFACT_PREFIXES)`。

### D2：配置形态 —— 前缀 + 后缀通配两类

`worktree.build_artifact_paths`：

```yaml
worktree:
  build_artifact_paths:
    - "dist/"                      # 目录前缀（强制以 / 结尾），本仓库产物根
    - "fenix-newtab-*.zip"         # 文件通配（含 *），本仓库发布包
```

- **前缀**（不含 `*`，MUST 以 `/` 结尾）：路径以该串开头即产物；
- **通配**（含 `*`）：以 `fnmatch.fnmatchcase` 匹配**完整相对路径**（不匹配
  basename——basename 匹配会把任意深度的同名文件误判为产物）；
- **校验**（写入侧 + 解析侧双保险）：不含 `*` 又未以 `/` 结尾 → 丢弃并 WARNING；
  前后空白/非字符串项 → 丢弃；绝对路径或含 `..` → 丢弃。

**为什么默认值只含 `core/dashboard/static`**：判定变宽会把语义改动误判为产物并被
静默丢弃（`fix-mergeback-stashpop-silent-loss` 事故家族）。默认值 = 现行有效集合，
产品项目显式声明后行为才变宽——「宁严谨不误伤」。

**为什么用「配置」而非「自动探测」**：产物根是项目结构事实，构建命令成功/失败都
可能留下产物；从 `commands.build` 反推目录（如 `npm run build` → `dist/`）在存在性
校验类场景会把 `dist/` 下的手写文件一并判为产物。显式声明让变更可审计、可回滚。

### D3：作用域 —— 4 个调用路径全部改用实例判定器

| 调用路径 | 改造 |
|---|---|
| `mergeback._rehearse_merge_from_branch` | `non_artifact` 改 `self._artifacts.non_artifacts_in(conflict_paths)` |
| `mergeback` 冲突分类（2 处） | 同上，改 `self._artifacts.is_artifact(p)` / `all(...)` / `any(...)` |
| `dist_conflicts` 三处 | `_artifact_paths()` 改 `self._artifacts.paths_in(...)`；stray 判定改实例方法 |
| `mergeback._detect_wip_overlap` | `_detect_wip_overlap` 保持只读、语义不变；由 `_wip_overlap_gate` 在返回前切分产物/语义子集（见 D3b） |

**为什么 WIP 重叠闸门也要排除产物（本 SPEC 的核心动机）**：闸门的作用是「主树未
提交改动与分支改动重叠时先收纳再合并」。产物的未提交改动**不需要保护**——产物是
`src` 的投影，会被重新构建覆盖；把它纳入重叠集合只会制造必然的 pop 冲突与误报告警。
排除后本仓库的实际事故不会再触发**闸门**（不再有 `WIP_GATE_STASH_PREFIX` 条目、
不再按 `policy=block` 阻塞纯产物重叠）；但**仅此一步不足以切断告警链路**，见 D3b。

**`_detect_wip_overlap` 仍保留 `spec/changes/**` 排除**（语义不同，勿合并）：
`spec/changes/**` 是「框架运行必需、有独立提交通道」，产物是「可再生的投影」。

### D3b：产物重叠子集在 stash 之前对齐 HEAD（切断误报链路的关键一步）

**为什么必须有这一步（实证）**：真正把主树改动卷进 stash 的是
`ensure_clean_tree()`（`mergeback.py:100`，闸门放行后**无条件**执行；路径集 `.` +
`:(exclude)spec/changes`，见 `stash_guard.py:85-97`），**不是闸门**——闸门只决定
stash 条目前缀（`WIP_GATE_STASH_PREFIX` vs `AUTOSTASH_MSG_PREFIX`）与
`wip_overlap` 的上报内容。因此 D3 把产物移出重叠集合后：产物**依旧脏、依旧被
stash**，pop 时依旧与分支侧新产物冲突，`last_stash_pop_conflicts` 依旧被填
（`mergeback.py:107-111`）→ `queue.py:930` 依旧直发 `severity=major` 告警
（`rollback.py:142-159`）。

实证：fenix-desktop `.fenix/admin_alerts.json` 的 `stock-standalone-sync` 记录，
`conflict_files=["dist/index.html","fenix-newtab-v1.0.0.zip"]`、`wip_overlap` 四路径
**全为产物** —— 即「排除后 overlap=[]」也拦不住这两文件被 autostash 卷走。
对照既有先例：闸门对 `spec/changes/**` 的排除之所以成立，是因为该前缀**同时**被
autostash 的 `:(exclude)spec/changes` 排除（`mergeback.py:180-186` docstring 已写明
「收纳对它无效」）——产物没有这层对偶，MUST 另行处理。

**做法**（在 `_wip_overlap_gate()` 内、`ensure_clean_tree` 之前；该调用点
`mergeback.py:96` 位于 `_main_tree_lock` 内，无需新增锁）：

1. `overlap = self._detect_wip_overlap(branch)`——**该方法保持只读、语义不变**；
2. 按实例判定器切分：`artifact_overlap = [p for p in overlap if
   self._artifacts.is_artifact(p)]`，其余为 `semantic_overlap`；
3. `artifact_overlap` 非空 → 逐路径 `git checkout HEAD -- <p>`（与
   `_resolve_build_artifact_conflicts` 的「产物无条件对齐 HEAD」同语义：产物是
   `src` 的投影，merge 后由构建重建），并记 INFO 日志（含路径清单，可审计）；
4. 对齐失败（返回码非 0 / 超时 / `OSError`）的路径**逐路径**回落：并入
   `semantic_overlap`——即退回现行行为（照旧 stash、照旧可能 pop 冲突与告警）。
   **fail-safe 方向 = 与现行行为一致**：MUST NOT 因对齐失败而阻塞 merge-back、
   MUST NOT 跳过 stash、MUST NOT 改宽判定；
5. 返回（与上报、与 `policy=block` 判定）的 `wip_overlap` = 对齐后的语义集合
   ——纯产物重叠不再阻塞 merge-back。

**作用域约束（防数据丢失，MUST）**：对齐只作用于**重叠子集**（既是主树脏
tracked、又是 `merge-base..branch` 改动的那部分）。主树独有、分支未触碰的产物脏
改动 **MUST NOT** 被对齐——它们由既有 stash/pop 往返返回主树，本无冲突风险；若
一并丢弃，等于把「用户本地刚构建、分支根本没碰」的产物静默抹掉，属净回归。

### D4：构造注入与故障回退

```python
# lifecycle.py G1LifecycleMixin.__init__
build_artifact_paths=None,          # 新增构造参数（缺省 None → 默认前缀）

# 构造体内
self._artifacts = ArtifactPathMatcher(
    normalize_artifact_patterns(build_artifact_paths)
) if build_artifact_paths else ArtifactPathMatcher()
```

`fenixd.py` 在既有 `_wip_policy` 附近注入：

```python
_artifact_paths = self.config.get("worktree.build_artifact_paths", None)
```

`normalize_artifact_patterns` 对任何异常（非列表/含非法项/全非法）**返回空列表**，
`ArtifactPathMatcher(patterns=[])` 的语义是「只用默认前缀」——判定器故障 MUST NOT
让判定变宽（也不缩窄：默认集合是现行有效集合）。

### D5：测试策略

新增 `tests/test_worktree_wip_artifact_scope.py`：

1. **判定矩阵**：默认前缀命中（`core/dashboard/static/**/dist/x.js` 真）；
   根级 `dist/x.js` 默认**假**、配置 `dist/` 后**真**；`fenix-newtab-1.0.0.zip`
   配置 `*.zip` 后真；非法项（无 `/` 结尾、含 `..`、非字符串）被丢弃且不影响
   其余项；空前缀列表 → 等价默认。
2. **WIP 重叠闸门**：主树脏 `dist/index.html` + 分支同改，配置产物后
   `_detect_wip_overlap` 仍返回该路径（只读口径不变），但 `_wip_overlap_gate`
   的返回/上报集合**不含**该路径，且该路径被对齐 HEAD（`git checkout HEAD --`
   调用以桩断言）、`last_stash_pop_conflicts` 为空。
3. **预演闸分类**：冲突全为配置产物时 `rehearsed` 为 None（放行真合并）；
   含语义路径时返回 `MergeConflictInfo(rehearsed=True)`。
4. **故障回退**：`build_artifact_paths="not a list"` / `[123, None]` →
   构造不抛异常、行为等价默认。
5. **兼容性**：不传 `build_artifact_paths` 时 `_is_build_artifact_path` 的行为与
   现行逐字节一致（既有 `test_worktree_stray_and_identical` 断言不回退）。
6. **链路切断（D3b 核心验收）**：纯产物重叠 → 对齐命令以产物路径为参数被调用、
   `wip_overlap` 与 `last_stash_pop_conflicts` 均为空；主树独有产物 → 对齐未被
   调用、仍走 stash/pop 往返；对齐失败 → 路径并入 `wip_overlap` 且不阻塞；
   语义重叠 → 对齐不接收该路径、闸门按 policy 照常处置。

### D6：前端与配置面的最小落点

按项目约定「新增配置项必须带 Dashboard 界面」，`worktree.build_artifact_paths` 在
验证契约页（`VerifyPanel.tsx`）以**只读文本**呈现当前生效值，并附一行说明
（语义 + 推荐值形态）。**不做可编辑表单**：该键是列表形态，编辑体验与校验成本高，
且误配后果是静默丢弃语义改动（高风险）；只读展示 + 手工编辑 config.yaml + 热重载
的路径已足够，且变更可审计。

`config_admin.py` 需覆盖：①缺省字典（两处：用户级与项目级）②`worktree` 段合并
应用分支 ③`write_config` 前置校验（列表形态 + 逐项规范化）④验证页来源标注
`_SOURCE_KEYS`。受管键白名单 `_SYNC_PAGE_KEYS["verify"]` **不含**该键（只读、不参与
「同步用户级设置」写入）。

## 兼容性与风险

- **默认零变化**：未配置项目判定集合恒等于现行 `DASHBOARD_STATIC_ROOT` 规则，
  4 个调用路径行为逐字节不变（D5-5 断言）。
- **误扩风险**：配置项由人工写入、有格式化校验、有只读展示可核对；且失败方向是
  「产物自愈处理语义文件」——仅当人工把语义路径写进配置才可能发生，属显式误配。
- **`dist/` 前缀宽度**：本仓库 `dist/` 内全是构建输出（无手写源码），前缀安全；
  校验要求前缀以 `/` 结尾，避免 `dist` 前缀意外匹配 `dists/`、`distfoo/`。
- **对齐丢弃（D3b）**：前置对齐会丢弃主树**重叠子集**的产物改动——该改动本身
  可再生（产物 = `src` 投影），且作用域被「重叠子集」与「配置显式声明」双重
  收窄、有 INFO 日志可审计、失败方向是回退现行行为。主树独有产物改动不受影响。
- **重建作用域（Non-Goals）**：产物在仓库根的项目 merge 后不会被框架自动重建
  （`src_touched` 仍限 `core/dashboard/static`），须由项目自身构建 hook 刷新；
  本 SPEC 不新增重建通道，判定器改造不改变 `_rebuild_dist_after_merge` 的触发面。
- **并发**：判定器构造后只读，无锁需求；`WorktreeManager` 单实例注入。D3b 的
  对齐在 `_main_tree_lock` 内执行（`_wip_overlap_gate` 的唯一调用点所在）。
