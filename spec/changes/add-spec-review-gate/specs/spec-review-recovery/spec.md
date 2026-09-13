# spec-review-recovery — 评审结论消费与人工恢复

## ADDED Requirements

### Requirement: 评审结论的机械消费

框架 SHALL 在评审 run 收工并通过结果硬门与写入边界校验后，按 `status` 机械收口，MUST NOT 交由 LLM 二次解释：

- `approved` → `transition(spec, "ready")`，随后直调 `_on_spec_ready(spec)` 进入实现调度。
- `repaired` → 同上（`transition ready` → 直调 `_on_spec_ready`）。
- `rejected` → `transition(spec, "blocked")`，并把 `findings` 中 `severity: blocking` 条目的 `aspect` / `detail` / `evidence` 摘要写入 STATE 的 `error` 字段，前缀为 `spec-review-rejected:`。

收口动作 MUST 与既有晋升成功路径同语义（直调 `_on_spec_ready` 而非依赖事件循环），保证晋升后立即进入实现调度。

#### Scenario: approved 收口到 ready
- **WHEN** 评审结论为 `approved` 且校验通过
- **THEN** 状态变为 `ready`，随即派发 implementer 调度

#### Scenario: repaired 收口到 ready
- **WHEN** 评审结论为 `repaired` 且校验通过
- **THEN** 状态变为 `ready`，SPEC 目录保留评审者的修补，随即派发 implementer 调度

#### Scenario: rejected 收口到 blocked
- **WHEN** 评审结论为 `rejected`
- **THEN** 状态变为 `blocked`，`error` 字段以 `spec-review-rejected:` 开头并含 blocking 条目的维度与证据摘要

#### Scenario: 不进入实现调度
- **WHEN** 评审结论为 `rejected`
- **THEN** MUST NOT 派发 implementer，MUST NOT 执行 `_on_spec_ready`

### Requirement: 评审故障的重试与标记

评审 run 未通过结果硬门或写入边界校验时，本**轮**评审 SHALL 判定为「未完成」，MUST NOT 被归入任何评审结论（尤其 MUST NOT 按 `approved` 放行）。框架 SHALL 递增内部字段 `_review_attempts` 并重试，累计尝试上限为 3 次（首次派发 + 最多 2 次重试）。达到上限后 SHALL `transition(spec, "blocked")` 并把失败原因写入 `error`，前缀为 `spec-review-incomplete:`。

失败原因 SHALL 具体可辨，至少区分：进程非零退出、结果文件缺失或为空、JSON 非法、`status` 越白名单、mtime 陈旧、`repairs` 路径越界、SPEC 目录外越界写入、`status` 与改动不一致。

#### Scenario: 首次失败后重试
- **WHEN** 评审 run 首次未完成
- **THEN** SPEC 保持 `reviewing`，`_review_attempts` 递增，随后重试派发

#### Scenario: 达上限转 blocked
- **WHEN** 评审 run 累计 3 次尝试均未完成
- **THEN** 状态变为 `blocked`，`error` 以 `spec-review-incomplete:` 开头并含具体失败原因

#### Scenario: 故障不被当作放行
- **WHEN** 评审 run 失败且结果文件缺失
- **THEN** MUST NOT 因「无否决证据」而将 SPEC 放行到 `ready`

#### Scenario: 重试成功后恢复正轨
- **WHEN** 首次评审失败，重试轮返回 `approved` 且校验通过
- **THEN** 状态变为 `ready`，`_review_attempts` 被重置清空

#### Scenario: 越界写入归此类
- **WHEN** 评审 run 在 `spec/changes/<spec>/` 之外产生了改动
- **THEN** 本轮判定为未完成并进入重试计数，越界文件清单记入错误原因

### Requirement: 两类 blocked 的区分

评审相关的 blocked SHALL 通过 `error` 前缀与其它 blocked 原因严格区分：`spec-review-rejected:`（方案被否决）与 `spec-review-incomplete:`（评审未完成）。两者 MUST NOT 复用既有熔断、冻结、合并失败等 blocked 的 error 前缀。`error` 字段内容 SHALL 足以让 Dashboard 与人工在不读 run 流转录的情况下判断该做什么。

#### Scenario: 否决可被前缀识别
- **WHEN** 读取一个因评审否决进入 blocked 的 SPEC 条目
- **THEN** 其 `error` 以 `spec-review-rejected:` 开头

#### Scenario: 未完成可被前缀识别
- **WHEN** 读取一个因评审故障进入 blocked 的 SPEC 条目
- **THEN** 其 `error` 以 `spec-review-incomplete:` 开头

#### Scenario: 不与冻结混淆
- **WHEN** 某 SPEC 通过人工冻结进入 blocked
- **THEN** 其 `error` 为冻结规范前缀，MUST NOT 呈现 `spec-review-` 前缀

### Requirement: 人工恢复的双路径

系统 SHALL 为评审相关 blocked 的 SPEC 提供两条人工恢复路径：

1. **重新评审**：`transition(spec, "reviewing")`，用于人工已修改 SPEC 内容、要求再次过评审门。
2. **担责放行**：`transition(spec, "ready")`（沿用既有边），用于人工裁决后直接进入实现调度，不再自动重评。

两条路径 MUST 都由人工显式触发，MUST NOT 由任何自动链路调用。

#### Scenario: 人工重新评审
- **WHEN** 人工对一个 `spec-review-rejected:` 的 blocked SPEC 触发重新评审
- **THEN** 状态变为 `reviewing` 并派发新的评审 run

#### Scenario: 人工担责放行
- **WHEN** 人工对一个评审相关 blocked 的 SPEC 触发担责放行
- **THEN** 状态变为 `ready`，SPEC 进入实现调度，MUST NOT 再自动派发评审 run

#### Scenario: 自动链路不触发恢复
- **WHEN** 无人工操作且 SPEC 处于评审相关 blocked
- **THEN** 状态保持不变，MUST NOT 自动恢复到 `reviewing` 或 `ready`

### Requirement: 重新评审入口的开放条件

重新评审动作 SHALL 有明确的开放条件，MUST NOT 对任意 blocked SPEC 开放：

- 目标 SPEC 状态 MUST 为 `blocked`。
- 目标 SPEC 的 `error` MUST 以 `spec-review-rejected:` 或 `spec-review-incomplete:` 开头。
- 目标 SPEC MUST NOT 带 `frozen: true` 标记。

任一条件不满足时，动作 SHALL 被拒绝并返回明确原因，STATE MUST NOT 发生任何变更。对非评审类 blocked（熔断、合并失败、人工冻结等）执行重新评审 SHALL 被拒绝，防止把不应进入自动链的 SPEC 误推进评审。

#### Scenario: 非评审 blocked 被拒
- **WHEN** 对因熔断进入 blocked 的 SPEC 触发重新评审
- **THEN** 动作被拒绝并返回原因，状态保持 `blocked`

#### Scenario: 冻结态被拒
- **WHEN** 对带 `frozen: true` 的 SPEC 触发重新评审
- **THEN** 动作被拒绝并返回原因，状态保持 `blocked`，冻结标记未被清除

#### Scenario: 状态不符被拒
- **WHEN** 对 `ready` 状态的 SPEC 触发重新评审
- **THEN** 动作被拒绝并返回原因，状态保持 `ready`

#### Scenario: 幂等防御
- **WHEN** 对同一 SPEC 连续两次触发重新评审
- **THEN** 第二次因状态已非 `blocked` 被拒绝，MUST NOT 派发两个评审 run

### Requirement: Dashboard 入口与状态展示

Dashboard SHALL 在项目页 SPEC 列表中展示 `reviewing` 状态，并为处于评审相关 blocked 的 SPEC 提供「重新评审」操作入口（带确认）。状态色板 SHALL 为 `reviewing` 提供独立于既有 10 个状态的视觉标识。设置页 SHALL 在「审批」页签提供 `gates.spec_review_mode` 单选控件（`auto` / `never`），位置在草稿晋升模式设置项上方或下方相邻处，并附说明文字。设置页提示词页签与模型分配 SHALL 包含 `spec-review` 角色。

#### Scenario: reviewing 状态可见
- **WHEN** 项目页加载且某 SPEC 状态为 `reviewing`
- **THEN** 该行展示 `reviewing` 状态标识，与其它 10 个状态在视觉上可区分

#### Scenario: 重新评审按钮仅对评审类 blocked 可见
- **WHEN** 项目页加载且某 SPEC 为 `spec-review-rejected:` 的 blocked
- **THEN** 该行提供「重新评审」入口；因熔断等其它原因 blocked 的行不提供该入口

#### Scenario: 操作失败展示原因
- **WHEN** 用户在项目页对不符合开放条件的 SPEC 触发重新评审
- **THEN** 页面展示后端返回的拒绝原因，SPEC 状态不变

#### Scenario: 设置页单选反映当前配置
- **WHEN** 当前 `gates.spec_review_mode` 为 `never`
- **THEN** 设置页加载后对应单选选中 `never`

#### Scenario: 设置页保存生效
- **WHEN** 用户在设置页选择 `never` 并保存
- **THEN** 配置写入成功且无错误提示；重新进入页面后选中项与配置一致

#### Scenario: 提示词与模型分配含新角色
- **WHEN** 打开设置页的提示词页签与模型分配
- **THEN** 均包含 `spec-review` 角色条目

### Requirement: CLI 重新评审命令

系统 SHALL 提供 CLI 命令 `bin/fenix_cli.py review <spec> [--project <path>]`（缺省 project 为当前目录），语义与 Dashboard 重新评审入口一致：对符合开放条件的 blocked SPEC 执行 `blocked → reviewing`。成功与失败结果 SHALL 打印到终端，失败 MUST 以非零退出码表示。

#### Scenario: CLI 重新评审成功
- **WHEN** 对 `spec-review-rejected:` 的 blocked SPEC 执行为 `python3 bin/fenix_cli.py review <spec>`
- **THEN** 命令输出成功信息，状态变为 `reviewing`，退出码为 0

#### Scenario: CLI 拒绝非评审 blocked
- **WHEN** 对熔断 blocked 的 SPEC 执行 CLI review
- **THEN** 命令输出拒绝原因，状态不变，退出码非 0

#### Scenario: CLI 指定项目路径
- **WHEN** 在项目根目录之外执行并传 `--project <path>`
- **THEN** 重新评审动作作用于指定项目的 STATE.md
