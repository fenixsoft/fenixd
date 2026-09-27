<!-- knowledge: capability=architect-agent rev=1 sources=spec/archive/add-architect-agent-1789628607 -->

# 架构师 agent（DFX 评估与重构建议）

以代码为数据源的常设角色：每日随自省周期对窗口内变动代码做 DFX 五维评估，产出结构化重构建议条目，不自动立项。

## 现行规则

- 角色注册完整：`architect` 在全部注册表同步登记——配置白名单（`KNOWN_AGENT_TYPES`）、模型分配映射（`agents.models.architect`）、prompt 文件映射（`agents/architect.md`）、run_id 前缀映射、前端模型分配角色列表；任一注册表遗漏即不合规。prompt 从 `agents/architect.md` 加载，缺失时 fail-fast（不静默降级）；run_id 前缀可解析回 `architect`；前后端角色白名单集合完全一致。
- 触发：复用自省调度入口（`SelfReviewScheduler.check_and_run`）作为唯一触发门，在自省路径（含其零活动跳过）之后执行；`admin.architect.enabled` 为 false 时全链路零动作（无 run、无建议写入、无状态更新）。「当日已执行」判定落在独立状态键 `architect_last_run_date`，不写自省的 `last_run_date` 与增量窗口锚点 `last_run_at`；同日不重复触发；架构师与自省互不抑制（任一方先执行都不阻断另一方当日触发）。
- 审查范围：数据源为自省增量窗口 `[last_run_at, now]`（`admin.architect.window_max_hours > 0` 时下界取 `max(window_start, now − N 小时)`）内发生变更的代码文件清单，不做全仓扫描。采集机制 = 已提交改动（`git log --since --name-only`）∪ 未提交改动（`git status --porcelain` / `git diff --name-only HEAD`）；git 均不可用时回退 mtime 扫描（后缀白名单）并在 prompt 标注降级来源。禁用只返回布尔的变更探测函数或只覆盖部分路径的文件枚举函数作清单来源；清单超上限时截断并标注截断事实与原始条数；窗口内零变更时不产出针对具体文件的建议。
- 产出契约：以结构化条目格式追加至项目 `todo.md`（与自省条目同一文件、同一格式契约），每条含 DFX 维度、涉及文件、问题证据、建议动作，清晰度标准为「未参与当日工作的新 agent 可据此直接起草 SPEC」；DFX 五维为可读性、健壮性、性能效率、可测试性、可观测性。追加不覆盖历史分节。不自动创建 SPEC、不注册 STATE 条目、不派发实现。
- 模型分配面板：Dashboard「模型分配」页为 `architect` 提供与其它角色一致的 provider/模型候选链编辑卡片；保存写入 `agents.models.architect` 并经既有配置热更新生效。
- 自进化页签设置卡片：含启用开关（`admin.architect.enabled`）与审查窗口上限（`admin.architect.window_max_hours`），两者为项目级配置键、与 `admin.self_review` 同作用域；用户级作用域下卡片只读、`collect()` 返回空补丁，不把项目级键写入用户级配置。写入走完整受管键链路（合并分支、前置校验、来源标注、缺省回显四处齐全），保存后热更新生效且重读配置时值仍在（不被白名单合并静默丢弃）。
- 统计与对账隔离：architect run 的 run_id 前缀从自省 run 统计（`collect_runs_stats`）中排除，不改变自省数据聚合口径、不点亮「窗口内零 SPEC 活动则跳过自省」判定。run 失败（异常/超时/非零退出）与自省同款处置：记失败告警、当日不重试、次日 run_at 后自然重试。token 用量归账到独立成本类目，条目标注 `agent_type: "architect"`。
- 文档同步：`docs/help/02-concepts.md` 的 Agent 类型表与 `docs/help/09-config.md` 中 `agents.models` 的角色枚举含 `architect`，且无与新角色数不符的表述。

## 溯源

- 2026-09-17 add-architect-agent-1789628607 — 新增架构师角色全链规则（注册表登记、自省后触发与独立状态键、窗口内变更清单受限审查、DFX 建议产出契约、模型面板与设置卡片、run 统计隔离与文档同步）
