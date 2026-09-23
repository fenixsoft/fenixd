## Why

Fenix 是通用开发框架，但构建产物路径的判定默认值被写死在代码里
（`core/worktree_manager/artifact_paths.py` 的 `DEFAULT_ARTIFACT_PREFIXES =
("core/dashboard/static",)`，以及 `_matches_default()` 里那条「static 根下任一层级
含 dist 目录」的规则）。这条默认值只描述 fenixd 自己一个仓库的产物形态，对任何
其它项目都是错的——它既漏掉被管项目真实的产物（根级 `dist/`、`release-*.zip`、
`build/` 等），又把一个与项目无关的路径当成产物"豁免区"。而且它骗过了配置回显：
`worktree.build_artifact_paths` 明明是空的，判定却"照常工作"（对 fenixd 恰好凑巧
对），于是这个键长期没人配、缺口被掩盖。

通用性要求：产物路径是项目特有的信息，MUST 由配置声明，MUST NOT 靠一个只为框架
自身仓库写死的兜底值。缺省时也不应有"猜"的行为——要么由 LLM 探测自动填写（如同
`fenix-setup` 已自动生成项目简介、`agents/administrator.md` 已自动起草
`.fenix/verify.yaml`），要么由人经 Dashboard 设置；确实没有产物的项目则用一个显式
标志声明，而不是靠"判定恒假"这一隐性默认来表达。

## What Changes

- **BREAKING（语义）**：删除代码里的产物路径默认判定
  （`DEFAULT_ARTIFACT_PREFIXES`、`_matches_default`、`_is_build_artifact_path` 的
  委托）。判定完全由配置驱动，未配置时判定恒为「非产物」（不再变宽到某个内置路径）。
- 新增配置键 `worktree.has_build_artifacts`（布尔，三态）表达项目是否有产物：
  - 未设置 → 未裁决（需要起草/人工填写）；
  - `false` → 项目确定无产物，判定器恒返回"非产物"，不再触发起草；
  - `true` → 按 `worktree.build_artifact_paths` 判定（该键为空时仍需起草）。
- **setup 自动填写**：`fenix-setup` 新增一步，用 LLM 探测项目构建配置（`package.json`
  scripts、`pyproject.toml`、目录结构）判断产物路径，写入
  `worktree.build_artifact_paths` 与 `worktree.has_build_artifacts`。失败不阻塞后续步骤，
  留给运行期兜底。
- **运行期兜底（信号式）**：新增信号 `build_artifact_paths_missing`。生产点在 merge-back
  的 WIP 重叠闸门（`_wip_overlap_gate`）——只在"真正需要区分产物与语义内容"的咽喉处
  触发，不在 daemon 每次启动空转。落地链路复用既有 `verify_contract_missing` 模式：
  `STORED_SIGNAL_TYPES` 登记 → `admin_monitor` 摄取唤起 Administrator →
  `_SIGNAL_RECOMMENDATION` 处置指引 → `agents/administrator.md` 新增起草手册。
  已裁决（`false` 或路径非空）时不写信号。
- **Dashboard 界面**：`核心设置`「验证」页签的「构建产物路径」卡片新增
  `has_build_artifacts` 开关（"项目存在构建产物"）；关闭时路径列表置灰/隐藏并显示
  "已声明无产物"；未裁决时显示待起草提示。
- **存量回填**：对已注册项目（含 fenixd 自身）做一次性回填——探测并写入上述两键，
  避免切换默认语义后立即误伤 merge-back。
- 摘要/回显与来源标注：`config_admin.py` 登记新键（`_SOURCE_KEYS`、缺省字典、
  `_managed_key_sources`），`.fenix/config.template.yaml` 补注释行。

## Capabilities

### New Capabilities

- `artifact-path-declaration`: 构建产物路径的判定语义与配置契约——三态
  `has_build_artifacts` × `build_artifact_paths` 的判定表、无代码默认值、未裁决语义。
- `artifact-path-autofill`: 产物路径的自动起草通路——setup 时的 LLM 探测填写，以及
  运行期 `build_artifact_paths_missing` 信号的产生、摄取、Administrator 起草落地。
- `artifact-path-dashboard-ui`: 验证页签产物卡片上的 `has_build_artifacts` 开关与三态
  呈现（已声明有产物 / 已声明无产物 / 未裁决）。

### Modified Capabilities

- `wip-artifact-scope`: 其「产物前缀判定的默认作用域」Requirement 与「未配置时回退
  内置默认集合」的语义被本 SPEC 反转——默认集合删除，未配置不再是"回退默认"而是
  "未裁决（恒非产物 + 触发起草）"。需改其 Requirement 与 Scenario。

## Impact

- **判定器**：`core/worktree_manager/artifact_paths.py`（删默认集合/默认匹配，
  `ArtifactPathMatcher` 增 `has_build_artifacts` 入参）、
  `core/worktree_manager/__init__.py`（`_is_build_artifact_path` 与
  `DASHBOARD_STATIC_ROOT` 的去留）、`core/worktree_manager/lifecycle.py`（构造期注入
  新键）。
- **消费点**：`mergeback.py`（预演闸 / 冲突分类 / WIP 重叠闸门）、
  `dist_conflicts.py`（产物冲突对齐 / 重建触发）。`dist_conflicts.py` 里
  `DASHBOARD_STATIC_ROOT` 另用于限定「重建作用域」，属框架自身 dashboard 的重建逻辑，
  本 SPEC 只处理**产物判定**口径，不改重建触发面（Non-Goal）。
- **配置**：`fenixd.py`（读两个键注入 WorktreeManager）、
  `core/dashboard/data/config_admin.py`（登记新键 + 校验 + 回显）、
  `.fenix/config.template.yaml`（注释行）。
- **技能/提示词**：`skills/fenix-setup/SKILL.md`（新增探测步骤）、
  `agents/administrator.md`（新增产物路径起草手册）、`core/admin_monitor.py`
  （信号严重度 / 建议 / `STORED_SIGNAL_TYPES`）。
- **前端**：`core/dashboard/static/src/pages/settings/components/VerifyPanel.tsx` +
  `services/dashboard.ts` 类型。
- **信号系统**：`core/pm_engine/verification/*` 或 merge-back 侧的生产点、
  `core/admin_store.py`（若需新 signal_type 枚举）。
- **测试**：`tests/test_worktree_wip_artifact_scope.py` 多处断言依赖默认语义
  （如 `:133-135`、`:340`、`:519`，另有判定矩阵内四处无参 `ArtifactPathMatcher()`
  构造 `:51`/`:57`/`:63`/`:91`）需改写（含其 `:26`/`:30` 对被删符号的 import、
  `:487-505` 的「非法配置回退默认」断言）；另有多处**未在本行列出**的测试夹具依赖
  「未配置时 `core/dashboard/static/dist` 判真」——`tests/test_merge_tree_rehearsal.py:91`
  与 `tests/test_mergeback_repair_lane.py:92` 的 `make_wm()` 均未传
  `build_artifact_paths`，其产物自愈用例会在语义反转后失败，须显式声明产物配置；
  **最大一处遗漏是 `tests/test_worktree_merge_guard.py`**：`:62` 的 `make_wm(root, **kwargs)`
  已支持关键字透传，但 `:252 TestBuildArtifactConflictSelfHeal` 与
  `:399 TestDistConflictRootCure` 两族（共 9 处 `make_wm(root)`）同样依赖默认判定，
  须显式声明（逐条盘点见 tasks 2.5）。
  **反向修正**：`tests/test_facade_delegation_contract.py` 实测**不含任何
  worktree/artifact 条目**（其 `:71` 是 `_write_verify_contract_missing`，属
  VerificationPipeline 组），原「需删 `_is_build_artifact_path` 条目」的说法不成立。
  取消派发前须按 tasks 2.5 逐条盘点。新增 `tests/test_artifact_paths_declaration.py`
  （三态判定表）与 `tests/test_artifact_paths_signal.py`（信号链路）
