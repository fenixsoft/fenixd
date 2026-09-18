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
  kind: modify
- path: .fenix/todo.md
  kind: modify
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
- [ ] 2.4 全量检索确认代码库中不再有 `DEFAULT_ARTIFACT_PREFIXES` / `_matches_default` / `_DEFAULT_STATIC_ROOT` / `_is_build_artifact_path` 的任何定义或引用（含门面 re-export 形态）；测试侧 `from core.worktree_manager import _is_build_artifact_path`（`tests/test_worktree_wip_artifact_scope.py:26`）与 `DEFAULT_ARTIFACT_PREFIXES`（同文件 `:30`）MUST 在同一变更内删除，否则测试收集期即 ImportError
- [ ] 2.5 **测试侧默认语义依赖盘点与改写**（proposal 的测试影响面只列了 `tests/test_worktree_wip_artifact_scope.py`，实测另有多处依赖「未配置时 static/dist 判真」，未改则语义反转后即回归失败）：
  - **夹具约定（先做，其余条目依赖它）**：语义反转后**任何**断言「`core/dashboard/static/**/dist` 判真」的用例都必须显式声明产物配置。既有夹具 `WorktreeManager(base, root, logger, **kwargs)`（`tests/test_worktree_merge_guard.py:62-65`）已支持关键字透传，故统一改写为 `make_wm(root, build_artifact_paths=["core/dashboard/static/"], has_build_artifacts=True)`；未声明该配置的 `make_wm()` 判定恒假（未裁决），这是本 SPEC 的预期语义、不是回归。
  - `tests/test_worktree_merge_guard.py`（`:62` `make_wm(root, **kwargs)` 已支持透传）：`:252 TestBuildArtifactConflictSelfHeal`（`:287`、`:321`、`:385`）与 `:399 TestDistConflictRootCure`（`:455`、`:495`、`:526`、`:540`、`:560`、`:583`，含 `DIST = "core/dashboard/static/dist"` 与 `SRC_PAGE = ".../static/src/pages/list.tsx"`）两族用例均依赖默认判定（前者断言产物冲突自愈、后者断言混合冲突不连坐 / stray 不复活 / 合并后从 src 重建）→ MUST 显式声明。注意 `:591 TestDistBuildContractDriven`（`:599-644`）与 `:648 TestSupersededStashDrop`、`:812 TestWipOverlapPrecheck`、`:909 TestWipOverlapGate` 走 `core/` 与 `shared.py` 路径，不受影响，逐个核对即可。
  - `tests/test_merge_tree_rehearsal.py:91` 的 `make_wm()`（签名 `(root: Path)`，须扩为 `**kwargs`）**未传** `build_artifact_paths`，其 `_branch_with_artifact_conflict`（同文件 `:135-150`）与 `test_artifact_self_heal_*` 依赖默认判定 → MUST 显式传同上两键
  - `tests/test_mergeback_repair_lane.py:92` 的 `make_wm()` 同形（签名同样为 `(root: Path)`，夹具 `:274-290`）→ 同上改写
  - `tests/test_worktree_wip_artifact_scope.py`：除 proposal 列出的 `:26`/`:30`/`:133-135`/`:340`/`:519` 外，判定矩阵内 `:51`、`:57`、`:63`、`:91` 四处 `ArtifactPathMatcher()` 无参构造（断言默认前缀命中 / 根级 dist 为假 / dist 为末段为假 / 配置前缀不丢失默认集合）与 `:489-505` 的「非法配置回退默认」断言同样依赖默认语义 → 一并改写（判定矩阵改为「配置驱动」口径；无参 matcher 判定恒假）
  - **`tests/test_facade_delegation_contract.py` 不受影响**（实测该文件**不含任何 worktree/artifact 条目**；`_write_verify_contract_missing:71` 属 VerificationPipeline 组，与本 SPEC 无关）——proposal.md「Impact」中「`:71` 需删 `_is_build_artifact_path` 条目」为误记，MUST 同步改正（见 proposal Impact 条目）
  - 检索 `tests/` 内其余 `core/dashboard/static` 断言（如 `tests/test_characterization_giant_classes.py:288-345` 的 `_rebuild_dist_after_merge` 用例——该族走 `patch("core.worktree_manager.subprocess.run")`，`diff` 调用被 mock 后 `src_touched` 的两项判定都拿不到真实路径 → 实测不受影响），逐个确认是否依赖默认判定，依赖者一并改写
- [ ] 2.6 核对 `core/worktree_manager/__init__.py` 门面：`_is_build_artifact_path` 删除后无任何 import 残留（`refactor-giant-classes` 的门面 re-export 验收曾将其列为公开名；实测唯一调用方是测试，见 2.4/2.5）

## 3. 运行期起草信号

- [ ] 3.1 在 `mergeback.py` 的 `_wip_overlap_gate` 内，判定「未裁决」时写 `build_artifact_paths_missing` 信号（AdminStore.append，kind=SIGNAL，severity=major，evidence 含「项目名=<name>」）；已裁决时不写。
  - **项目名来源与注入约定（MUST，否则实现期无据可依）**：`WorktreeManager` 当前**不持有项目名**（`lifecycle.py:33-45` 构造参数只有 base_dir/project_root/logger/...），而 `admin_monitor._detect_family_explosion`（`core/admin_monitor.py:807-815`）只在信号**无 `spec` 字段**时才会回落解析 evidence 的「项目名=」。故本 SPEC 明确：**信号 MUST 带 `spec` 字段**，取 `self._spec_from_branch(branch)`（`core/worktree_manager/queries.py:43`，既有 helper，merge-back 链路已在用），「项目名=」作为**冗余证据**写入以便人工/工具定位；不要求为 `WorktreeManager` 新增 project_name 构造参数。`_spec_from_branch` 返回空（非常规分支名）时 MUST 仍写信号并退化为仅靠 evidence 的「项目名=」形态（摄取侧已支持该回退，见 3.4）。
  - **触发点位置（顺序敏感）**：判定 MUST 置于 `_wip_overlap_gate` 的 `if not overlap: return None, []` 早退**之前**（`mergeback.py:155-157`）——否则「主树干净、无 WIP 重叠」这一最常见形态（`core/worktree_manager/mergeback.py` 内早退）永不触发起草，缺口被静默掩盖，恰是本 SPEC 要消灭的「默认值掩盖配置缺口」的复刻。
- [ ] 3.2 实现在途去重：同项目同 signal_type 的未消费信号已存在时跳过重复写入（照搬 `settings_routes._api_verify_yaml_autodraft_post` 的 inflight 判定范式：`kind == SIGNAL and not r.get("handled")`，`core/dashboard/routes/settings_routes.py:366-375`）
- [ ] 3.3 `core/admin_monitor.py` 登记（**以文件实际常量名为准**，实现期按此落位）：严重度表 `SIGNAL_SEVERITY`（`:192`）增 `"build_artifact_paths_missing": "major"`；处置建议表 `SIGNAL_RECOMMENDATION`（`:240`）增处置指引；`STORED_SIGNAL_TYPES`（`:296`）增该类型
- [ ] 3.4 摄取侧项目名解析分支（方法名 `_detect_family_explosion`，`core/admin_monitor.py:784`；proposal/design 中的 `_ingest_stored_signals` 为口头简称）：把该信号并入 `:809` 的 `stype in ("verify_contract_missing", "verify_contract_redraft")` 元组，使「无 spec 时从 evidence 的『项目名=』解析」分支同样覆盖本信号
- [ ] 3.5 信号写入异常 MUST 记 warning 不抛穿（复用 `_write_verify_contract_missing` 的失败处理契约，`core/pm_engine/verification/scenario_gate.py:487-517`），确保信号通道故障不影响 merge-back 判定
- [ ] 3.6 新增信号类型 MUST NOT 需要改动 `core/admin_store.py`：该模块 `_normalize_entry` 对 `signal_type` 无枚举白名单（`core/admin_store.py:211`），登记点只有 `admin_monitor` 三张表——实现期勿额外造枚举

## 4. Administrator 起草手册

- [ ] 4.1 `agents/administrator.md` 新增「构建产物路径起草手册」小节：输入源（package.json scripts / pyproject.toml / 目录结构 / project.type）、起草流程（探测 → 写配置 → 校验 → 提交 → 留痕）、确无产物时写 `has_build_artifacts=false` 结案
- [ ] 4.2 在「高级权限」清单增补一条：修正/生成 `.fenix/config.yaml` 的产物路径配置（`build_artifact_paths` + `has_build_artifacts`），边界规则与既有 verify.yaml 起草同构（有效配置一律不碰）
- [ ] 4.3 新增探测脚本 `bin/fenix_detect_artifacts.py`：读项目清单与目录结构输出候选产物路径（JSON），供 Administrator 与 setup 复用；MUST 纯本地探测（无网络）、失败返回空候选不抛

## 5. setup 自动填写

- [ ] 5.1 `skills/fenix-setup/SKILL.md` 新增探测步骤（置于「生成项目简介」之后）：调用 `bin/fenix_detect_artifacts.py` 或等价 LLM 探测，写入 `worktree.build_artifact_paths` 与 `worktree.has_build_artifacts`
- [ ] 5.2 该步骤实现幂等：`worktree.has_build_artifacts` 已显式存在时跳过（MUST NOT 覆盖人工设置）；探测失败/信息不足时 MUST NOT 阻塞后续步骤（留空交运行期兜底）
- [ ] 5.3 `.fenix/config.template.yaml` 的 `worktree` 段补 `has_build_artifacts` 注释行（说明三态语义 + 与 `build_artifact_paths` 的关系），并修正既有 `build_artifact_paths` 注释中「回退默认集合仅 core/dashboard/static」的过时措辞（`.fenix/config.template.yaml:199-208` 明写「未配置时等价只含 ["core/dashboard/static"]」「→ 回退默认集合」，语义反转后两处 MUST 改写为三态语义）

## 6. Dashboard 界面与配置登记

- [ ] 6.1 `config_admin.py`：`_SOURCE_KEYS`（`:46-102`）增 `worktree.has_build_artifacts`；两处缺省字典的 `"worktree"` 项（`:321-322`、`:525-526`）增该键；`_managed_key_sources` 增「wm_raw 含该键 → project」；`_deep_merge_managed`（`:664`）增该键合并（布尔）；**校验落点**：`write_config` 内联校验段（`:1021-1032` 的 `build_artifact_paths` 分支旁）增布尔校验（非布尔 400 拒绝）——`config_admin.py` **无** `_apply_config_patch` / `_validate_config_patch` 这两个函数名，实现期勿按不存在符号检索
- [ ] 6.2 `core/dashboard/static/src/services/dashboard.ts` 的 `ConfigData.worktree` 类型增 `has_build_artifacts?: boolean`
- [ ] 6.3 `VerifyPanel.tsx` 产物卡片新增 `has_build_artifacts` 三态控件（文案「项目存在构建产物」）：未裁决（未配置态 + 「尚未配置」提示 + 列表可编辑）、`true`（开 + 列表可编辑）、`false`（关 + 列表置灰/隐藏 + 「已声明本项目无构建产物」）。**同时**修正卡片顶部说明文案（`VerifyPanel.tsx:192-195` 现写「留空时回退框架默认仅在 core/dashboard/static 内判定」——语义反转后此句 MUST 改写为三态语义，否则界面自述与实现相悖）。
  - **控件形态约定（MUST）**：antd **无** `indeterminate` 语义（`core/dashboard/static/node_modules/antd/es/switch/index.d.ts` 的 `SwitchProps` 只有 `checked?: boolean`）。「未定态」MUST 用既有 `Radio.Group`（`VerifyPanel.tsx:93`）承载三态（未配置 / 有产物 / 无产物），或 `Select` 三选一；若坚持 `Switch`，则未裁决只能以「关 + 提示文案」呈现，MUST NOT 声称开关本身处于 indeterminate（不可实现）。
  - 同理「开关关 → 列表置灰」：`Form.List` 不支持 `disabled` 透传，需对每个 `Input` 传 `disabled`（`VerifyPanel.tsx:209`），或直接不渲染列表（隐藏）。
  - **提示文案 MUST NOT 承诺本页存在「AI 起草」入口**：既有自动起草仅覆盖 verify.yaml（`ProjectProfilePanel.tsx` 的「AI 起草验证契约」→ `POST /api/verify-yaml-autodraft`），本 SPEC **不新增**产物路径的起草端点（起草由运行期信号 + Administrator 承担）。未裁决态文案 MUST 改为「尚未配置，请手动填写或等待系统自动起草」一类表述，不得指向不存在的按钮。
- [ ] 6.4 `VerifyPanel.tsx` 的 `handleSave` 把 `has_build_artifacts` 并入 `payload.worktree`（仅项目级作用域提交）；用户级作用域沿用只读展示与切换提示
- [ ] 6.5 `config_admin.py` 的两条回显路径 MUST 回显新键：`worktree_config_view`（`core/worktree_manager/artifact_paths.py:158-171`）现在**只返回 `build_artifact_paths`**，而 `read_config` / `read_effective_config` 的 `result["worktree"]` 正是由它产出（`config_admin.py:453-457`、`:648-651`）——不扩展则 `has_build_artifacts` 永远回显缺省、开关在界面上恒为「未裁决」。扩展契约：`worktree_config_view` 返回值含 `has_build_artifacts`（缺省键时 MUST 回显 `None` 而非 `false`——三态语义要求回显能区分「未裁决」与「已声明无产物」；非法值同样回显 `None`）；`_deep_merge_managed` 的 worktree 分支（`config_admin.py:826-836`）增布尔合并
- [ ] 6.6 `_managed_key_sources` 的「wm_raw 含该键 → project」分支（`config_admin.py:225-228`）为 `build_artifact_paths` 与 `has_build_artifacts` **各判一次**（存在性判定，不能用 `or`/`in` 合并写成一处）
- [ ] 6.7 `_SYNC_PAGE_KEYS`（`config_admin.py:1429-1465`）MUST 保持不含 `worktree.*`：`has_build_artifacts` 与 `build_artifact_paths` 同为项目级键，「同步用户级设置」按钮 MUST NOT 把用户级值覆盖进项目级（沿用 `:1428-1429` 既有理由的措辞补上 `has_build_artifacts`），并在 `core/dashboard/static/src/services/dashboard.ts` 的 `ConfigData.worktree`（`:1138`）类型补该键

## 7. 存量回填能力

- [ ] 7.1 提供一次性回填入口（`bin/fenix_detect_artifacts.py --write <project_root>` 或等价 API）：探测并写入目标项目主树的 `worktree.has_build_artifacts` + `build_artifact_paths`，写入经 `validate_build_artifact_paths` 同口径校验
- [ ] 7.2 回填入口 MUST 幂等且不覆盖已显式配置的项目；对探测无产物的项目写 `has_build_artifacts=false`
- [ ] 7.3 **（合并前 MUST 完成的本机前置条件）** 回填入口对 fenixd 自身调用一次并落盘本仓库 `.fenix/config.yaml`（`has_build_artifacts=true` + `build_artifact_paths=["core/dashboard/static/"]`），作为首个实证样本。**执行时机**：`bin/fenix_detect_artifacts.py` 是独立脚本（纯本地探测、直接写主树配置），可在实现分支上先跑，不依赖 daemon 升级——即「先回填、后让新语义生效」。**执行前确认**：主树无未提交的 `core/dashboard/static/src/**` 改动（`build_artifact_paths=["core/dashboard/static/"]` 前缀会把 src 一并判为产物，WIP 重叠对齐 HEAD 会丢弃未提交的 src 改动，见 design D6 补充约定）。注意：`.fenix/config.yaml` 被 `.gitignore:26` 整体排除，回填结果**仅本机生效**、MUST NOT 用 `git add -f` 入库（含密钥）；因此该步是「本机前置条件」而非随版本交付的默认值
- [ ] 7.4 在 `.fenix/todo.md` 登记：对其余已注册项目执行回填的人工运维步骤（跨仓库写主树配置，非本 SPEC 交付范围）
- [ ] 7.5 **发布顺序约束（跨项目生效面）**：把语义反转版本部署到某台机器前，该机上所有已注册项目 MUST 先完成回填（D5）。否则 daemon 一启动，未回填项目即落入「未裁决」窗口——其产物被判为语义内容、`core/dashboard/static` 类路径失去豁免（回归面见 `design.md` Risks 首条）。**本仓库自身亦受此约束**：本 SPEC 的实现分支合并前，7.3 必须先落盘（daemon 一旦以新语义重启，未回填的 fenixd 自身 `dist_conflicts` 自愈链即整体失效）。顺序：本仓库（7.3）→ 同机其它已注册项目（7.4）

## 8. 测试与回归

- [ ] 8.1 改写 `tests/test_worktree_wip_artifact_scope.py` 中依赖内置默认语义的断言（`:133-135`、`:340`、`:519` 等）：原「包级判定与配置无关」改为「未配置时判定恒假」
- [ ] 8.2 新增 `tests/test_artifact_paths_declaration.py`：三态判定表逐格用例（未裁决/true 非空/true 空/false/缺省配非空）、非法布尔回退缺省、`is_artifact_config_unresolved` 用例、`normalize` 空集合回退用例
- [ ] 8.3 新增 `tests/test_artifact_paths_signal.py`：未裁决时 `_wip_overlap_gate` 写信号、已裁决（false / 非空路径）不写、在途去重、`admin_monitor` 摄取与项目名解析、`mark_escalated` 防重复唤起
- [ ] 8.4 前端类型检查（`npx tsc --noEmit`）与 `npm run build` 通过；产物卡片三态在项目级/用户级作用域各渲染一次核对
- [ ] 8.5 运行有界全量套件 `python3 bin/run_full_suite.py --timeout 3600`，确认无新增回归（存量失败按 `--baseline` 归类）
