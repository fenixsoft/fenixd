# adjudication-alert-narrative 规格

## ADDED Requirements

### Requirement: 转人工裁决告警附带三段式叙事

写转人工裁决告警（kind=escalation 且携带 choices 的桶 2 信号）时，系统 SHALL 在告警落盘的同一时机经一次轻量 LLM 调用生成三段式叙事，并以 `narrative` 字段并入告警记录。narrative MUST 为含下列三个固定段落的 Markdown（段落标题依次为「发生了什么」「为什么需要你决策」「决策选项」，顺序固定）：

- **发生了什么**：把 description/evidence 中的技术串（如 `failure_profile=round1:real-bugs; round3:repeat`）翻译为因果白话，指明信号主体（哪个 spec、哪个闸门、第几轮）；
- **为什么需要你决策**：说明自动链已尝试的路径与停止原因（哪条计数器/预算/闸门到顶），以及放任自动继续的代价；
- **决策选项**：结合本告警上下文，对 choices 快照中的每个选项（按 id 一一对应）给出含义、执行后果与建议倾向（建议倾向 MUST 标注为参考，最终由人决定）。

narrative 为纯增强字段，MUST NOT 改写 description/evidence/recommended_action/choices/trigger 任一既有字段的结构化语义（既有消费方 alert-resolve、闭环判定、Administrator 处置 MUST 零感知）。

#### Scenario: 升级闸门告警携带三段式叙事

- **WHEN** 升级闸门对某 spec 触发第 4 轮 verify_fail_escalation 冻结（叙事开关开启、LLM 通道正常），告警经汇聚写入口落盘
- **THEN** 告警记录含 `narrative` 字段，其文本依次包含「发生了什么」「为什么需要你决策」「决策选项」三个段落标题
- **AND** 「发生了什么」段含 spec 名与「连续失败第 4 轮」语义的白话转述
- **AND** 「决策选项」段对 choices 快照的每个 id（如 continue_auto_fix/manual_fixed_reverify）各有一段对应解释
- **AND** description/evidence/recommended_action/choices/trigger 字段内容与关闭叙事时的基线形态完全一致

#### Scenario: 叙事生成不改变既有消费方行为

- **WHEN** 带 narrative 的告警被 POST /api/alert-resolve 按 choices 的 action 执行裁决
- **THEN** 动词分派行为与无 narrative 的告警完全一致（narrative 不参与分派与闭环判定）

### Requirement: 叙事覆盖全部转人工裁决告警

叙事接线 SHALL 覆盖全部桶 2 转人工裁决告警发射点：汇聚写入口（pm_engine._send_human_escalation_alert，覆盖预算耗尽/升级闸门/评审两族/judge 重跑上限/同因重派熔断/恢复期回调）以及两个旁路 choices 附带点（core/worktree_manager/mergeback.py 的 build_artifact_paths_missing、core/agent_runner/token_budget.py 的 token_budget）。旁路点 SHALL 复用同一叙事辅助模块，MUST NOT 各自内联第二套生成逻辑。

覆盖面口径说明（评审补注 spec-review 2026-09-29）：三处发射点的记录 kind 并不同质——汇聚点与 token_budget 记录为 kind=ESCALATION（进前端告警区，token_budget.py:236），build_artifact_paths_missing 记录为 kind=SIGNAL（不进前端告警区，choices 由 alert-resolve 与 Administrator 处置消费，mergeback.py:465 注释）。「前端告警区渲染叙事」的渲染约束仅适用于进入告警区的 ESCALATION 记录；SIGNAL 记录的 narrative 仅要求字段落盘（供消费侧读取），零渲染要求。

#### Scenario: 旁路发射点同样携带叙事

- **WHEN** merge-back 产物路径缺失信号（build_artifact_paths_missing）经 worktree_manager/mergeback.py 写告警（叙事开关开启、LLM 通道正常）
- **THEN** 告警记录含 narrative 字段且三段结构齐全
- **AND** token_budget 信号经其发射点写告警时同样含 narrative

#### Scenario: 桶 0 知情类信号不受影响

- **WHEN** 桶 0（知情/自愈类，choices_for 返回空集）信号写告警
- **THEN** 不发起 LLM 叙事调用，告警记录不含 narrative 字段

### Requirement: 叙事失败兜底 fail-open

LLM 叙事调用失败（异常、超时、空输出）时，系统 SHALL 让告警以既有机械文案照常落盘（不写 narrative 字段），MUST NOT 阻塞发射链路、MUST NOT 重试超过一次、MUST 在日志记 WARNING 留痕。同步调用的总耗时 MUST NOT 超过 `admin.narrative_timeout_seconds`（整数秒，缺省 60）。

#### Scenario: LLM 超时回退机械文案

- **WHEN** 叙事开关开启但 LLM 调用持续超过 narrative_timeout_seconds 无响应
- **THEN** 告警在超时上限内以机械文案照常落盘，记录不含 narrative 字段
- **AND** 日志含该次叙事失败的 WARNING 记录，发射链路（冻结/告警后续步骤）无异常中断

#### Scenario: LLM 异常立即回退不重试链路

- **WHEN** LLM 调用抛出异常（网关 5xx/连接拒绝）
- **THEN** 至多一次尝试后放弃，告警照常落盘（无 narrative），发射链路正常收口

### Requirement: 叙事开关与配置

系统 SHALL 提供三个配置项并给出 Dashboard 设置界面：

- `admin.narrative_enabled`（bool，缺省 true）：关闭时写告警零 LLM 调用、零额外延迟，行为与本 SPEC 落地前完全一致；
- `admin.narrative_timeout_seconds`（int，缺省 60）：叙事同步调用硬超时；
- `admin.narrative_model`（str，缺省空=复用 `admin.agent_model`，仍为空时复用框架默认模型）。

三者 SHALL 加入 config.template.yaml 的 admin 段（带中文注释），并在设置页 SystemPanel 的 admin 作用域出可编辑控件（保存走既有配置保存通道，缺省值与模板一致）。

#### Scenario: 开关关闭时行为退化为现状

- **WHEN** admin.narrative_enabled 为 false，任一桶 2 信号写告警
- **THEN** 告警不含 narrative 字段，其余字段与基线一致，写路径无 LLM 调用（耗时与基线同量级）

#### Scenario: 设置页可编辑叙事配置

- **WHEN** 用户在设置页 SystemPanel 修改 narrative_timeout_seconds 为 30 并保存
- **THEN** 配置持久化生效（热更新通道），后续告警叙事调用按 30 秒硬超时执行

### Requirement: 前端告警区渲染叙事

Dashboard 告警区 SHALL 在证据（evidence）之前渲染 narrative 三段式（Markdown 渲染，默认展开）；记录无 narrative 字段时 MUST 保持现有渲染不变。choices 下拉与执行按钮的交互 MUST 与现状一致（叙事仅为可读性增强，不承载任何机器语义）。

#### Scenario: 有叙事与无叙事的渲染分叉

- **WHEN** 告警列表同时含带 narrative 与不带 narrative 的记录
- **THEN** 带叙事的记录在证据前显示三段式内容，不带叙事的记录渲染与现状逐像素同构（无新增空壳区块）

#### Scenario: 长叙事不破坏布局

- **WHEN** narrative 文本超过 2000 字符
- **THEN** 告警卡片以既有序列化容器规则折叠/滚动展示，不横向溢出、不遮挡 choices 操作区
