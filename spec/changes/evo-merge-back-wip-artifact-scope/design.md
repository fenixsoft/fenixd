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
| `dist_conflicts.py:374` | `_artifact_paths(ref)`：列出某 ref 下的产物路径集 | 集合为空，对齐/移除全失效 |

`mergeback.py:176` `_detect_wip_overlap()` 用「主树脏 tracked ∩
`merge-base..branch` 改动」求交，只排除 `spec/changes/**`，**不含产物排除**。

### 本项目形态（fenix-desktop）

- 产物根：仓库根级 `dist/`（`vite.config.ts` 构建输出，tracked）；
- 发布包：仓库根 `fenix-newtab-v1.0.0.zip`（`scripts/package.sh` 产出，tracked；
  `scripts/upload_release_to_cos.py` 钩子每次 done/pushed 重打包）；
- 结果：上述 4 个调用路径对本仓库的产物**全部判定为假**。

## Goals / Non-Goals

**Goals**

- 产物判定作用域可配置：项目可声明自己的产物根（前缀）与产物文件（后缀通配）。
- 默认行为与现行逐字节兼容（未配置的项目零行为变化）。
- 消除「产物 → WIP 重叠 → 闸门收纳 → pop 冲突 → 误报 major 告警」链路。
- 判定器故障（配置非法/解析异常）一律**回退默认**，绝不放宽判定。

**Non-Goals**

- 不改 `_heal_unmerged_files` / `_drop_superseded_stash_entry` 的自愈与 drop 语义。
- 不引入「按构建命令自动推断产物目录」的启发式（弱规则在存在性校验类场景会误伤
  真实源码文件）。
- 不自动清理历史 `stash_pop_conflict` 告警与主树存量产物脏改动。
- 不改 `mergeback_wip_overlap_policy`（auto/block）语义与其默认值。

## Decisions

### D1：判定器独立成模块，实例持有前缀集合

新增 `core/worktree_manager/artifact_paths.py`，导出：

```python
DEFAULT_ARTIFACT_PREFIXES = ("core/dashboard/static",)   # 框架既有有效集合

def normalize_artifact_patterns(raw) -> list: ...
    """把配置值规范化为 (kind, pattern) 列表；非法项丢弃并记 WARNING。"""

class ArtifactPathMatcher:
    """产物路径判定器（每实例一份，线程内只读）。"""
    def __init__(self, patterns=None, defaults=DEFAULT_ARTIFACT_PREFIXES): ...
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
| `mergeback._detect_wip_overlap` | 重叠集合**额外**排除产物：`overlap = [p for p in overlap if not self._artifacts.is_artifact(p)]` |

**为什么 WIP 重叠闸门也要排除产物（本 SPEC 的核心动机）**：闸门的作用是「主树未
提交改动与分支改动重叠时先收纳再合并」。产物的未提交改动**不需要保护**——产物是
`src` 的投影，会被重新构建覆盖；把它纳入重叠集合只会制造必然的 pop 冲突与误报告警。
排除后本仓库的两次实际事故（4 文件版 / 2 文件版）都不会再触发闸门。

**`_detect_wip_overlap` 仍保留 `spec/changes/**` 排除**（语义不同，勿合并）：
`spec/changes/**` 是「框架运行必需、有独立提交通道」，产物是「可再生的投影」。

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
   `_detect_wip_overlap` 返回**不含**该路径（改造前含）。
3. **预演闸分类**：冲突全为配置产物时 `rehearsed` 为 None（放行真合并）；
   含语义路径时返回 `MergeConflictInfo(rehearsed=True)`。
4. **故障回退**：`build_artifact_paths="not a list"` / `[123, None]` →
   构造不抛异常、行为等价默认。
5. **兼容性**：不传 `build_artifact_paths` 时 `_is_build_artifact_path` 的行为与
   现行逐字节一致（既有 `test_worktree_stray_and_identical` 断言不回退）。

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
- **并发**：判定器构造后只读，无锁需求；`WorktreeManager` 单实例注入。
