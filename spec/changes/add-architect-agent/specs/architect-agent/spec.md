# architect-agent

## ADDED Requirements

### Requirement: 架构师角色注册完整

框架 MUST 新增一类 agent 角色 `architect`，且在全部角色注册表同步登记：配置白名单（`KNOWN_AGENT_TYPES`）、模型分配映射、prompt 文件映射（`AGENT_PROMPT_FILES`）、run_id 前缀映射（`RUN_ID_AGENT_PREFIXES`）、前端模型分配角色列表。任一注册表遗漏 MUST 视为不合规。

#### Scenario: 配置白名单接受该角色

- **WHEN** 项目配置含 `agents.models.architect`
- **THEN** 配置校验不报「未知 agent 类型」，该键被正常接受

#### Scenario: prompt 文件存在且加载

- **WHEN** 架构师 run 启动
- **THEN** 从 `agents/architect.md` 加载 prompt，缺失时 fail-fast（不得静默降级）

#### Scenario: run 可被归类

- **WHEN** 产生一个架构师 run 产物
- **THEN** 其 run_id 前缀可被解析回 `architect` agent_type

#### Scenario: 前后端角色列表一致

- **WHEN** 对比后端 `KNOWN_AGENT_TYPES` 与前端模型分配角色列表
- **THEN** 两者集合完全一致（含 `architect`）

### Requirement: 架构师随每日自省周期触发（状态与自省互不抑制）

架构师 MUST 复用自省调度入口（`SelfReviewScheduler.check_and_run`）作为唯一触发门，MUST 在自省路径（含其零活动跳过）之后执行；`admin.architect.enabled` 为 false 时全链路零动作。架构师 MUST NOT 使自省被抑制，也 MUST NOT 因自省已执行而自身永不触发：架构师的「当日已执行」判定 MUST 落在独立状态键 `architect_last_run_date`，架构师路径 MUST NOT 写自省的 `last_run_date`，也 MUST NOT 写自省增量窗口锚点 `last_run_at`。

#### Scenario: 定时触发

- **WHEN** 架构师启用、到达 run_at、今日自省路径已走完且 `architect_last_run_date` 非今日
- **THEN** daemon 发起一次架构师 run，并仅在状态文件中写 `architect_last_run_date`（`last_run_date` 与 `last_run_at` 保持不变）

#### Scenario: 架构师不抑制当日自省

- **WHEN** 架构师 run 先完成并写入状态
- **THEN** 当日自省调度判定不受影响，自省仍按既有规则触发

#### Scenario: 自省已执行不阻断架构师

- **WHEN** 当日自省已完成（`last_run_date == today`）而架构师当日未执行
- **THEN** 架构师仍在本轮或后续巡检周期触发一次

#### Scenario: 开关关闭零动作

- **WHEN** 架构师开关为 false
- **THEN** 无架构师 run、无建议写入、无 `architect_last_run_date` 更新

#### Scenario: 同日不重复

- **WHEN** 今日架构师已执行
- **THEN** 同日的后续巡检周期不再次发起

### Requirement: 审查范围限于自省窗口内变动的代码

架构师的数据源 MUST 为自省增量窗口 `[last_run_at, now]`（`admin.architect.window_max_hours > 0` 时下界取 `max(window_start, now - N hours)`）内发生变更的代码文件**清单**；MUST NOT 主动遍历或扫描全仓代码。prompt MUST 显式约束该范围，并在清单被截断或来源降级时显式标注。

框架 MUST 以可产出**路径清单**的机制采集：已提交改动（`git log --since --name-only`）+ 未提交改动（`git status --porcelain` / `git diff --name-only HEAD`）并集；两者均不可用时回退 mtime 扫描（后缀白名单）。MUST NOT 以只返回布尔值的变更探测函数（如 `code_files_changed_since`）或只覆盖 `fenixd.py` + `core/**/*.py` 的文件枚举函数（如 `code_tracked_files`）作为清单来源。

#### Scenario: 仅注入窗口内变更文件

- **WHEN** 自省窗口内仅有 3 个代码文件发生变更
- **THEN** 注入架构师 run 的代码清单恰为这 3 个文件

#### Scenario: 未提交改动被采集

- **WHEN** 窗口内有已提交改动与主树未提交改动各若干
- **THEN** 清单包含两者（仅用 `git log` 会漏掉未提交部分）

#### Scenario: 无变更时零产出

- **WHEN** 自省窗口内没有任何代码文件变更
- **THEN** 架构师 run 不产出针对具体文件的重构建议（可产出「无变更」的空结论）

#### Scenario: 清单超限被截断且可辨识

- **WHEN** 窗口内变更文件数超过配置上限
- **THEN** 注入清单被截断至上限并在 prompt 中标注截断事实与原始条数

#### Scenario: 非 git 环境降级可辨识

- **WHEN** 项目非 git 仓库或 git 命令失败
- **THEN** 回退 mtime 扫描并在 prompt 中标注清单来源为降级路径

#### Scenario: 不做全仓扫描

- **WHEN** 审阅架构师 prompt 与其注入数据
- **THEN** 其中不含全仓文件清单或全目录遍历指令

### Requirement: 产出结构化重构建议至建议条目

架构师的产出 MUST 以既有结构化条目格式追加至项目 `todo.md`（与自省条目同一文件、同一格式契约），每条建议 MUST 含：DFX 维度、涉及文件、问题证据、建议动作，清晰度标准为「未参与当日工作的新 agent 可据此直接起草 SPEC」。架构师 MUST NOT 自动创建 SPEC、注册 STATE 条目或派发实现。

#### Scenario: 条目含必需字段

- **WHEN** 架构师产出某条重构建议
- **THEN** 该条目含 DFX 维度、涉及文件、证据与建议动作

#### Scenario: 不自动立项

- **WHEN** 架构师运行结束
- **THEN** `spec/changes/` 与 STATE.md 无新增条目，无 agent 派发

#### Scenario: 追加不覆盖历史

- **WHEN** `todo.md` 已存在历史分节
- **THEN** 架构师条目追加，历史内容不变

### Requirement: 模型分配面板提供架构师槽位

Dashboard「模型分配」页 MUST 为 `architect` 提供与其它角色一致的 provider/模型候选链编辑界面；保存后经既有配置写入与热更新生效。

#### Scenario: 界面可见可编辑

- **WHEN** 打开「模型分配」页
- **THEN** 存在「Architect（架构师）」卡片，可编辑其 provider/模型候选链并保存

#### Scenario: 保存生效

- **WHEN** 保存架构师的模型分配
- **THEN** `agents.models.architect` 被写入配置，后续架构师 run 使用该候选链

### Requirement: 自进化页签提供架构师设置

「自进化」页签 MUST 提供架构师设置卡片，含启用开关（`admin.architect.enabled`）与审查窗口上限（`admin.architect.window_max_hours`）控件；两者为**项目级**配置键，与 `admin.self_review` 同作用域。卡片在用户级作用域下 MUST 只读、`collect()` 返回空补丁（沿用 `SuggestedImprovementsPanel` 既有 scope 约定），MUST NOT 把项目级键写入用户级配置。

配置写入 MUST 走完整受管键链路：合并分支、前置校验、来源标注、缺省回显四处齐全；保存后经既有配置热更新生效，且**保存后重新读取配置时该值仍在**（不得被白名单合并静默丢弃）。

#### Scenario: 设置卡片存在

- **WHEN** 打开设置页「自进化」页签（项目级作用域）
- **THEN** 存在架构师设置卡片，含启用开关与审查窗口控件

#### Scenario: 设置生效且可回读

- **WHEN** 在卡片中修改审查窗口并保存
- **THEN** 该值写入 `.fenix/config.yaml` 的 `admin.architect.window_max_hours`，重新读取配置仍返回该值，且被后续架构师 run 采用（无需重启 daemon）

#### Scenario: 用户级作用域只读

- **WHEN** 在用户级作用域打开「自进化」页签并触发保存
- **THEN** 架构师卡片不写入任何键，用户级配置文件不新增 `admin.architect` 段

### Requirement: 架构师的 run 产物不污染自省数据源与既有统计

架构师 run 的 run_id 前缀 MUST 从自省自身的 run 统计（`collect_runs_stats`）中排除——该统计现仅排除 `review-`，若架构师 run 被计入，会改写自省的数据聚合口径，并使「窗口内零 SPEC 活动则跳过自省」的判定失真。架构师 run 失败 MUST 与自省同款处置（记告警、当日不重试、次日自然重试），并 MUST 与自省使用独立成本类目以便对账区分。

#### Scenario: 不计入自省 run 统计

- **WHEN** 窗口内既有 SPEC run 又有架构师 run
- **THEN** 自省的数据聚合与零活动判定只反映 SPEC run，架构师 run 计数为 0

#### Scenario: 无 SPEC 活动的日子不被架构师点亮

- **WHEN** 窗口内没有任何 SPEC run、架构师 run 已执行
- **THEN** 自省的零活动跳过判定仍成立（不因架构师 run 存在而误唤起自省）

#### Scenario: 失败记告警且当日不重试

- **WHEN** 架构师 run 异常、超时或返回非零退出码
- **THEN** 记录一条失败告警，当日不再重试，次日 run_at 后自然重试

#### Scenario: 成本独立类目

- **WHEN** 架构师 run 结束并产生 token 用量
- **THEN** 用量归账到独立类目文件且条目标注 `agent_type: "architect"`

### Requirement: 新增角色同步文档

新增 `architect` 角色后，`docs/help/02-concepts.md` 的 Agent 类型表与 `docs/help/09-config.md` 中 `agents.models` 的角色枚举 MUST 同步更新（后者为写死枚举，不更新即成为错误文档）。

#### Scenario: 角色表已更新

- **WHEN** 检索文档中的 Agent 类型枚举
- **THEN** 均包含 `architect`，且无「键取九角色」一类与新角色数不符的表述
