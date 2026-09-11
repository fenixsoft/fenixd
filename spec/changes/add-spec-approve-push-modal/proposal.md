# add-spec-approve-push-modal

## Why

Fenix 框架中 done→pushed 是唯一的人工审批门（`gates.approve_mode: manual`），目前只能通过 CLI `/fenix-approve` skill 完成：用户须打开终端、跑脚本列 SPEC、逐个确认推送。Web Dashboard 已收敛了归档/冻结/晋升/预算等全部状态操作（add-spec-status-modal-budget 的「修改状态」弹窗），唯独缺审批推送入口——用户离开终端即无法完成闭环，SPEC 滞留 done 阻塞后续派发。

## What Changes

- **修改状态弹窗新增「审批推送」区块**：SPEC 状态为 done 时渲染（pushed 已终态不渲染），展示推送说明与确认按钮；确认后发起审批请求，成功提示「已提交推送，daemon 执行中」并刷新列表。
- **新增审批推送文件信号**：`.fenix/approve_push_request.json`，dashboard API 原子写入（tmp+rename），payload `{spec, source: "dashboard", created}`；已有未消费信号 → 409 冲突；spec 非 done → 403 拒绝。
- **daemon 主循环消费信号**：与 `_check_cancel_requests` / `_check_scheduling_kick_requests` 同构——1s 粒度扫描、损坏 JSON 删除防卡死、先读后删；消费时调 `pm_engine.approve_push(spec)`，完整复用其既有语义（单飞锁、main 先行+分支尽力、SHA 去重、退避重试、归档收口、project log），不新增任何推送语义。
- **daemon 未运行时前置拦截**：dashboard API 检测 daemon 存活（复用 `is_running` 探测），未运行 → 409 并提示先启动 daemon（信号无人消费，避免静默滞留）。
- **零新状态语义**：状态推进仍由 `approve_push` 内部 `transition(pushed)` 完成；退避/失败仍走既有 error 写回与 push_failed 信号链路。

## Capabilities

### New Capabilities

- `spec-approve-push-modal`: SPEC「修改状态」弹窗的审批推送区块——done 态渲染、确认发起、API 文件信号、daemon 消费执行 approve_push、冲突与存活前置校验。

### Modified Capabilities

<!-- 无：spec/specs/ 当前无活跃 specs；spec-status-actions-modal 能力（add-spec-status-modal-budget）仍在活跃 change 区未归档，本能力只新增第五区块，不修改其既有需求行为 -->

## Impact

- **前端**：`core/dashboard/static/src/pages/projects/components/SpecStatusModal.tsx`（新增审批推送区块）；`core/dashboard/static/src/services/dashboard.ts`（新增 `approveSpecPush`）。
- **后端 API**：`core/dashboard/server.py`（新增 `POST /api/spec-approve-push` 路由 + 模块 docstring 端点清单同步）；`core/dashboard/data.py`（新增 `request_spec_approve_push`：spec 存在性/终态校验、daemon 存活探测、信号原子写）。
- **daemon**：`fenixd.py`（新增 `_check_approve_push_requests` 主循环消费 + 主循环挂载）。
- **运行时文件**：`.fenix/approve_push_request.json`（消费后删除，gitignored 运行时产物，不提交）。
- **测试**：`tests/test_dashboard_api.py` 既有模式扩展（API 全分支）+ 新增信号消费测试（损坏 JSON/先读后删/spec 已删/非 done 拒绝/成功路径 approve_push 调用）。
- **不涉及**：`approve_push` / `_auto_approve` / 退避与 push_failed 语义本身、auto 模式自动推送链路、CLI `/fenix-approve` skill。
