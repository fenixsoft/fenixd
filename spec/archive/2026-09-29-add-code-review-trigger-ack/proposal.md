## Why

Dashboard 代码审查页签手动触发后存在「受理→运行」异步窗口：POST 只写文件信号即返回「已受理」，daemon 经 1s 主循环拾取 + 线程池排队 + `collect_manifest` 全库文件收集（full 审查轻松超过 30s）后才创建 run 文件；窗口内 `progress.running` 恒 false，前端卡片不渲染、按钮可重复点击，唯一兜底是 30s 心跳——用户不知道任务是否开始、可能重复提交，刷新页面才看到进度卡片。附带后端假受理缺陷：窗口内第二次 POST 能同时通过 running 守卫与信号文件 O_EXCL 守卫返回 200「已受理」，但被 daemon 单飞静默丢弃（只记日志），用户得到假确认。

## What Changes

- daemon 消费 code-review 触发信号后，把判定结果原子写入回链文件 `.fenix/code_review_request_result.json`（`requested_at` 回链 + `status: started|dropped|failed` 三态 + 面向用户的中文 `message`）；单飞拒绝、hosting_state 守卫拒绝、worker 投递失败、manifest 为空等今日只记日志的分支 MUST 全部落结果文件，不再静默丢信号（对齐 `add-code-fix-manual-trigger` 结果回链先例）
- 新增只读端点 `GET /api/code-review/run-result?project=<name>` 返回回链文件内容（缺失返回缺省态，MUST NOT 500）
- `POST /api/code-review/run` 增加受理窗口守卫：读回链结果，daemon 已受理（started）且 run 尚未进入 running 时返回 409「已受理正在启动」，消灭窗口内假受理
- 前端 QualityTab 触发审查后轮询 run-result（带超时上限），按 `requested_at` 回链匹配本次触发，按三态分派反馈：started → 提示已启动并短暂轮询 progress 至 `running=true` 让既有进度卡片接管；dropped/failed → 明确回显拒绝/失败原因；超时 → 「请稍后在进度卡片或 daemon 日志确认」类提示
- 受理等待期间两个审查按钮 SHALL 保持禁用（独立于既有 actionPending 的受理等待态），消灭「提示已提交但按钮仍可点、卡片迟迟不出现」的无反馈窗口

## Capabilities

### New Capabilities
- `code-review-trigger-ack`：code-review 手动触发的受理结果回链（daemon 写侧三态落盘 + GET 端点 + POST 窗口守卫 + 前端受理等待态与分派反馈）

### Modified Capabilities

## Impact

- `fenixd.py`：`_check_code_review_requests` 消费端（落结果文件，含单飞拒绝/守卫拒绝/投递失败分支）
- `core/code_review.py`：新增回链结果读取函数（读侧缺省态）
- `core/dashboard/data/code_review.py`：dashboard 数据层读封装
- `core/dashboard/routes/code_review_routes.py`：GET run-result 端点 + POST 窗口守卫
- `core/dashboard/static/src/services/dashboard.ts`：前端 API 封装
- `core/dashboard/static/src/pages/projects/components/QualityTab.tsx`：触发交互改造（受理等待态、轮询分派、按钮门控）
- `tests/test_code_review.py`：回链写侧/读侧/窗口守卫单测
