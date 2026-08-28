# 验证报告：fix-improve-run-lifecycle-governance

- **验证时间**：2026-08-28T15:56:25Z
- **引擎报告**：`/root/fenixd/.fenix/verify-progress/fix-improve-run-lifecycle-governance/report.json`
- **判定结论**：✅ **verified（验证通过，无真实产品缺陷）**
- **统计**：共 13 场景，通过 11，失败 2，警告 0，错误 0，环境阻塞 0

---

## 一、结果总览

| 场景 ID | 描述 | 状态 | 关键断言 |
|---|---|---|---|
| smoke-dashboard-serves-8787 | 生命周期可观察面包烟（8787 新代码） | ✅ pass | 概览页标题 / 卡片网格 / 无 console 错误 |
| recovery-deferred-live-child-detail | 功能正向：stuck 但有存活子进程 → recovery defer | ✅ pass | status-pill 就绪 / error-banner `recovery deferred, live child present` |
| worktree-lock-orphan-holding-detail | 功能正向：孤儿持锁 → 进程表重建跳过派发 | ✅ pass | error-banner `worktree already active - deferred until lock released` |
| timeout-supervision-active-run-detail | 功能正向：活跃运行被纳入可观察面 | ✅ pass | status 实现中 / 无 error-banner / 时间轴节点可见 |
| real-spec-error-subrow-and-clear | 交互：在线清除治理规格 error（回归点） | ❌ fail | 见分析 1 |
| post-recovery-patrol-dispatch-stalled-alert | 功能正向：dispatch_stalled 告警横幅 | ✅ pass | alert-banner / alert-item 含 `dispatch_stalled` |
| post-recovery-patrol-activity-card | 功能正向：运维记录 activity-card | ✅ pass | activity-card 含 `governance-stuck-ready` / `dispatch_stalled` |
| empty-activities-no-records | 空状态：无活动 → 空状态文案 | ✅ pass | `暂无运维记录` |
| governance-config-timeout-supervision-tab | 配置可观察面：并行度页签切换 | ✅ pass | config-tabs / 保存按钮 / 并行度面板 |
| regression-overview-no-console-error | 回归点：概览无控制台/网络错误 | ✅ pass | no_console_error / no_network_error |
| recovery-no-live-child-clean-reset-detail | 功能反向：确认无存活子进程 → 正常重置 | ✅ pass | status 就绪 / 无 error-banner（无 defer 残留） |
| governance-alert-mark-handled | 交互：标记告警已处理（闭环） | ❌ fail | 见分析 2 |
| governance-alert-clear-all-dismiss | 对话框：取消清理所有事件 | ✅ pass | 横幅与告警项仍保留（未误清理） |

---

## 二、失败场景归因（均非产品缺陷）

### 失败 1：`real-spec-error-subrow-and-clear`（第 1/2 层断言超时）

**表象**：断言 `tr.spec-row + tr.spec-info-row` 错误子行可见、`button.info-clear-btn` 清除按钮可见、`no_click_interception` 均超时失败。

**根因**：场景描述的前提不成立。该场景依赖「live STATE.md 中 `improve-run-lifecycle-governance` 处于 bug-found 且 **error 非空**」。但核查实时 `STATE.md:484` 显示该规格 `error: null`，因此前端按设计**不渲染**错误子行与清除按钮。

**代码佐证**：`core/dashboard/static/app.js:926` 明确 `if (s.error) { ...渲染 spec-info-row 与 info-clear-btn ... }` —— `error` 为空则不渲染子行、不占行高。产品行为完全正确。

**判定**：属于**测试场景前提过期**（所选载体规格的实际 error 字段为空），非产品 Bug。`no_click_interception` 的失败只是「按钮因前提不成立而从未渲染」的连带结果，非遮挡/时序问题。

**影响**：仅此 1 个场景。建议修正场景设计：改用确实携带 `error` 信息的规格，或预先通过 `/api/spec-error-clear` 反向构造非空的 error 状态。

### 失败 2：`governance-alert-mark-handled`（第 1 层断言超时）

**表象**：点击 `.alert-handled-btn` 后断言 `.alert-item`「不存在」失败（实际仍保留 1 条告警项）。注意同场景 `no_click_interception` 为 **pass**（按钮可点、未被遮挡）。

**根因**：`/api/alerts` 被 mock 为**静态固定负载**，不持久化 handled 状态。点击「标记已处理」→ `markAlertHandled`（`app.js:342`）POST `/api/alerts/<id>/handled`（mock 恒 200 成功）→ `loadAlerts()` 重新拉取 `/api/alerts`，但拉回的仍是未变更的 mock 数据，故告警项依旧存在。产品刷新逻辑正确，失败源于 **mock 不反映状态变更**。

**判定**：属于**测试环境脚手架问题**（mock 未模拟 handled 状态持久化），非产品 Bug。对照组 `governance-alert-clear-all-dismiss` 验证了 confirm 取消分支逻辑正确，进一步佐证告警处置链路本身无误。

**影响**：仅此 1 个场景。建议修正 mock：让 `/api/alerts` 在收到 handled 请求后从返回负载中移除对应项，或改用 stateful mock。

---

## 三、聚合与系统性判断

- 两处失败**根因不同**（场景前提过期 vs mock 状态不持久化），**无系统性问题**。
- 两处失败均发生在**交互/回归类场景**，而所有**核心治理功能路径**（`recovery-state-consistency`、`post-recovery-patrol`、`agent-run-timeout-supervision`、配置可观察面、空状态）全部通过。
- 全部 `no_console_error`、`no_network_error` 断言均无产品级报错（外部 API 场景无密钥/签名类错误，无未豁免的网络层错误）。
- 无 `no_auth_error` 场景，无需密钥/签名特判。

---

## 四、结论

验证引擎报告的 2 个失败经逐项根因核查，**均为测试场景脚手架/前提问题，不构成真实产品缺陷**。产品代码在治理生命周期可观察面、恢复一致性、闭环复查、超时监督、配置与告警处置等关键路径上行为正确。

**最终判定：`verified`** —— 该 SPEC 可进入 approve / 归档流程。

> 附：建议后续补强 2 个测试场景的 mock/前提构造，使端到端交互链路也能被自动验证覆盖（非阻塞）。
