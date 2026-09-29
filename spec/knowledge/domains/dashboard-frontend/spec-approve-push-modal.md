<!-- knowledge: capability=spec-approve-push-modal rev=1 sources=spec/archive/2026-09-17-add-spec-approve-push-modal -->

# 审批推送弹窗

done SPEC 的人工审批推送入口：弹窗区块 + 信号文件 API + daemon 主循环消费的推送闭环。

## 现行规则

- 弹窗区块：修改状态弹窗对状态为 `done` 的 SPEC 在归档区块之前渲染「审批推送」区块——说明文案（审批后由 daemon 执行推送，main 先行 + feature 分支尽力，成功后 SPEC 推进到 pushed 终态；推送失败走既有退避重试，超限升级 push_failed 人工告警）与「审批推送」确认按钮；按钮点击后弹出二次确认（Modal.confirm，文案含 SPEC 名称与推送目标远端 origin），确认后调用审批推送 API。状态为 `pushed` 或任何非 done 状态不渲染该区块（已推送无待审批语义）。
- 信号 API：`POST /api/spec-approve-push?project=<name>&spec=<name>` 按序校验——project 不存在或 spec 不在项目 STATE.md 返回 404；spec 状态非 `done` 返回 403（pushed 幂等无操作与其他状态非法的文案区分）；daemon 未运行（复用 `core.fenix_session.is_running` 存活探测）返回 409「daemon 未运行，请先启动 daemon」（信号无人消费，前置拦截）；已存在未消费的 `.fenix/approve_push_request.json` 返回 409「已有进行中的审批推送请求」（不覆盖，对齐 cancel_run/scheduling_kick 冲突语义）；校验通过后原子写入（tmp+rename）payload `{"spec": <name>, "source": "dashboard", "created": <ISO8601 UTC>}`，返回 `{ok: true, created}`。
- daemon 消费：daemon 主循环（1s 粒度）扫描 `.fenix/approve_push_request.json`——损坏 JSON 删除信号文件防卡死、本轮跳过；先读后删，删除失败（被并发消费）本轮跳过下轮再试；payload 缺 spec 记 WARNING 并忽略；pm_engine 未初始化记 WARNING 并丢弃；消费时调用 `pm_engine.approve_push(spec)`——单飞锁、main 先行 + 分支尽力、SHA 去重、退避、归档收口、project log 全部沿用既有实现，不新增任何推送语义；`approve_push` 返回 False（非 done、退避期内、推送失败）记 WARNING 不重试（退避重放与 recovery 兜底已覆盖；已 pushed 幂等返回 True 不重复推送）。
- 边界行为：成功推送后 SPEC 推进为 pushed、project log 记录推送事件；信号文件存在但 daemon 已停止时信号滞留且不阻塞其他调度，daemon 下次启动后主循环照常拾取消费。

## 溯源

- [2026-09-17 add-spec-approve-push-modal](spec/archive/2026-09-17-add-spec-approve-push-modal/) — 建立审批推送弹窗区块、/api/spec-approve-push 信号 API（五道校验与原子写入）与 daemon 主循环信号消费闭环
