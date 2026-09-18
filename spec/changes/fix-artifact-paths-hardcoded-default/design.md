## Context

产物路径判定器在 `evo-merge-back-wip-artifact-scope` 中从「包级硬编码函数」改为
「实例状态 + 可配置前缀」，但**保留了内置默认集合**：`DEFAULT_ARTIFACT_PREFIXES =
("core/dashboard/static",)` 与 `_matches_default()`（逐字节复刻旧
`_is_build_artifact_path`）。理由是"向后兼容、配置缺省时的安全回退"。

问题是这条默认值描述的是 fenixd 自己一个仓库的产物形态，与框架的通用性直接冲突：

- 对被管项目它漏判真实产物（根级 `dist/`、`release-*.zip`、`build/`），且把
  `core/dashboard/static` 这个与它们无关的路径当成产物豁免区；
- 它掩盖了配置缺口——fenixd 自己 `build_artifact_paths` 明明为空，判定却"照常
  工作"（因为默认值恰好对上），于是没人发现这个键从未被设置；
- 无法表达「这个项目确实没有产物」——只能靠"判定恒假"这一隐性默认去猜。

判定器的消费点（`mergeback.py` 预演闸 / 冲突分类 / WIP 重叠闸门；
`dist_conflicts.py` 产物冲突对齐 / 重建触发）都是 merge-back 链路，即"只在真正
需要把产物与语义内容分开处理"时才用到——这正是运行期兜底触发的咽喉。

## Goals / Non-Goals

**Goals:**

- 删除代码里所有写死的产物路径默认值，判定完全由配置驱动。
- 新增 `worktree.has_build_artifacts` 三态键，能区分「未裁决」「已声明有产物」
  「已声明无产物」。
- setup 时由 LLM 自动探测填写（复用既有「生成项目简介」模式）。
- 运行期未裁决时经信号呼叫 Administrator 起草（复用 `verify_contract_missing`
  全链路模式），且只在 merge-back 需要分类时触发，不空转。
- Dashboard 验证页签提供可读可写的三态开关。
- 存量项目（含 fenixd 自身）一次性回填，避免语义切换后立即误伤。

**Non-Goals:**

- 不改 `dist_conflicts.py` 中 `DASHBOARD_STATIC_ROOT` 用于「限定重建作用域」的
  逻辑（那是框架自身 dashboard 的重建触发面，不是产物判定口径）。
- 不改产物判定的**匹配算法**（前缀/通配语义、`*` 不跨 `/` 的约束照旧）。
- 不引入项目级/用户级的新的路径默认值来源——没有任何默认值。
- 不做自动 git 提交之外的新机制；起草落地仍走既有 admin 处置链。

## Decisions

### D1：判定器入参从「配置列表」扩为「配置列表 + has_build_artifacts」

`ArtifactPathMatcher.__init__(patterns, defaults, has_build_artifacts=...)`：
删除 `defaults` 参数与 `_defaults` 状态；`has_build_artifacts` 为 `False` 时
`is_artifact()` 直接短路返回假。`normalize_artifact_patterns` 的 fail-safe 语义
从"回退默认集合"改为"回退空集合"（空集合 = 判定恒假，即未裁决的保守侧）。

替代方案：把 `has_build_artifacts` 也塞进 `build_artifact_paths`（如用空列表当
哨兵）。否决——空列表无法区分"未裁决"与"已声明无产物"，且旧代码/扁平化容易
把它误写。

### D2：三态判定表以「未裁决」为一等状态

判定器暴露 `is_artifact(path)`，另提供模块级函数
`is_artifact_config_unresolved(has_build_artifacts, patterns) -> bool` 判定是否
未裁决（`patterns` 为 `normalize_artifact_patterns` 的产物——非法项已被丢弃，
故「非法/全非法」与「未配置」在未裁决判定上同归保守侧）：

| `has` | `paths` | 判定 | 未裁决 |
|-------|---------|------|--------|
| 缺省 | 空 | 恒假 | 是 |
| 缺省 | 非空 | 按配置 | 否 |
| `false` | 任意 | 恒假 | 否 |
| `true` | 非空 | 按配置 | 否 |
| `true` | 空 | 恒假 | 是 |

非法布尔值一律按缺省处理（保守侧，MUST NOT 让判定变宽）。

### D3：运行期兜底信号放 `_wip_overlap_gate`（用户已认可）

`mergeback.py:_wip_overlap_gate` 是"需要把产物与语义内容分开处理"的唯一上游咽喉；
在此检测未裁决并写 `build_artifact_paths_missing` 信号。放 `dist_conflicts` 更早
触发但那是分类结果的下游，本 SPEC 明确选 WIP 闸门。信号不改闸门判定，只呼叫起草。

全链路复用 `verify_contract_missing`：
`STORED_SIGNAL_TYPES` 登记 → `admin_monitor` 摄取（无 spec 时从 evidence 的
「项目名=」解析）→ `_SIGNAL_RECOMMENDATIONS` 指引 → `agents/administrator.md`
起草手册。在途去重（同项目同 signal_type 未消费则跳过）照搬。

### D4：setup 自动填写与运行期信号并存

setup 走"尽力填写"，失败/信息不足不阻塞（留待运行期兜底）；已显式配置时跳过
（不覆盖人工值）。两者不冲突：setup 填过 → 已裁决 → 信号不触发。新增键登记进
`.fenix/config.template.yaml` 注释行，供 fenix-init 渲染的新项目有指引。

### D5：存量回填作为一次性运维动作

语义切换后，未裁决项目的产物会被当语义内容 → merge-back 可能冲突/误报。故需对
已注册项目（含 fenixd 自身）跑探测回填。**该回填是人工/运维动作**（写各项目主树的
`.fenix/config.yaml`，跨仓库），不进 tasks.md 门禁——本 SPEC 的 tasks 只交付
"回填能力"（探测脚本或等价 API），实际执行经 `.fenix/todo.md` 登记由人工/后续
信号完成。

### D6：`DASHBOARD_STATIC_ROOT` 保留

`dist_conflicts.py` 用 `DASHBOARD_STATIC_ROOT` 限定"主树 dashboard 产物重建"的
作用域，与产物判定是两回事。保留该常量与其用法；只移除它作为**产物判定默认值**
的角色（`artifact_paths.py` 里的 `_DEFAULT_STATIC_ROOT`）。`__init__.py` 的
`DASHBOARD_STATIC_ROOT` 保留导出，包级 `_is_build_artifact_path` 删除（唯一调用
方是测试，见下）。

**补充约定（评审就地修补，实现期必须遵循）：**

- **fail-safe 方向**：判定器构造/配置解析的任何异常、非法项、非法布尔值，
  一律落到**未裁决**——判定恒假（保守，不让判定变宽），且照常触发起草信号
  （用户可见、可被修正）。MUST NOT 出现「因配置形态非法而静默既不判真也不告警」
  的中间态。
- **`DASHBOARD_STATIC_ROOT` 的残留用途**（收窄后的边界）：删除产物判定默认值后，
  该常量在 `dist_conflicts.py` 中仍有三处「框架自身 dashboard 重建作用域」用途——
  `_run_dist_build` / `_rebuild_dist_after_merge`（`dist_conflicts.py:231/281/295/308/338`）
  与 `_artifact_paths(rev)` 的 `git ls-tree` 查询范围（`:370`）。三者都是「限定查询/重建
  范围」，不是「判真」；而其中的**判定**（`is_artifact` / `strays` 过滤，
  `:124`、`:281`、`:383`）随本 SPEC 变为配置驱动：某项目若不声明
  `build_artifact_paths`，其 `core/dashboard/static/**` 不再被判为产物，
  `_rebuild_dist_after_merge` 的 `src_touched` 会对自己重建出的产物判真——
  这属已接受的方向性回归（产物判定必须由配置声明），fenixd 自身由 D5/7.3 回填消解。
  **本机自举影响面（MUST 知悉）**：本仓库 `/root/fenixd` 的 `.fenix/config.yaml`
  目前**没有 `worktree` 段**（`worktree:` 只在 `.fenix/config.template.yaml`），
  即回填（7.3）执行前本机 daemon 自身即处于「未裁决」。既然「未裁决」的定义是
  判定恒假，则本仓库的 `dist_conflicts` 自愈链（`:72-124` 产物冲突对齐、
  `:281 src_touched`、`:383 stray 过滤）会整体失效，直到 7.3 落盘为止——
  故 **7.3 是本 SPEC 合并前 MUST 完成的本机前置条件，不是可选的收尾步骤**。
- **本仓库未跟踪产物的既有事实**：`.gitignore:30` 的 `dist/` 与 `:22-24` 的
  `core/dashboard/static/dist` 说明帧已使 `core/dashboard/static/dist/**` 不入库，
  `git ls-tree` 本就枚举不到——即「回填里的 `build_artifact_paths=["core/dashboard/static/"]`
  会把 src 一并判为产物」这一副作用，在 dist 不入库的前提下只影响**尚未提交的
  工作区 src 改动**（产物重叠对齐 HEAD 会丢弃它们）。该风险由 D5 回填 + 7.3
  手工确认消解，但实施 7.3 时 MUST 先确认主树无未提交的 `core/dashboard/static/src/**`。
- **D5 回填的生效范围**：`.fenix/config.yaml` 被 `.gitignore:26` 整体排除，
  回填结果只作用于**本机**该项目的 daemon；跨机器/新克隆的项目 MUST 走
  setup 探测（D4）或运行期信号兜底，不得假设仓库携带该配置。因此**部署顺序**
  必须由 tasks 7.5 约束：先回填本机全部已注册项目，再升级 daemon 语义。

## Risks / Trade-offs

- **语义反转的回归面**：任何依赖"未配置时 `core/dashboard/static` 产物判真"的
  代码/测试会失败。缓解：`tests/test_worktree_wip_artifact_scope.py` 多处断言
  （`:133-135`、`:340`、`:519`）需同步改写；全量套件回归验证。
- **未裁决项目在回填完成前的窗口**：切换后到回填完成前，未配置项目的 merge-back
  可能把产物当语义内容。缓解：信号在首次触发即呼叫起草；回填（D5）尽快执行；
  风险窗口有告警可视化（信号 + 运维记录）。
- **信号噪声**：若闸门频繁命中未裁决项目，可能重复写信号。缓解：在途去重
  （D3）+ `mark_escalated` 防重复唤起（既有契约）。
- **setup 探测误判**：LLM 可能填错路径。缓解：填入的是可编辑的配置值，Dashboard
  可随时改；`validate_build_artifact_paths` 在写入侧拒绝非法项；探测结果不阻塞
  setup，最坏情况退化为"未裁决"由运行期兜底。
- **BREAKING 性质**：这是对已发布能力 `wip-artifact-scope` 的语义反转，文档/记忆
  需同步（`spec/archive` 里的旧 spec 保留为准的历史，新 spec 的 MODIFIED 段为准的
  现行）。
