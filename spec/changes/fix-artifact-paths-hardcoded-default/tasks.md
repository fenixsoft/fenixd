## Deliverables

```yaml
- path: core/worktree_manager/artifact_paths.py
  kind: modify
- path: core/worktree_manager/__init__.py
  kind: modify
- path: core/worktree_manager/lifecycle.py
  kind: modify
- path: core/worktree_manager/mergeback.py
  kind: modify
- path: fenixd.py
  kind: modify
- path: core/admin_monitor.py
  kind: modify
- path: agents/administrator.md
  kind: modify
- path: skills/fenix-setup/SKILL.md
  kind: modify
- path: .fenix/config.template.yaml
  kind: reference
- path: core/dashboard/data/config_admin.py
  kind: modify
- path: core/dashboard/static/src/pages/settings/components/VerifyPanel.tsx
  kind: modify
- path: core/dashboard/static/src/services/dashboard.ts
  kind: modify
- path: tests/test_worktree_wip_artifact_scope.py
  kind: modify
- path: tests/test_artifact_paths_declaration.py
  kind: new
- path: tests/test_artifact_paths_signal.py
  kind: new
- path: bin/fenix_detect_artifacts.py
  kind: new
```

## 1. 判定器去默认值

- [ ] 1.1 删除 `artifact_paths.py` 的 `DEFAULT_ARTIFACT_PREFIXES`、`_DEFAULT_STATIC_ROOT`、`_matches_default()`、`ArtifactPathMatcher._match_default()` 与 `defaults` 构造参数；`is_artifact()` 改为「配置前缀 ∪ 配置通配」判定，无任何内置路径
- [ ] 1.2 `normalize_artifact_patterns` 的 fail-safe 从「回退默认集合」改为「回退空集合」；更新其 docstring 与内部注释（非法项仍丢弃 + WARNING）
- [ ] 1.3 `ArtifactPathMatcher.__init__` 新增 `has_build_artifacts: Optional[bool]` 入参；值为 `False` 时 `is_artifact()` 与 `paths_in()` 短路返回空/假（判定恒假）
- [ ] 1.4 新增模块级函数 `is_artifact_config_unresolved(has_build_artifacts, patterns) -> bool`，按三态表判定「未裁决」（缺省键、或 true 配空路径）；非布尔值按缺省处理
- [ ] 1.5 删除 `core/worktree_manager/__init__.py` 的包级 `_is_build_artifact_path()`；保留 `DASHBOARD_STATIC_ROOT` 常量与其在 `dist_conflicts.py` 的重建作用域用法（Non-Goal：不改重建触发面）

## 2. 配置注入生效路径

- [ ] 2.1 `lifecycle.py` 的 `G1LifecycleMixin.__init__` 新增 `has_build_artifacts=None` 入参，构造 matcher 时连同 `normalize_artifact_patterns(build_artifact_paths)` 一并注入
- [ ] 2.2 `fenixd.py` 读取 `worktree.has_build_artifacts`（缺省 None）并传入 `WorktreeManager`，与既有 `worktree.build_artifact_paths` 读取并列
- [ ] 2.3 核对 `mergeback.py` / `dist_conflicts.py` 的 matcher 消费点：确认判定语义切换后调用签名不变（`is_artifact` / `paths_in` / `non_artifacts_in`），无需改调用方
- [ ] 2.4 全量检索确认代码库中不再有 `DEFAULT_ARTIFACT_PREFIXES` / `_matches_default` / `_is_build_artifact_path` 的任何定义或引用

## 3. 运行期起草信号

- [ ] 3.1 在 `mergeback.py` 的 `_wip_overlap_gate` 内，判定「未裁决」时写 `build_artifact_paths_missing` 信号（AdminStore.append，kind=SIGNAL，severity=major，evidence 含「项目名=<name>」）；已裁决时不写
- [ ] 3.2 实现在途去重：同项目同 signal_type 的未消费信号已存在时跳过重复写入（照搬 `settings_routes._api_verify_yaml_autodraft_post` 的 inflight 判定范式）
- [ ] 3.3 `core/admin_monitor.py` 登记：`_SIGNAL_SEVERITY` 增 `build_artifact_paths_missing: major`；`_SIGNAL_RECOMMENDATIONS` 增处置指引；`STORED_SIGNAL_TYPES` 增该类型
- [ ] 3.4 `_ingest_stored_signals` 的项目名解析分支扩展到该信号（无 spec 时从 evidence 的「项目名=」提取，与 `verify_contract_missing` 同分支）
- [ ] 3.5 信号写入异常 MUST 记 warning 不抛穿（复用 `_write_verify_contract_missing` 的失败处理契约），确保信号通道故障不影响 merge-back 判定

## 4. Administrator 起草手册

- [ ] 4.1 `agents/administrator.md` 新增「构建产物路径起草手册」小节：输入源（package.json scripts / pyproject.toml / 目录结构 / project.type）、起草流程（探测 → 写配置 → 校验 → 提交 → 留痕）、确无产物时写 `has_build_artifacts=false` 结案
- [ ] 4.2 在「高级权限」清单增补一条：修正/生成 `.fenix/config.yaml` 的产物路径配置（`build_artifact_paths` + `has_build_artifacts`），边界规则与既有 verify.yaml 起草同构（有效配置一律不碰）
- [ ] 4.3 新增探测脚本 `bin/fenix_detect_artifacts.py`：读项目清单与目录结构输出候选产物路径（JSON），供 Administrator 与 setup 复用；MUST 纯本地探测（无网络）、失败返回空候选不抛

## 5. setup 自动填写

- [ ] 5.1 `skills/fenix-setup/SKILL.md` 新增探测步骤（置于「生成项目简介」之后）：调用 `bin/fenix_detect_artifacts.py` 或等价 LLM 探测，写入 `worktree.build_artifact_paths` 与 `worktree.has_build_artifacts`
- [ ] 5.2 该步骤实现幂等：`worktree.has_build_artifacts` 已显式存在时跳过（MUST NOT 覆盖人工设置）；探测失败/信息不足时 MUST NOT 阻塞后续步骤（留空交运行期兜底）
- [ ] 5.3 `.fenix/config.template.yaml` 的 `worktree` 段补 `has_build_artifacts` 注释行（说明三态语义 + 与 `build_artifact_paths` 的关系），并修正既有 `build_artifact_paths` 注释中「回退默认仅 core/dashboard/static」的过时措辞

## 6. Dashboard 界面与配置登记

- [ ] 6.1 `config_admin.py`：`_SOURCE_KEYS` 增 `worktree.has_build_artifacts`；两处缺省字典的 `"worktree"` 项增该键；`_managed_key_sources` 增「wm_raw 含该键 → project」；`_apply_config_patch` 增该键合并（布尔）；`_validate_config_patch` 增布尔校验（非布尔 400 拒绝）
- [ ] 6.2 `core/dashboard/static/src/services/dashboard.ts` 的 `ConfigData.worktree` 类型增 `has_build_artifacts?: boolean`
- [ ] 6.3 `VerifyPanel.tsx` 产物卡片新增 `has_build_artifacts` 开关（文案「项目存在构建产物」）与三态呈现：未裁决（未定态 + 「尚未配置」提示 + 列表可编辑）、`true`（开关开 + 列表可编辑）、`false`（开关关 + 列表置灰/隐藏 + 「已声明本项目无构建产物」）
- [ ] 6.4 `VerifyPanel.tsx` 的 `handleSave` 把 `has_build_artifacts` 并入 `payload.worktree`（仅项目级作用域提交）；用户级作用域沿用只读展示与切换提示

## 7. 存量回填能力

- [ ] 7.1 提供一次性回填入口（`bin/fenix_detect_artifacts.py --write <project_root>` 或等价 API）：探测并写入目标项目主树的 `worktree.has_build_artifacts` + `build_artifact_paths`，写入经 `validate_build_artifact_paths` 同口径校验
- [ ] 7.2 回填入口 MUST 幂等且不覆盖已显式配置的项目；对探测无产物的项目写 `has_build_artifacts=false`
- [ ] 7.3 回填入口对 fenixd 自身调用一次并落盘本仓库 `.fenix/config.yaml`（`has_build_artifacts=true` + `build_artifact_paths=["core/dashboard/static/"]`），作为首个实证样本
- [ ] 7.4 在 `.fenix/todo.md` 登记：对其余已注册项目执行回填的人工运维步骤（跨仓库写主树配置，非本 SPEC 交付范围）

## 8. 测试与回归

- [ ] 8.1 改写 `tests/test_worktree_wip_artifact_scope.py` 中依赖内置默认语义的断言（`:133-135`、`:340`、`:519` 等）：原「包级判定与配置无关」改为「未配置时判定恒假」
- [ ] 8.2 新增 `tests/test_artifact_paths_declaration.py`：三态判定表逐格用例（未裁决/true 非空/true 空/false/缺省配非空）、非法布尔回退缺省、`is_artifact_config_unresolved` 用例、`normalize` 空集合回退用例
- [ ] 8.3 新增 `tests/test_artifact_paths_signal.py`：未裁决时 `_wip_overlap_gate` 写信号、已裁决（false / 非空路径）不写、在途去重、`admin_monitor` 摄取与项目名解析、`mark_escalated` 防重复唤起
- [ ] 8.4 前端类型检查（`npx tsc --noEmit`）与 `npm run build` 通过；产物卡片三态在项目级/用户级作用域各渲染一次核对
- [ ] 8.5 运行有界全量套件 `python3 bin/run_full_suite.py --timeout 3600`，确认无新增回归（存量失败按 `--baseline` 归类）
