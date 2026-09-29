<!-- knowledge: capability=delete-stop-inflight-agents rev=1 sources=spec/archive/2026-09-25-add-freeze-stop-inflight-agents -->

# 项目删除先停在跑 Agent

删除 SPEC 前先终止其名下全部在跑 agent 并等待终态，再执行软删除；API 异步受理，前端反馈停止计数。

## 现行规则

- 先停后删：删除存在在跑 run 的 SPEC 时，MUST 先请求终止其名下全部在跑 run（归属判定用全等 `run_spec_part(run_id) == spec`，覆盖全部 agent 前缀），再在有界窗口内等待落终态（每 run 宽限与 `AGENT_TERMINATE_GRACE_SECONDS` 同源，另有总上限），终态齐备后执行既有软删除（STATE 条目移除 + `spec/changes/<name>/` 移入 archive）。
- 超时不删除：等待超时仍有 run 未落终态时，返回明确失败并附未终止 run 列表；run 仍可能写盘时 MUST NOT 移动其 spec 目录，不产生半删状态。
- 无在跑 run 时保持既有同步软删除语义，不引入额外等待。
- API 异步受理：`POST /api/spec-delete` 在该 SPEC 有在跑 agent 时写删除请求文件信号（`.fenix/spec_delete_request.json`，含 `spec`/`source`/`created`，tmp+rename 原子写），立即返回受理结果（含待停止 agent 计数），请求线程不阻塞等待终止完成。
- 受理前置校验：daemon 非 `managed` 托管态 → 409 明确拒绝（信号无人消费，比静默滞留更可诊断）；已存在未消费的删除信号 → 409 冲突，不覆盖既有信号。
- 信号消费：daemon 主循环消费删除信号——停止该 spec 全部在跑 run → 有界等待终态 → 调软删除；信号文件先读后删（删除失败下轮再试），损坏 JSON 直接删除防卡死。
- 前端反馈：删除确认弹窗与受理后提示展示待停止 agent 计数；收到异步受理结果后提示「正在停止 N 个进行中的 agent」并轮询刷新，直至该 SPEC 从列表消失；无在跑 agent 时 MUST NOT 展示此类提示。

## 溯源

- [2026-09-25 add-freeze-stop-inflight-agents](spec/archive/2026-09-25-add-freeze-stop-inflight-agents/) — 新增本能力：删除从「120 秒内活跃 run 直接拒绝（409）」升级为先停后删、API 异步受理（托管态校验 + 信号消费）与前端停止计数反馈
