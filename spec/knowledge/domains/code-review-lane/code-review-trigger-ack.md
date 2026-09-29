# 审查手动触发受理回链

<!-- knowledge: capability=code-review-trigger-ack rev=1
     sources=spec/archive/2026-09-29-add-code-review-trigger-ack -->

代码审查手动触发的受理结果回链：daemon 消费触发信号后把判定结果落盘为结果文件，POST 侧受理窗口守卫消灭假受理，前端按回链三态分派用户反馈。

## 规则

- 手动触发走「写文件信号 → daemon 异步消费」链路，POST 返回 200 只代表信号已写入，不构成启动确认。
- daemon 消费触发信号（`.fenix/code_review_request.json`）后把判定结果原子写入 `.fenix/code_review_request_result.json`（同目录临时文件 + rename，消费者不可读到半写内容）。
- 结果文件字段：`requested_at`（回链信号 payload 的 `requested_at`，前端凭它与本次触发匹配）、`status` 三值（`started` 已受理投递 / `dropped` 被守卫拒绝 / `failed` 已受理但执行前置失败）、`reason`（机器可读 slug 或 null）、`message`（面向用户的中文文案）、`finished_at`（UTC ISO8601，本条结果写入时刻）。
- 结果文件单文件覆盖写，无历史留存与清理；只承载受理判定，不承载 run 终态——daemon 不在 run 结束时回写结果，run 是否已启动过由窗口守卫凭 review_id epoch 判定。
- daemon 侧所有丢弃/失败分支必须落结果文件并给出明确 reason，禁止只记日志静默丢弃：hosting_state 守卫拒绝（`daemon_not_running` / `daemon_unmanaged`）、payload 非法（`invalid_payload`）、单飞已在跑（`already_running`）、worker 池投递异常（`submit_error`）、manifest 收集异常（`manifest_error`）或为空（`manifest_empty`）。
- 落结果不改变既有控制流：单飞旗标的置位/复位顺序保持不变。
- 只读端点 `GET /api/code-review/run-result?project=<name>` 返回回链文件内容；文件缺失或 JSON 损坏时返回缺省态（`requested_at`/`status` 为 null 的空形态），不抛 500；项目不存在返回 404。
- `POST /api/code-review/run` 的守卫序为：running 守卫 → 信号独占创建 → 受理窗口守卫。受理窗口守卫在四个条件同时成立时返回 409 稳定错误码 `code_review_ack_pending`：结果 `status=started`；`progress.running=false`（run 尚未开始）；结果 `finished_at` 距今不超过 900 秒（新鲜度窗口）；`progress.review_id` 内嵌 epoch 不大于 `finished_at`（受理后尚无新 run 启动过）。
- epoch 判据与新鲜度窗口缺一不可：`started + running=false` 形态二义（「排队收集中」与「已跑完」完全相同），run 一旦启动即产生 epoch 大于 `finished_at` 的 review_id，凭此放行已跑完后的合法重触发；新鲜度窗口防陈旧结果永久锁死触发。
- 窗口守卫读结果与 running 判定之间的竞态 fail-open：放行的重复信号由 daemon 单飞拒绝并落 `dropped/already_running` 结果，链路终点是有反馈的显式拒绝，无静默路径。
- 既有守卫判定口径不变：`progress.running=true` 时仍由既有 running 守卫先命中返回 409 `code_review_running`；信号文件未被消费时仍被 O_EXCL 守卫以 409 拒绝——窗口守卫补的是「信号已消费、run 未开始」的空隙。

## 关键行为

前端（质量页签）触发后的受理等待态：

- POST 返回 200 后不弹「已受理」类终态文案，进入受理等待：以 1 秒间隔轮询 run-result，上限 120 秒；仅当结果 `requested_at` 与本次触发返回的一致才视为本次结果，读到陈旧残留继续轮询、不弹提示。
- 按结果分派：`started` → 以 2 秒间隔轮询 progress 直到 `running=true`（上限 60 秒），既有「审查进行中」卡片与进度轮询自动接管，`running=true` 前不弹无信息量的中间提示；`dropped` → 警告回显 `message`；`failed` → 错误回显 `message`；任一段超时 → 给出「请稍后在进度卡片或 daemon 日志确认」类兜底提示并解禁按钮。
- 受理等待期间两个审查触发按钮保持禁用（独立门控态，不并入「HTTP 请求进行中」的通用态，不影响取消与自动修复按钮）；等待期内重复触发同时被 POST 侧窗口守卫显式 409 拒绝。
- 组件卸载/切页签/切项目立即停止轮询且不再弹任何提示。

## 溯源

- [2026-09-29 add-code-review-trigger-ack](spec/archive/2026-09-29-add-code-review-trigger-ack/) — 新建本能力：daemon 写侧三态落盘（移植 code-fix 手动触发回链先例、键名随本车道信号 payload 用 `requested_at`）、GET run-result 只读端点、POST 受理窗口守卫（epoch 判据为评审修补）、前端受理等待态与三态分派反馈。
