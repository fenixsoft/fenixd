# FAQ 与故障排查

本章按「现象 → 根因 → 处置」整理 Fenix 常见问题。每条都来自真实运行中可能遇到的场景，并在结尾交叉链接到对应的专题篇。

## 1. SPEC 卡在 ready 不派发

**现象**：SPEC 状态长期为 ready，没有 implementer run 启动。

**根因**（按概率排序）：有更高优先级 SPEC 占用并发额度（`agents.max_concurrent`）；达到每日运行上限 `agents.daily_run_limit`；达到实现尝试预算（`_impl_run_budget_used >= impl_run_budget`）；SPEC 处于派发锁退避期（`pm.dispatch_backoff_schedule`，error 记录 backoff until）；或者 daemon 根本没有运行。

**处置**：先用 `/fenix-status` 与 Dashboard 概览页确认 daemon 健康；再查 `.fenix/logs/fenixd-<year>.log` 的 dispatch 相关记录，以及 STATE.md 中该 spec 的 `error` 与 `_impl_run_budget_used` 字段。若确认是预算耗尽，人工评估后调整 `agents.impl_run_budget`（约 30 秒热更新）并 reset spec。

相关：[调度与治理规则](06-governance.md#三类预算)、[SPEC 生命周期与状态机](03-lifecycle.md#blocked阻塞)

## 2. SPEC 反复打回（ready↔implementing 空转）

**现象**：SPEC 在 ready 和 implementing 之间反复横跳，无明显进展。

**根因**：派发后 run 秒挂（启动即失败），进入冷却期后又被立即重派，形成空转回路。

**处置**：查看最新 impl run jsonl 的首条事件，秒挂的原因通常是环境或命令错误；再看 Admin Monitor 是否报了 `flapping` 或 `repeated_failures` 信号；修复根因（如损坏的 commands.test/build）后 reset spec。

## 3. 烧钱快（token 消耗异常）

**现象**：Dashboard token 面板数字涨得快，或收到 80%/100% 预算告警。

**根因**：常见有三类：验证场景反复失败导致修复循环多轮重验；卡住的 run 在超时监督续期（extension）中空转；多个同根 fix 并行派生。

**处置**：先把 `agents.timeout_supervision.max_extensions` 调小或置 0，压缩续期上限；再检查是否陷入修复循环，看 `.fenix/verify-progress/<spec>/` 的重验轮数与失败截图；紧急止损可直接在 Dashboard 冻结该 SPEC。注意预算告警本身不会自动冻结 SPEC，处置由人工决策（[配置参考](09-config.md#agents)）。

## 4. merge 冲突反复失败

**现象**：SPEC 在 merge-back 阶段反复失败，最终 blocked。

**根因**：与主分支或其它 worktree 产生 git 冲突，连续失败达到 `merge_breaker_threshold`（默认 2）后熔断。

**处置**：按提示清理 git 状态（stash / 分支冲突），手动解决冲突后 reset spec 重新 merge；同时查 `merge_streak` 告警（critical 级）的证据。

相关：[调度与治理规则](06-governance.md#merge-修复通道与熔断)

## 5. 验证反复失败（fix 修不好）

**现象**：验证报告持续 fail，fix 分支已派生多层（fix-fix-…）。

**根因**：要么根因没有定位准（验证报告证据不足），要么环境问题导致伪失败。

**处置**：先排除伪失败：构建失败/应用不可达不会判 bug-found，确认不是环境问题再继续；然后看失败截图 `.fenix/verify-progress/<spec>/screenshots/` 与 report.json 的 assertion message 定位根因。修复循环有三轮熔断，若触发了 `family_explosion`（fix 族谱超限）则转人工；同时人工审视 verify.yaml 契约（BASE_URL 铁律是否正常注入）。

相关：[验证体系](05-verification.md)、[文件与数据地图](10-artifacts.md)

## 6. 告警横幅频响（升级告警反复弹）

**现象**：Dashboard 顶部横幅同一 SPEC 反复出现告警。

**根因**：`admin.escalation_cooldown_minutes`（默认 60 分钟）冷却内会抑制重复告警；频响通常意味着困境真实存在，自动解决之后又复发了。

**处置**：查 admin_alerts.json 的处置记录，看自动解决的依据；再对照信号类型到治理篇查对应规则（[调度与治理规则](06-governance.md)）。

## 7. daemon 反复重启 / 断档

**现象**：SPEC 进度倒退、中断状态被回退 ready。

**根因**：daemon 由 supervisor 托管（`fenixd_supervisor.py`），异常退出会被自动拉起；重启后 `implementing`/`testing` 回退 ready。

**处置**：查 daemon 日志 `.fenix/logs/fenixd-<year>.log` 尾部确认崩溃原因；必要时 `/fenix-setup` 重建环境，或用 `/fenix-dashboard` 跨项目统一管理。需要说明的是，重启恢复是设计行为（[03 生命周期](03-lifecycle.md#daemon-重启中断恢复)），不是数据丢失。

## 8. 希望人工接管某个 SPEC

**现象**：想暂停自动化，自己手工处理，或让 Administrator 介入。

**处置**：冻结用 Dashboard SPEC 行「冻结」或 `/fenix-freeze`，SPEC 进入 blocked + frozen 标记，自动链全部剥离；处理完后用「解冻」恢复原状态。若只想让 Administrator 诊断一次，用 SPEC 行「呼叫 Admin」，它会写 admin_invoke_request.json，daemon 下一轮拾取后唤起。

相关：[SPEC 生命周期与状态机](03-lifecycle.md#冻结与解冻)、[Dashboard 使用指南](08-dashboard.md)

## 9. 配置改了不生效

**现象**：改了 `.fenix/config.yaml` 的键，行为没有变化。

**根因**：改的是需重启生效的键（对照表见 [配置参考](09-config.md)）；或 `agents.timeout_supervision` 与顶层 `timeout_supervision` 同时配置（顶层只是回退开关）；或被「模板值与代码缺省不一致」误导（[模板值与代码缺省不一致](09-config.md#模板值与代码缺省不一致)）。

**处置**：按键标注的生效方式决定是否重启 daemon；判断实际生效值以项目 config.yaml 为准。

## 10. 找不到某个文件/目录

**现象**：排查时需要某个产物（报告/日志/截图），但找不到。

**处置**：对照 [文件与数据地图](10-artifacts.md#出问题去哪查对照表) 逐项核对。`.fenix/` 内的文件都可以安全重新生成，缺失不一定代表异常。

## 11. 配了 hook 但没触发 / 收到 hook_failure 告警

**现象**：SPEC 状态变化后配置的 hook 没有执行；或运维记录页出现 `hook_failure` 告警。

**根因**：hook 动作失败不重试也不去重（git 失败、webhook 不可达、shell 非零退出/超时），每次失败都直接告警。没触发则常见于：手工编辑 config.yaml 漏了 `id`（缺失 id 的条目不执行且无任何痕迹）、`events` 拼写不在十状态枚举内、`enabled: false`（审计记 skipped）、保存后未满 30 秒热更新窗口。

**处置**：先查 `.fenix/hook_audit.jsonl`（或 Dashboard Hook 页签「最近执行」）按 spec 找记录：status=skipped 是被停用；status=failure 是动作报错，detail 含输出摘要；完全没有记录则是匹配阶段未命中（核对 id 与 events）。修正配置后 ≤30 秒热更新自动生效。完整键参考见[配置参考](09-config.md#hooks)。

## 12. 配了 Provider 但 Agent 没走它（仍打到默认网关）

**现象**：`agents.models` 给某角色分配了 Provider，但从时间轴的 `model@provider` 标记或账单看，请求仍打到 cc-switch 等默认网关。

**根因**：常见四类：角色键配错或用了未知角色键（未知键降级跳过并 ERROR 告警）；Provider 名拼错（`llm.providers` 注册表中无此 `name`，候选被跳过）；候选链上所有候选都处于切换冷却或熔断中（chain_exhausted，本次派发直接失败、不消耗 spec 重试，冷却窗口过后自动恢复）；或配置保存后未过 30 秒热更新窗口。

**处置**：先在 SPEC 详情时间轴看该 run 实际驱动的 `model@provider` 确认通道；再逐字符核对 `agents.models.<角色>.provider` 与 `llm.providers[].name` 是否一致。注意 Agent 通道与用户会话是隔离的（[LLM Provider 隔离](02-concepts.md#llm-provider-隔离)）：Agent 是否走 Provider 只由 `agents.models` 分配决定，改用户 `~/.claude/settings.json` 不会影响已分配的 Agent。

## 相关文档

- [核心概念与架构](02-concepts.md)、[SPEC 生命周期与状态机](03-lifecycle.md)
- [验证体系](05-verification.md)、[调度与治理规则](06-governance.md)
- [配置参考](09-config.md)、[文件与数据地图](10-artifacts.md)
