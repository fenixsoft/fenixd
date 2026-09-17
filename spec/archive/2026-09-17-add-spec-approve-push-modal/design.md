# add-spec-approve-push-modal 设计

## Context

done→pushed 是 Fenix 框架唯一的人工审批门（`gates.approve_mode: manual` 默认）。推送核心逻辑全部收敛在 `PMEngine.approve_push`（core/pm_engine/engine.py:1321）：实例级 `_push_lock` 单飞锁（fix-daemon-lifecycle-races D5）保证「status 重读 → git push → transition(pushed)」全临界区原子化，main 先行+分支尽力+SHA 去重（D1/D2）、指数退避（D3）、归档收口（archive-auto-commit）均已就位。

Dashboard 是独立进程（`bin/fenix_dashboard.py` serve 模式），**不持有 pm_engine 实例**——`approve_push` 依赖的 `_push_lock`、`state_machine`、退避重试计数全部活在 daemon 进程内。跨进程只能走文件信号：`.fenix/admin_invoke_request.json`（手动唤起 Admin）、`.fenix/cancel_run_request.json`（run 取消）、`.fenix/scheduling_kick_request.json`（清空定时即派发）三个成熟先例，均为「dashboard 原子写 → daemon 主循环 1s 粒度扫描 → 读取→删除→执行」。

修改状态弹窗（SpecStatusModal.tsx）按状态条件渲染四区块（归档/冻结/晋升/预算），done 态目前只有归档区块。

## Goals / Non-Goals

**Goals**
- 用户在 Web Dashboard 完成 done→pushed 审批，闭环不离开浏览器
- 推送执行完全复用 `approve_push` 既有语义，零双轨实现
- 与既有三个文件信号同构的消费模式，维护成本最低

**Non-Goals**
- 不改 `approve_push` / `_auto_approve` / 退避 / push_failed 信号语义
- 不做 CLI `/fenix-approve` skill 的功能替代（二者共存，Web 端是入口增强）
- 不做批量审批（一次一个 spec；多 spec 待推送时逐个操作）
- 不改 auto 模式自动推送链路

## Decisions

### D1: 跨进程执行走文件信号，dashboard 不直接推送

**选择**：dashboard API 校验通过后原子写 `.fenix/approve_push_request.json`，daemon 主循环消费并调 `pm_engine.approve_push(spec)`。

**备选**：dashboard server 进程内直接 `git push` + `transition(pushed)`（fenix-approve skill 的简化语义）。

**理由**：直接推送是双轨实现——绕过 `_push_lock` 单飞锁会重新引入 fix-daemon-lifecycle-races D5 消除的双 push/重复 project log/pushed→pushed ERROR 竞态；绕过退避计数会与 daemon 侧重试互相干扰；且 dashboard 进程没有归档收口。历史上状态双轨并行产生过「解冻后半死态」事故（freeze 双轨，data.py:291 docstring 记录）。文件信号是本仓库三次验证过的同构模式。

### D2: daemon 未运行时 API 前置 409 拦截

**选择**：`request_spec_approve_push` 写信号前用 `core.fenix_session.is_running` 探测 daemon 存活，未运行直接 409。

**理由**：信号无人消费时静默滞留，用户以为审批已发起、实际什么都没发生——比明确报错更糟。admin_invoke/cancel_run 无此探测（它们的场景 daemon 必在运行），审批推送的触发时机（SPEC 刚 done，用户回来看）恰是「daemon 可能没启动」的高发场景。探测是只读的 `/proc` 检查，成本可忽略。

### D3: 消费失败不重试，退避与 recovery 兜底

**选择**：`approve_push` 返回 False 时记 WARNING 结束，消费侧不重试。

**理由**：False 的三种来源各有既有兜底——非 done（幂等拒绝，重试无意义）、退避期内（`_is_push_backoffed`，重放由 recovery full_scan 覆盖）、推送失败（`_handle_push_failure` 已写回退避标记或升级 push_failed 信号）。消费侧重试反而绕过退避节奏。

### D4: 信号 payload 极简 `{spec, source, created}`

**选择**：不携带额外参数（如推送目标 ref、是否跳过归档）。

**理由**：`approve_push` 无可注入参数，全部行为由配置与 STATE 驱动。payload 字段越多越容易与 daemon 侧实现漂移。source 字段留 dashboard/project log 可溯源。

### D5: 前端区块置于归档区块之前（done 态区块顺序：审批推送 → 归档）

**理由**：done 态用户的首要意图是审批推送（闭环动作），归档是推送后的次要动作。其余状态不变（非终态：冻结+预算；drafted：晋升）。

## Risks / Trade-offs

- [信号滞留：daemon 恰在写入与消费之间被停] → D2 前置拦截覆盖主场景；滞留信号在 daemon 下次启动时照常消费（approve_push 幂等），不阻塞调度。消费前 spec 被人工迁移到非 done → approve_push 拒绝，信号已删，无重试风暴。
- [并发审批同一 spec：双开弹窗连点] → 文件级冲突（第二写 409）+ daemon 侧 `_push_lock` + approve_push 幂等跳过三道防线。
- [daemon 版本旧不认识新信号文件] → 与「部署新 dashboard + 旧 daemon」的组合只在升级窗口出现；信号滞留无害（见上），升级完成后自动消费。
- [审批推送 long-running（git push 最长 120s）阻塞主循环] → `_check_approve_push_requests` 同步调用 approve_push 与 `_check_scheduling_kick_requests` 内 `_process_queue` 同级；git push 120s 超时上限可接受（scheduling_kick 的派发同样是重操作）。若实测阻塞不可接受，后续 SPEC 再移入 worker 池（与 admin 处置同模式），本期不做。

## Migration Plan

纯增量：新信号文件、新 API 端点、新弹窗区块、daemon 主循环新扫描项。无 schema 迁移、无配置项新增（复用 `gates.approve_mode` 语义：manual 模式下本入口是正常门禁；auto 模式下 done SPEC 会被 daemon 自动推送，本入口对残留 done SPEC 是人工兜底，与 CLI 语义一致）。回滚 = 还原四个文件，无残留状态。
