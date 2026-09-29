<!-- knowledge: capability=admin-invoke-record-dialog rev=1 sources=spec/archive/2026-09-04-add-admin-invoke-dialog -->

# 呼叫管理员处置过程弹窗

呼叫 Admin 后自动弹出的处置过程弹窗：实时展示 Administrator run 的 Agent 消息流，而非只留痕结果。

## 现行规则

- SPEC 行右键「呼叫 Admin 介入」后，呼叫请求返回成功（2xx）或 409（该 SPEC 已有处置进行中）时自动打开处置过程弹窗；其他错误（网络异常、5xx）只显示错误提示，不弹窗。
- 弹窗主体展示该 SPEC 对应 Administrator run 的处置过程输出（Agent 消息事件时间轴）：经该 SPEC 的 `admin_run_id` 定位 run（可经 `GET /api/admin-activities?spec=<name>` 解析 pending/final disposition 记录），复用既有 run watch 机制（watch/unwatch + `run_events` SSE 增量推送）实时渲染。
- Administrator 尚未启动时显示「等待 Administrator 开始处置」等待态；run 启动（pending disposition 落盘、`.fenix/admin_alerts.json` 变更触发广播）后自动切换为实时输出视图并注册 run watch，无需用户刷新。
- 处置过程中新 Agent 消息经 `run_events` SSE 增量推送实时出现在时间轴中；处置完成后弹窗保留完整过程输出，顶部状态行显示最终处置状态（处置中/已完成/已中断）。
- 用户可随时关闭弹窗：关闭即取消该 run 的 watch 订阅，后台处置与记录落盘继续正常进行，关闭后新事件不产生无效更新或报错。

## 溯源

- [2026-09-04 add-admin-invoke-dialog](spec/archive/2026-09-04-add-admin-invoke-dialog/) — 呼叫后弹窗从「处置记录卡片」定为「处置过程实时输出」：run 定位、等待态自动切换、SSE 增量渲染与关闭不中断后台处置
