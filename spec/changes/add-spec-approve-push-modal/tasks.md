# add-spec-approve-push-modal 任务清单

## Deliverables

```yaml
- path: core/dashboard/data.py
  kind: modify
- path: core/dashboard/server.py
  kind: modify
- path: fenixd.py
  kind: modify
- path: core/dashboard/static/src/services/dashboard.ts
  kind: modify
- path: core/dashboard/static/src/pages/projects/components/SpecStatusModal.tsx
  kind: modify
- path: tests/test_spec_approve_push.py
  kind: new
- path: tests/test_dashboard_api.py
  kind: modify
```

## 1. 后端：审批推送请求（data.py）

- [x] 1.1 `core/dashboard/data.py`：新增常量 `APPROVE_PUSH_REQUEST = ".fenix/approve_push_request.json"` 与 `request_spec_approve_push(project_root, spec)`——spec 不在 STATE.md → `{ok: False, found: False}`；status 非 `done` → `{ok: False, terminal: pushed 时幂等文案 / not_done: 其他状态文案}`（error 文案区分 pushed 与非 done）；daemon 存活探测（`from core.fenix_session import is_running`，与 registry.py 同用法）未运行 → `{ok: False, daemon_down: True}`；信号已存在 → `{ok: False, conflict: True}`（对齐 `request_run_cancel` 冲突语义，读既有 created 供返回）；校验通过 → 原子写（tmp+rename + fsync，与 `request_admin_invoke` 同构）`{"spec": spec, "source": "dashboard", "created": <ISO8601 UTC>}`，返回 `{ok: True, found: True, file, created, error: None}`
- [x] 1.2 `request_spec_approve_push` docstring 注明：状态推进由 daemon 侧 `approve_push` 的 `transition(pushed)` 完成，本函数只写信号不触碰 STATE.md；退避/失败由既有 `_handle_push_failure` 链路接管

## 2. 后端：API 路由（server.py）

- [x] 2.1 `core/dashboard/server.py`：新增 `POST /api/spec-approve-push?project=<name>&spec=<name>` 路由与 `_api_spec_approve_push` handler（模式对齐 `_api_spec_promote`）——project/spec 缺失 → 404；`daemon_down` → 409「daemon 未运行，请先启动 daemon」；`conflict` → 409「已有进行中的审批推送请求」；`terminal` → 403「SPEC 已推送（pushed），无需审批」；`not_done` → 403「仅 done 状态可审批推送（当前 <status>）」；成功 → 200 `{ok: true, project, spec, created}`；模块 docstring 端点清单同步

## 3. daemon：信号消费（fenixd.py）

- [x] 3.1 `fenixd.py`：新增 `_check_approve_push_requests`——与 `_check_cancel_requests` 完全同构（损坏 JSON 删除防卡死 / 先读后删 / 缺 spec 记 WARNING）；pm_engine 为 None → 记 WARNING 丢弃；消费调 `self.pm_engine.approve_push(spec)`，返回 True 记 INFO（含 spec），返回 False 记 WARNING（注明退避重放与 recovery 兜底覆盖，不重试）；docstring 引用 design D3
- [x] 3.2 主循环挂载：`_check_scheduling_kick_requests` 之后按同模式 try/except 挂载（1s 粒度，异常记 error 不中断主循环），注释对齐既有三个信号扫描的格式

## 4. 前端：服务层与弹窗区块

- [x] 4.1 `core/dashboard/static/src/services/dashboard.ts`：新增 `ApprovePushResult` 接口与 `approveSpecPush(project, spec)`（模式对齐 `promoteSpec`）
- [x] 4.2 `core/dashboard/static/src/pages/projects/components/SpecStatusModal.tsx`：done 态（`summary.status === 'done'`，pushed 不渲染）在归档区块之前新增「审批推送」区块——说明文案（daemon 执行推送：main 先行+分支尽力，成功推 pushed，失败走退避重试超限升级 push_failed 告警）+「审批推送」按钮；点击经 `appModal.confirm` 二次确认（文案含 SPEC 名称与推送目标 origin，对齐 handleArchive 交互模式），确认后调 `approveSpecPush`：成功 `message.success('已提交推送，daemon 执行中')` + onDone；失败 message.error 展示后端 error 文案（含 daemon 未运行/冲突/非 done 三态）；模块头部注释同步区块清单（四区块→五区块）

## 5. 测试

- [x] 5.1 `tests/test_spec_approve_push.py`（新建）：`request_spec_approve_push` 全分支（404 not found / 非 done 拒绝含 pushed 与 ready 两态文案区分 / daemon 未运行 daemon_down / 冲突 conflict 读既有 created / 成功写入 payload 三键断言 + tmp 残留无）；`_check_approve_push_requests` 消费（成功调 approve_push 且文件已删 / approve_push 返回 False 记 WARNING / 损坏 JSON 删除 / 缺 spec 删除+WARNING / 先读后删：unlink 失败下轮再试）；夹具对齐 test_dashboard_api 的 make_project（done 态条目需自建）
- [x] 5.2 `tests/test_dashboard_api.py`：`/api/spec-approve-push` HTTP 全分支——200 成功、404（project/spec）、403 非 done（ready）与 403 pushed 文案区分、409 daemon_down、409 conflict；响应体键断言对齐既有 budget/promote API 测试风格
- [x] 5.3 幂等与竞态核对：连续两次调用（中间不消费）第二次 409；spec 已 pushed 后消费信号 → approve_push 幂等返回 True 无 pushed→pushed ERROR（断言日志无 Invalid transition）

## 6. 验证与收尾

- [x] 6.1 全量跑新增与相关既有测试（test_dashboard_api / test_dashboard_data / test_run_cancel 如有信号同构断言 / test_spec_scheduling 回归），零失败
- [x] 6.2 前端构建通过（`core/dashboard/static` 下 build/type-check 零错误）；dist 不提交
- [x] 6.3 场景核对：对照 specs/spec-approve-push-modal 全部 Scenario 逐条自验

## 验证修复（原地打回第 1 轮）

- [ ] 先复核失败有效性：逐条核对 `spec/changes/add-spec-approve-push-modal/verification-report.md` 中失败场景的期望断言（状态字面量/选择器/前置数据）与产品实际行为是否相符——断言与产品不符属场景缺陷，修场景文件；确属产品行为不符才修产品代码
- [ ] 按复核结论修复：场景缺陷改场景文件，真实产品 Bug 改产品代码
- [ ] 修复后重跑验证确认通过
