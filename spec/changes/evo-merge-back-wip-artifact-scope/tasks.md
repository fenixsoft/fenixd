# Tasks: evo-merge-back-wip-artifact-scope

## Deliverables

```yaml
- path: core/worktree_manager/artifact_paths.py
  kind: new
- path: core/worktree_manager/__init__.py
  kind: modify
- path: core/worktree_manager/mergeback.py
  kind: modify
- path: core/worktree_manager/dist_conflicts.py
  kind: modify
- path: core/worktree_manager/lifecycle.py
  kind: modify
- path: fenixd.py
  kind: modify
- path: .fenix/config.template.yaml
  kind: modify
- path: core/dashboard/data/config_admin.py
  kind: modify
- path: core/dashboard/static/src/pages/settings/components/VerifyPanel.tsx
  kind: modify
- path: core/dashboard/static/src/services/dashboard.ts
  kind: modify
- path: tests/test_worktree_wip_artifact_scope.py
  kind: new
- path: tests/test_worktree_stray_and_identical.py
  kind: modify
- path: core/dashboard/static/dist/index.html
  kind: reference
```

> 说明：`core/dashboard/static/dist/index.html`（及同目录其余 dist 资产）为前端
> `npm run build` 产物，属 `reference`——构建后由 `dist-conflicts` 既有机制刷新，
> 不进交付物硬校验。本 SPEC 不改产品侧 `.fenix/config.yaml` 的**运行时**值
> （由管理员/人工按需写入），只改框架侧配置模板。

## 1. 判定器模块（D1/D2）

- [ ] 1.1 新建 `core/worktree_manager/artifact_paths.py`：定义包级常量
      `DEFAULT_ARTIFACT_PREFIXES = ("core/dashboard/static",)`，并把既有
      `_is_build_artifact_path` 的语义（前缀 + `dist` 非末段）原样搬入模块内的
      `_matches_default(path) -> bool`，模块 docstring 写明「判定作用域从全局常量
      改为实例状态」的迁移背景与调用点清单（4 条路径）
- [ ] 1.2 同文件实现 `normalize_artifact_patterns(raw) -> list`：把配置值规范化为
      `(kind, pattern)` 列表（`kind ∈ {"prefix", "glob"}`）——非列表/非字符串项、
      不含 `*` 且未以 `/` 结尾的项、绝对路径（`/` 开头）或含 `..` 段的项一律丢弃
      并记 WARNING；任何异常捕获后返回空列表（fail-safe 回退默认）
- [ ] 1.3 同文件实现 `ArtifactPathMatcher`：`__init__(patterns=None, defaults=None)`
      持 `self._prefixes` / `self._globs` / `self._defaults`；方法
      `is_artifact(path) -> bool`（前缀命中 或 `fnmatchcase` 命中完整相对路径 或
      默认规则命中）、`paths_in(paths) -> list`、`non_artifacts_in(paths) -> list`。
      **通配不跨目录**：含 `/` 的路径 MUST NOT 被不含 `/` 的 glob 命中（用
      `fnmatch.fnmatchcase` 后额外校验 `pattern` 与 `path` 的 `/` 段数关系）
- [ ] 1.4 `core/worktree_manager/__init__.py`：`_is_build_artifact_path` 改为
      「默认判定」别名——委托 `ArtifactPathMatcher().is_artifact(path)`，签名与
      返回值语义逐字节不变；`DASHBOARD_STATIC_ROOT` 常量保留（既有引用
      `dist_conflicts.py` / `tests/test_characterization_giant_classes.py` 零改动）

## 2. 四路径接线（D3/D4）

- [ ] 2.1 `lifecycle.py`：`G1LifecycleMixin.__init__` 新增构造参数
      `build_artifact_paths=None`，构造体内 `self._artifacts = ArtifactPathMatcher(
      normalize_artifact_patterns(build_artifact_paths))`；缺省/全非法时等价
      `ArtifactPathMatcher()`（仅默认集合）。**MUST NOT 用 `getattr(self, ...)` 兜底**
      ——判定器是构造期必需属性，缺失应暴露而非静默降级
- [ ] 2.2 `fenixd.py`：在既有 `_wip_policy` 注入段旁读取
      `self.config.get("worktree.build_artifact_paths", None)` 并随构造传入（含注释
      说明「判定变宽会静默丢弃语义改动，故默认只含框架现行有效路径」）
- [ ] 2.3 `mergeback.py`：`_rehearse_merge_from_branch` 的 `non_artifact` 改
      `self._artifacts.non_artifacts_in(conflict_paths)`；merge 冲突分类两处
      （`self_heal_applicable` / `has_semantic_conflict`）改 `self._artifacts`
- [ ] 2.4 `mergeback.py`：`_detect_wip_overlap` 在既有 `spec/changes/**` 排除
      **之后**追加产物排除 `[p for p in overlap if not self._artifacts.is_artifact(p)]`，
      并在 docstring 写明「两类排除语义不同、MUST NOT 合并」
- [ ] 2.5 `dist_conflicts.py`：`_resolve_build_artifact_conflicts` 的
      `artifact_paths` 过滤与 stray 判定、`_artifact_paths(ref)` 集合枚举、以及
      `_rebuild_dist_after_merge` 的 `src_touched` 判定全部改走 `self._artifacts`

## 3. 配置面与前端（D6）

- [ ] 3.1 `.fenix/config.template.yaml`：`worktree` 段补
      `build_artifact_paths` 键与注释（说明两类形态、非法项丢弃规则、默认值语义，
      并给出「产物在仓库根」项目的示例形态）
- [ ] 3.2 `core/dashboard/data/config_admin.py`：覆盖全部落点——①缺省字典（用户级
      与项目级两处）②`worktree` 段合并应用分支（列表形态原样透传）③`write_config`
      前置校验（非列表/含非法项时报错并给出规范化提示）④`_SOURCE_KEYS` 来源标注。
      `_SYNC_PAGE_KEYS` **不含**该键（只读键，不参与「同步用户级设置」写入），
      并在注释写明该决定
- [ ] 3.3 `core/dashboard/static/src/pages/settings/components/VerifyPanel.tsx`：
      验证契约页增加「构建产物路径」只读展示（当前生效值 + 语义说明 + 推荐形态）；
      `core/dashboard/static/src/services/dashboard.ts` 的 `ConfigData` 类型补
      `worktree.build_artifact_paths?: string[]`
- [ ] 3.4 前端构建：`npm run build`（`core/dashboard/static`），确认产物刷新

## 4. 测试（D5）

- [ ] 4.1 新建 `tests/test_worktree_wip_artifact_scope.py`：判定矩阵——默认前缀命中
      / 根级 `dist/x.js` 默认为假 / 配置 `dist/` 后为真 / 配置
      `fenix-newtab-*.zip` 命中发布包 / `*.zip` MUST NOT 命中 `src/vendor/pkg.zip` /
      未以 `/` 结尾项被丢弃 / 绝对路径与 `..` 项被丢弃 / 配置形态非法（字符串、
      `[123, None]`）不抛异常且回退默认 / 空列表等价默认
- [ ] 4.2 同文件：WIP 重叠闸门——主树脏 `dist/index.html` + 分支同改且已配置产物 →
      `_detect_wip_overlap` 不含该路径、无其他重叠时返回空列表；语义文件
      （`src/...`）重叠仍计入；`spec/changes/**` 排除不受产物配置影响
- [ ] 4.3 同文件：预演闸分类——冲突全为配置产物时返回 `None`（放行）；含语义路径时
      返回 `rehearsed=True` 且 `conflict_paths` 不含产物路径；包级
      `_is_build_artifact_path("dist/index.html")` 仍为 False（默认语义与配置无关）
- [ ] 4.4 `tests/test_worktree_stray_and_identical.py`：核对既有断言在「未配置产物
      路径」下零回退（如需要，仅补标注不改语义）；核对
      `tests/test_characterization_giant_classes.py` 对
      `_is_build_artifact_path` / `DASHBOARD_STATIC_ROOT` 的引用仍通过

## 5. 回归与收尾

- [ ] 5.1 运行 `python3 bin/run_full_suite.py --timeout 3600`，修复因判定器迁移引入
      的回归（重点 `test_worktree_*`、`test_mergeback_repair_lane`、
      `test_reclaim_stale_autostash`、`test_characterization_giant_classes`）
- [ ] 5.2 在本项目（`/root/fenix-desktop`）确认收敛效果：核对主树脏产物不再进入
      `_detect_wip_overlap` 结果（可用一次只读调用验证），并在 `.fenix/config.yaml`
      **不作为本 SPEC 交付物**（运行时文件）——在 notes 中给出建议值
      `["dist/", "fenix-newtab-*.zip"]` 供人工写入
- [ ] 5.3 写 `.fenix-run-result.json`（含 `completed_tasks` 与各场景证据），并持久化
      场景集与结果到 `.fenix/verify-progress/evo-merge-back-wip-artifact-scope/`
- [ ] 5.4 逐项勾选本 tasks.md 全部已完成任务
