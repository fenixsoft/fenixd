# turn-limit-lifecycle

## ADDED Requirements

### Requirement: 轮次上限收口 WIP 保全（锚点 C）

框架轮询环判定 run 达到 `agents.max_turns` 轮次上限并对子进程执行终止（terminate/grace/kill 序列）后，在异常收口前 MUST 对该 attempt 正在使用的 worktree（存在且为有效 git worktree 时）执行一次 WIP checkpoint 提交，锚点标识为 `turn-limit`。该提交 MUST 复用既有 `commit_wip_checkpoint` helper（尽力而为、失败降级不阻断），并遵守既有消息契约 `fenix(wip): checkpoint turn-limit <spec>`。无 worktree 载体或路径失效时 MUST 跳过（与锚点 A/B 同语义），不产生空提交。

#### Scenario: builtin 型零提交 run 被强杀后现场保全

- **WHEN** implementer run 在零分支提交状态下触及 400 轮上限，worktree 内有未提交产物，轮询环终止子进程后进入收口
- **THEN** worktree 上产生一条 `fenix(wip): checkpoint turn-limit <spec>` 提交，包含全部未提交产物；后续 attempt resume 或降级重建均能从该提交恢复

#### Scenario: worktree 干净或无载体时零动作

- **WHEN** turn-limit 收口时 worktree 无未提交变更（`git status --porcelain` 为空），或本 attempt 无有效 worktree 载体
- **THEN** 不产生任何提交、不报错、收口流程继续（幂等，与锚点 A/B 一致）

#### Scenario: WIP 提交失败不阻断收口

- **WHEN** 锚点 C 的 git 操作超时（15s）或失败
- **THEN** 仅 WARNING 留痕，run 的既有失败收口（append_run_error + RuntimeError）照常执行

### Requirement: 轮次上限活性感知续期

轮询环判定 run 达到轮次上限时 MUST 按封闭决策矩阵判定续期或终止，不得无差别 kill：run 表现出真实推进活性（判定窗口内分支有新提交，或有新 tool_result 事件流量）且续期次数未达封顶时，执行轮次续期（extend 上限量），以 `turn_extension` 事件落 run 产物文件留痕；无活性或续期封顶时才执行 kill + 锚点 C 收口。判定 MUST 与超时路径既有 `_supervision_deadline_action` 封闭矩阵语义同构（extend 有据、封顶有限、每次续期留痕），具体窗口/步长/封顶为配置常量并在 design 固化。

#### Scenario: 健康推进中的 run 获得续期

- **WHEN** run 达到 400 轮上限，判定窗口内分支有新提交（如 add-ssh-foundation a1 第 378 轮仍在勾选任务、每任务稳定出提交）
- **THEN** 不 kill，轮次上限按固定步长 extend，run 产物文件新增 `turn_extension` 记录（含 extension 序号、步长、活性证据摘要、新上限）

#### Scenario: 无活性 run 直接终止并保全

- **WHEN** run 达到轮次上限且判定窗口内既无新提交也无新 tool_result 流量（如卡死空转）
- **THEN** 执行既有 kill 序列 + 锚点 C 收口 + 既有 turn_limit_error 失败收口，行为与现行一致

#### Scenario: 续期封顶后终止

- **WHEN** run 已连续用尽全部续期次数（封顶），再次触及新上限
- **THEN** 不再 extend，执行 kill + 锚点 C 收口 + 失败收口

#### Scenario: 续期与超时矩阵互不干扰

- **WHEN** run 同时受超时死线与轮次上限约束
- **THEN** 超时路径既有 `_supervision_deadline_action` 行为不变（其 extend 计数与 turn 续期计数相互独立），两者任一命中均按各自矩阵处置

### Requirement: 强杀路径消耗观测口径

turn-limit/timeout 等强杀路径（无 result 终态事件）的成本记账 MUST 区分「观测不到」与「确认为零」：DEBUG 留痕与相关日志 MUST 记为消耗不可观测（unobserved）语义，MUST NOT 记「tokens counted as 0」；STATE 侧成本累计 MUST 保持不伪造原则（不凭空补数、不展示虚构金额），但内部口径须可区分 unobserved 与 zero 两种状态。

#### Scenario: turn-limit 失败日志不再误导审计

- **WHEN** implementer run 因轮次上限被强杀，attempt 循环记录失败原因
- **THEN** DEBUG/WARNING 日志写明「消耗不可观测（无 result 终态，真实消耗未知且非零为大概率）」，不出现「tokens counted as 0」字样

#### Scenario: STATE 成本累计不因 unobserved 虚增

- **WHEN** turn-limit 强杀后 attempt 循环走 `_extract_usage_info(None)` 兜底
- **THEN** STATE 侧金额/计数累计不因该 run 增加（不伪造），该 run 的 usage 记录带 unobserved 标识可供审计区分
