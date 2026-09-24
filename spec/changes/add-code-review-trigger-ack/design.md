## Context

手动触发 code-review 的现有链路是「文件信号 + 异步消费」：`POST /api/code-review/run` 原子写 `.fenix/code_review_request.json` 即返回 200（`core/dashboard/routes/code_review_routes.py`），daemon 主循环 1s tick 经 `_check_code_review_requests`（`fenixd.py:2266`）消费信号，投递 `_admin_executor` 线程池，worker 内先 `collect_manifest` 全库收集（full 审查可达数十秒）再 `run_code_review` 创建 `.fenix/runs/<review_id>.jsonl`。

前端的「运行中」UI（进度卡片渲染 `progress?.running`、按钮禁用）完全绑定 `read_progress` 的 `running` 判据（`core/code_review.py:739`），而该判据要求 run 文件已存在。受理→运行窗口内（tick 延迟 + 池排队 + manifest 收集）`running` 恒 false：卡片不渲染、按钮解禁，唯一兜底是 30s 心跳。且窗口内第二次 POST 可同时通过 running 守卫与信号 O_EXCL 守卫（信号已被消费 unlink）返回 200，随后被 daemon 单飞静默丢弃（`fenixd.py:2342` 只记日志）——假受理。

同页签「立即自动修复」已有完整先例（`add-code-fix-manual-trigger`）：触发后轮询结果回链文件 `code_fix_request_result.json`，`request_created` 时间戳回链防陈旧误读，拒绝/失败一律落结果文件不静默。本 change 把同一模式移植到 code-review 手动触发。

## Goals / Non-Goals

**Goals:**
- 消灭受理窗口的无反馈状态：触发后用户在秒级内得到「已启动 / 被拒（含原因）/ 失败 / 超时兜底」四类明确终态反馈之一
- 窗口内重复触发被显式拒绝（409）而非假受理
- 拒绝/失败不再静默丢信号：daemon 侧所有丢弃分支落结果文件

**Non-Goals:**
- 不改 `read_progress` 的 running 判据本身（终态+stale 口径是另一条已验收链路）
- 不引入 SSE 广播 code-review 事件（回链轮询已覆盖，watcher 事件面保持不动）
- 不做结果文件的历史留存/清理（单文件覆盖写，`requested_at` 回链保证正确性）

## Decisions

### D1. 回链文件契约（对齐 code-fix 先例）

路径 `.fenix/code_review_request_result.json`，原子写（同目录 tmp + `os.replace`），内容：

```json
{"requested_at": "<信号 payload 的 requested_at>", "status": "started|dropped|failed",
 "reason": "<机器可读 slug 或 null>", "message": "<面向用户的中文文案>",
 "finished_at": "<UTC ISO8601>"}
```

- 键名对齐 code-fix 先例风格但用本车道语义：`requested_at`（code-fix 用 `request_created`，因两车道信号 payload 键名不同——code-review 信号 payload 本就写 `requested_at`）
- 单文件覆盖写，不清理；消费端每次消费新信号即覆盖旧结果
- `finished_at` 语义统一为「本条结果写入时刻」（对 `started` 即受理时刻，对 `dropped`/`failed` 即拒绝/失败时刻）——daemon 不在 run 结束时回写结果，结果文件不承载 run 终态；run 是否已启动过由窗口守卫以 review_id epoch 判定（见 D3）

### D2. 三态语义与落盘点位（`fenixd.py:_check_code_review_requests`）

| status | 点位（现有控制流） | reason 示例 |
|--------|--------------------|-------------|
| `dropped` | payload 非法 / hosting_state ∈ {stopped, unmanaged}（现只 warning） | `daemon_not_running` / `daemon_unmanaged` / `invalid_payload` |
| `dropped` | 单飞判定已在跑（现只 info「已有审查在跑」） | `already_running` |
| `started` | `_admin_executor.submit` 成功后 | null |
| `failed` | worker 内 `collect_manifest` 异常 / manifest 为空（现只 info/error） | `manifest_error` / `manifest_empty` |
| `failed` | submit 抛异常（现只 error，需连带既有单飞复位逻辑） | `submit_error` |

落盘函数为独立小工具（写侧原子性集中一处），各分支调用不得改变现有控制流（单飞旗标置位/复位顺序保持不变）。worker 内失败落 `failed` 意味着 worker 也要能写结果——把 `requested_at` 传入闭包即可。

### D3. POST 窗口守卫判据（`_api_code_review_run`）

既有守卫之后、写信号之前追加：

```
若 结果文件存在 且 status == "started"
   且 progress.running == false          （run 尚未开始）
   且 finished_at 距今 ≤ ACK_WINDOW_SECONDS（900s，新鲜度）
   且 progress.review_id 内嵌 epoch ≤ finished_at（受理后尚无新 run 启动过）
→ 409「审查已受理，正在启动（文件收集/排队中），请稍候」code=code_review_ack_pending
```

- 新鲜度必要：run 结束后结果文件仍是 started 且 running=false，不判新鲜会永久锁死触发
- epoch 判据必要（评审修补）：daemon 不在 run 结束时回写结果（worker 在 run 完成后无任何结果文件写入，fenixd.py:2373-2386），`started + running=false` 有二义——「排队收集中」与「已跑完」形态相同；仅凭新鲜度，run 结束后窗口内（900s − run 时长，可逾 10 分钟）的合法重触发会被假 409「正在启动」拒绝，而今日行为是立即放行，属本 change 引入的回归。run_id 形如 `code-review-<epoch>[-<n>]`（`core/code_review.py:728` `_latest_review_run` 同款解析），受理的 run 一旦启动即产生 epoch > finished_at 的 review_id → 放行。误放行终点仍是既有 running 守卫或 daemon 单飞的显式拒绝并落结果，有反馈不留静默（与下条 fail-open 论证同款）
- 超窗口放行后链路自洽：新信号被 daemon 消费 → 单飞拒绝 → 落 `dropped/already_running` → 前端明确反馈，不留静默
- 守卫读结果与 running 判定之间存在竞态（两读之间 run 恰好开始）→ 放行的第二发被 daemon 单飞拒绝并落结果，fail-open 到「有反馈的拒绝」，可接受
- 信号文件 O_EXCL 409 与本守卫并存：前者覆盖「信号未消费」，本守卫覆盖「信号已消费、run 未开始」的空隙

### D4. GET 端点

`GET /api/code-review/run-result?project=<name>` → `dashboard_data.read_code_review_request_result(project_root)`；文件缺失/损坏返回缺省态 `{}` 形态（`requested_at: null, status: null, ...`），MUST NOT 500——完全对齐 `_api_code_review_fix_run_result` 形态。

### D5. 前端受理等待态（QualityTab）

- 新增独立 state `ackPending: boolean` + 哨兵 ref（卸载/切页签/切项目置位，复用 `fixRunPollAbortedRef` 模式）。`ackPending` 只禁用两个审查触发按钮，不并入 `actionPending`（后者连带禁用取消按钮与 fix-run 按钮，语义是「HTTP 请求进行中」）
- `handleTrigger` 流程改为两段等待：
  1. **等结果**：POST 200 后不弹「已受理」toast（现有文案是假承诺），置 `ackPending=true`，1s 间隔轮询 run-result，仅认 `requested_at` 与本次 POST 返回一致的记录，上限 120s；读到 `started` → 进第 2 段；`dropped` → warning 回显 `message`；`failed` → error 回显；超时 → 提示「未收到启动确认，请稍后在进度卡片或 daemon 日志确认」并解禁
  2. **等启动**：收到 started 后 2s 间隔轮询 `loadProgress` 直到 `running=true`（既有卡片与 2s 进度轮询自动接管）或上限 60s（超时提示「已受理但启动较慢」并解禁——run 仍可能稍后开始，既有 30s 心跳兜底）
- 任一段结束（含超时/失败）复位 `ackPending`；卸载/切页签立即停止轮询且不弹 toast
- 期间重复点击被 `ackPending` 禁用直接挡住

### D6. 时间与陈旧性

全链 UTC（`requested_at`/`finished_at` ISO8601 UTC）；新鲜度判定用 dashboard 进程本地钟，dashboard 与 daemon 同机部署，偏差可忽略；即使钟差导致误拒/误放，链路终点都是 daemon 侧落结果文件的显式反馈，无静默路径。

## Risks / Trade-offs

- **[daemon 旧码在飞] 结果文件不产生** → 前端 120s 超时兜底明确提示（部署后需 daemon 重启生效，同既有「生效须 daemon 重启」约定）
- **[排队极慢 >120s]** → 前端超时解禁可再触发；此时 daemon 侧单飞或 POST 窗口守卫（900s 内）给出明确拒绝，不会重复执行
- **[回链轮询增加 GET QPS]** → 仅触发后 120s 窗口内 1s 一次，稳态零开销
- **[双车道守卫语义相似易混]** → POST 现有 `code_review_running` 409 与新增 `code_review_ack_pending` 409 错误码分离，前端分支按错误码判定（对齐 `fbdb437a22a0` 稳定错误码先例）

## Migration Plan

纯增量：新文件、新端点、新守卫、前端交互改造；无数据迁移。上线顺序 = 合并即生效（前端产物需 build，daemon 侧需重启）。

## Open Questions

无（方案已经用户选定：复用 code-fix 回链模式，full 模式）。
