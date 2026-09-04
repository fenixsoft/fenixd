# daily-self-review

## ADDED Requirements

### Requirement: 每晚定时自省

配置 `admin.self_review.enabled: true` 时，daemon MUST 在每日本地时间 `admin.self_review.run_at`（HH:MM，缺省 22:00）后由 Administrator Agent 执行一次当日工作回顾；执行数据源 MUST 包含当日 STATE 终态分布、runs 统计（成功/失败/秒挂/超时/丢弃计数）、admin 告警与处置记录、日志 ERROR 聚合。`enabled: false` 时全链路零动作（不调度、不执行、不写文件）。

#### Scenario: 定时触发执行

- **WHEN** enabled=true、run_at=22:00，本地时间到达 22:00 后的第一个巡检周期
- **THEN** daemon 发起一次自省 run，产出回顾并追加写入项目根 todo.md，状态文件记录今日已执行

#### Scenario: 开关关闭零动作

- **WHEN** enabled=false，本地时间超过 run_at
- **THEN** 无自省 run、无 todo.md 写入、无状态文件更新

### Requirement: 防重复与补跑

同一自然日 MUST 至多执行一次自省（以状态文件的 last_run_date 判定）。daemon 启动时若发现当日 run_at 已过且今日尚未执行，MUST 在启动后补跑一次；跨日后计数归零恢复调度。

#### Scenario: 同日不重复

- **WHEN** 今日自省已执行（last_run_date=今天），巡检周期再次到达执行条件
- **THEN** 不发起第二次自省 run

#### Scenario: 错过后补跑

- **WHEN** run_at=22:00，daemon 于 23:30 启动且今日未执行过
- **THEN** 启动后的首个巡检周期补跑自省，状态文件更新为今日

### Requirement: todo.md 结构化追加

自省回顾 MUST 以 markdown 追加（不覆盖历史）写入项目根 `todo.md`：每日一个 `## YYYY-MM-DD` 分节，内含「浪费」「失误」「可改进」三个小节，每条 MUST 含证据（具体数字/事件）与建议动作，条目清晰度标准为「未参与当日工作的新 agent 可据此直接起草 SPEC 提案」。todo.md 不存在时 MUST 创建。写入成功后 MUST 自动 commit（仅含 todo.md 路径）并尝试 push，失败降级 WARNING 不影响下次追加。

#### Scenario: 首次写入创建文件

- **WHEN** 项目根无 todo.md，自省产出第一条回顾
- **THEN** todo.md 被创建，含 `## YYYY-MM-DD` 分节与三个小节，且产生仅含 todo.md 的 commit

#### Scenario: 追加不覆盖

- **WHEN** todo.md 已存在历史分节，今日自省完成
- **THEN** 新分节追加在文件尾部，历史分节内容不变

#### Scenario: 条目可复用于 SPEC 起草

- **WHEN** 自省产出某条改进点（如「CLI 秒挂 61 连发」）
- **THEN** 该条目包含可量化的证据（次数/时长/根因）与明确建议（如「连续 ≥3 次秒挂进入冷却」），新 agent 无需追问即可据此起草 SPEC 需求

### Requirement: 上下文阅读开关

配置 `admin.self_review.read_todo: true` 时，自省 prompt MUST 包含既有 todo.md 的全文内容（供 Agent 识别历史条目、避免重复、标注已闭环项）；false 时 prompt 不含 todo.md 内容。默认 false。

#### Scenario: 开启时注入上下文

- **WHEN** read_todo=true 且 todo.md 存在历史分节，自省 run 启动
- **THEN** 自省 prompt 含 todo.md 全文，产出对新条目标注与历史条目的关系（新增/恶化/已闭环）

#### Scenario: 关闭时不注入

- **WHEN** read_todo=false，自省 run 启动
- **THEN** prompt 不含 todo.md 内容

### Requirement: 禁止自动创建 SPEC

自省链路 MUST NOT 依据 todo.md 条目自动创建 SPEC、注册 STATE 条目或派发 implementer——SPEC 立项判定权 MUST 保留给用户；自省产出与 todo.md 仅供阅读。

#### Scenario: 自省后无新 SPEC

- **WHEN** 自省产出 N 条可改进建议并写入 todo.md
- **THEN** openspec/changes/ 与 STATE.md 均无任何新增条目，无 agent 派发

### Requirement: 配置界面

`admin.self_review` 的三个键（enabled/run_at/read_todo）MUST 在 Dashboard v3 设置页提供读写界面：enabled 与 read_todo 为开关控件，run_at 为时间输入（HH:MM 校验）；保存后经既有配置热更新机制生效，无需重启 daemon。

#### Scenario: 设置页修改生效

- **WHEN** 用户在 v3 设置页将 run_at 从 22:00 改为 23:00 并保存
- **THEN** 配置文件更新，热更新生效，次日自省在 23:00 后触发；非法输入（如 25:00）被前端与后端双重校验拒绝
