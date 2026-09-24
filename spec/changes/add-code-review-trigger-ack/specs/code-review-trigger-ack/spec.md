## ADDED Requirements

### Requirement: 触发判定结果回链落盘

daemon 消费 code-review 手动触发信号（`.fenix/code_review_request.json`）后，SHALL 把判定结果原子写入 `.fenix/code_review_request_result.json`：`{requested_at, status, reason, message, finished_at}`，其中 `requested_at` SHALL 回链信号 payload 的 `requested_at`，`status` SHALL 为 `started`（已投递执行）/ `dropped`（被守卫拒绝）/ `failed`（已受理但执行前置失败）三值之一，`message` 为面向用户的人类可读中文文案，`finished_at` 为 UTC ISO8601。写入 SHALL 原子（同目录临时文件 + rename），MUST NOT 让消费者读到半写内容。daemon 侧所有丢弃/失败分支——hosting_state 守卫拒绝、单飞已在跑、payload 非法、worker 池投递异常、manifest 收集异常、manifest 为空——MUST 全部落结果文件并给出明确 reason，MUST NOT 静默丢弃信号（对齐 add-code-fix-manual-trigger 先例）。

#### Scenario: 受理投递成功
- **WHEN** 信号通过全部守卫且 worker 池投递成功
- **THEN** 结果文件 `status=started`、`requested_at` 与信号一致、`reason=null`

#### Scenario: 单飞在跑时拒绝并落结果
- **WHEN** 信号被消费时已有 code-review run 在跑（单飞判定命中）
- **THEN** 结果文件 `status=dropped` 且 `reason=already_running`、`message` 中文可读，MUST NOT 只记日志

#### Scenario: daemon 状态守卫拒绝并落结果
- **WHEN** 信号被消费时 daemon 实际处于 stopped 或 unmanaged（绕过 POST 前置拦截写入的信号）
- **THEN** 结果文件 `status=dropped` 且 reason 区分 `daemon_not_running` / `daemon_unmanaged`

#### Scenario: manifest 收集失败落 failed
- **WHEN** worker 内 `collect_manifest` 抛异常或收集结果为空
- **THEN** 结果文件 `status=failed` 且 reason 区分 `manifest_error` / `manifest_empty`，不静默跳过

#### Scenario: 单飞旗标复位语义不变
- **WHEN** 任一分支落结果文件
- **THEN** 既有单飞旗标置位/复位顺序与现状完全一致（落盘不改变控制流）

### Requirement: 结果只读端点

系统 SHALL 提供只读端点 `GET /api/code-review/run-result?project=<name>` 返回回链文件内容；文件缺失或损坏时 SHALL 返回缺省态（`requested_at`/`status` 为 null 的空形态），MUST NOT 500（形态对齐 `GET /api/code-review/fix-run-result`）。项目不存在 SHALL 返回 404。

#### Scenario: 结果可读
- **WHEN** 回链文件存在且为合法 JSON
- **THEN** 端点原样返回其内容

#### Scenario: 结果缺失返回缺省态
- **WHEN** 回链文件不存在或 JSON 损坏
- **THEN** 端点返回 200 与缺省态对象，不抛 500

### Requirement: 触发端点受理窗口守卫

`POST /api/code-review/run` SHALL 在既有 running 守卫与信号独占创建之前增加受理窗口守卫：当回链结果 `status=started` 且 `progress.running=false`（run 尚未开始）且结果 `finished_at` 距今不超过 900 秒（新鲜度窗口）且 `progress.review_id` 内嵌 epoch 不大于 `finished_at`（受理后尚无新 run 启动过——run 结束后结果文件仍停留 `started`，须凭此区分「排队中」与「已跑完」）时，SHALL 返回 409 与稳定错误码 `code_review_ack_pending`，MUST NOT 覆盖既有 `code_review_running`（409）与信号独占创建（409）语义。既有守卫的判定口径 MUST NOT 改变。

#### Scenario: 窗口内重复触发被显式拒绝
- **WHEN** daemon 已受理上一触发（结果 started）但 run 尚未开始（progress.running=false）且结果未超新鲜度窗口，用户再次 POST
- **THEN** 返回 409 `code_review_ack_pending`，信号文件不被写入

#### Scenario: run 已开始时守卫让位既有错误码
- **WHEN** progress.running=true 时用户 POST
- **THEN** 仍返回 409 `code_review_running`（既有守卫先命中）

#### Scenario: run 结束后陈旧结果不锁死触发
- **WHEN** 上一轮审查已结束（progress.running=false）且回链结果 finished_at 距今超过 900 秒
- **THEN** 窗口守卫放行，新信号正常写入（若 daemon 侧仍在执行旧链则由单飞拒绝并落 dropped 结果）

#### Scenario: run 结束后窗口内重触发不误拒
- **WHEN** 上一轮审查已结束（progress.running=false），结果文件仍为 `started` 且 `finished_at` 距今不足 900 秒，但最新 `review_id` 内嵌 epoch 大于 `finished_at`（受理的 run 已启动并结束过）
- **THEN** 窗口守卫放行，新信号正常写入（若恰有审查在跑则由既有 `code_review_running` 守卫或 daemon 单飞落结果给出显式拒绝）

### Requirement: 前端受理等待与分派反馈

质量页签（QualityTab）触发审查后 SHALL 进入受理等待态：POST 返回 200 后不弹出「已受理」类终态文案，改为轮询 `GET /api/code-review/run-result`（1 秒间隔，上限 120 秒），仅当结果 `requested_at` 与本次触发返回的 `requested_at` 一致时才视为本次结果，陈旧残留结果 MUST NOT 被当作本次反馈。按结果分派：`started` → 以 2 秒间隔轮询 progress 直到 `running=true`（上限 60 秒）让既有进度卡片接管，`running=true` 前 SHALL NOT 弹出无信息量的中间提示（含既有「已受理」终态文案——POST 200 只代表信号已写，不构成启动确认）；`dropped` → 警告回显 `message`；`failed` → 错误回显 `message`；任一段超时 → 给出「请稍后在进度卡片或 daemon 日志确认」类兜底提示。受理等待期间两个审查触发按钮 SHALL 保持禁用（独立门控态，不影响取消与自动修复按钮）；组件卸载/切页签/切项目 SHALL 立即停止轮询且不再弹提示。

#### Scenario: started 后卡片接管
- **WHEN** 轮询读到本次 `status=started` 且随后 progress.running=true
- **THEN** 既有「审查进行中」卡片与 2s 进度轮询自动接管展示，无需额外操作

#### Scenario: 被拒原因可见
- **WHEN** 轮询读到本次 `status=dropped`（如 already_running）
- **THEN** 弹出警告文案回显拒绝原因，按钮解禁

#### Scenario: 等待期间不可重复触发
- **WHEN** 受理等待态进行中（POST 已返回、终态反馈未到）
- **THEN** 两个审查触发按钮均为禁用态，点击无效

#### Scenario: 超时兜底
- **WHEN** 120 秒内未读到 `requested_at` 匹配的结果
- **THEN** 弹出「未收到启动确认」类兜底提示并解禁按钮，不挂死在等待态

#### Scenario: 陈旧结果不误报
- **WHEN** 轮询读到的结果 `requested_at` 与本次触发不一致（上一轮残留）
- **THEN** 继续轮询，MUST NOT 弹出残留学生成的提示

#### Scenario: 离开页面停止反馈
- **WHEN** 受理等待轮询进行中用户切走页签或切换项目
- **THEN** 轮询立即停止且不弹出任何提示
