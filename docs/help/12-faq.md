# FAQ 与故障排查

本章按「现象 → 根因 → 处置」整理 Fenix 常见问题。每条都来自真实运行中可能遇到的场景，并在结尾交叉链接到对应的专题篇。

## 1. SPEC 卡在 ready 不派发

**现象**：SPEC 状态长期为 ready，没有 implementer run 启动。

**根因**（按概率排序）：有更高优先级 SPEC 占用并发额度（`agents.max_concurrent`；调度默认严格优先级，开启 `pm.dispatch.aging` 后等待中的 SPEC 逐级放宽降档，高优先级不再严格垄断并发槽）；达到每日运行上限 `agents.daily_run_limit`；达到实现尝试预算（`_impl_run_budget_used >= impl_run_budget`）；SPEC 处于派发锁退避期（`pm.dispatch_backoff_schedule`，error 记录 backoff until）；或者 daemon 根本没有运行。

**处置**：先用 `/fenix-status` 与 Dashboard 概览页确认 daemon 健康；再查 `.fenix/logs/fenixd.log` 的 dispatch 相关记录，以及 STATE.md 中该 spec 的 `error` 与 `_impl_run_budget_used` 字段。若确认是预算耗尽，人工评估后调整 `agents.impl_run_budget`（约 30 秒热更新）并 reset spec。

相关：[调度与治理规则](06-governance.md#三类预算)、[生命周期与状态机](03-lifecycle.md#blocked阻塞)

## 2. SPEC 反复打回（ready↔implementing 空转）

**现象**：SPEC 在 ready 和 implementing 之间反复横跳，无明显进展。

**根因**：派发后 run 秒挂（启动即失败），进入冷却期后又被立即重派，形成空转回路。

**处置**：查看最新 impl run jsonl 的首条事件，秒挂的原因通常是环境或命令错误；再看 Admin Monitor 是否报了 `flapping` 或 `repeated_failures` 信号；修复根因（如损坏的 commands.test/build）后 reset spec。

## 3. 烧钱快（token 消耗异常）

**现象**：Dashboard token 面板数字涨得快，或收到 80%/100% 预算告警。

**根因**：常见有三类：验证场景反复失败导致修复循环多轮重验；卡住的 run 在超时监督续期（extension）中空转；多个同根 fix 并行派生。

**处置**：先把 `agents.timeout_supervision.max_extensions` 调小或置 0，压缩续期上限；再检查是否陷入修复循环，看 `.fenix/verify-progress/<spec>/` 的重验轮数与失败截图；若怀疑 run 在低效空转，可开启 `agents.run_stall_budget_*`（缺省关闭）——观测窗内持续停滞的 run 会被主动终止并写 `[run-stall-budget]` 前缀错误，而不是靠超时续期硬拖（见[调度与治理规则](06-governance.md#run-止损run-stall-budget)）；紧急止损可直接在 Dashboard 冻结该 SPEC。注意预算告警本身不会自动冻结 SPEC，处置由人工决策（[配置参考](09-config.md#agents)）。

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

**处置**：查 daemon 日志 `.fenix/logs/fenixd.log` 尾部确认崩溃原因；必要时 `/fenix-setup` 重建环境，或用 `/fenix-dashboard` 跨项目统一管理。需要说明的是，重启恢复是设计行为（[03 生命周期](03-lifecycle.md#daemon-重启中断恢复)），不是数据丢失。

## 8. 项目在跑但 restart_request 永不生效（概览显示「运行中·未托管」）

**现象**：daemon 进程在运行，但 `touch .fenix/restart_request` 后 daemon 不重启，restart_request 文件一直残留；Dashboard 概览页该项目卡片显示「运行中·未托管」；审批推送同样无响应。

**根因**：项目处于 `unmanaged` 托管态——有 daemon 进程但无 supervisor（`fenixd_supervisor.py`）。supervisor 是 restart_request 的唯一消费方，裸 daemon 不检查该文件，请求信号永久滞留并锁死该项目后续全部审批推送（单槽位占位）。典型场景：存量项目未经 `/fenix-setup` 托管、或 supervisor 崩溃后无人重启。

**处置**：经 Dashboard 项目卡片「更多」→「安装托管」一键执行「停止裸 daemon → 经 supervisor 启动」；或重新运行 `/fenix-setup`。安装托管后 supervisor 启动即会看到并消费残留的 restart_request，daemon 换上新代码，restart_failed 告警也可关闭。

相关：[调度与治理规则](06-governance.md#重启协议)、[Dashboard 操作手册](08-dashboard.md#托管态徽标与安装托管)

## 9. 希望人工接管某个 SPEC

**现象**：想暂停自动化，自己手工处理，或让 Administrator 介入。

**处置**：冻结用 Dashboard SPEC 行「冻结」或 `/fenix-freeze`，SPEC 进入 blocked + frozen 标记，自动链全部剥离；处理完后用「解冻」恢复原状态。若只想让 Administrator 诊断一次，用 SPEC 行「呼叫 Admin」，它会写 admin_invoke_request.json，daemon 下一轮拾取后唤起。

相关：[生命周期与状态机](03-lifecycle.md#冻结与解冻)、[Dashboard 操作手册](08-dashboard.md)

## 10. 配置改了不生效

**现象**：改了 `.fenix/config.yaml` 的键，行为没有变化。

**根因**：改的是需重启生效的键（对照表见 [配置参考](09-config.md)）；或 `agents.timeout_supervision` 与顶层 `timeout_supervision` 同时配置（顶层只是回退开关）；或被「模板值与代码缺省不一致」误导（[模板值与代码缺省不一致](09-config.md#模板值与代码缺省不一致)）。

**处置**：按键标注的生效方式决定是否重启 daemon；判断实际生效值以项目 config.yaml 为准。

## 11. 找不到某个文件/目录

**现象**：排查时需要某个产物（报告/日志/截图），但找不到。

**处置**：对照 [文件与数据地图](10-artifacts.md#出问题去哪查对照表) 逐项核对。`.fenix/` 内的文件都可以安全重新生成，缺失不一定代表异常。

## 12. 配了 hook 但没触发 / 收到 hook_failure 告警

**现象**：SPEC 状态变化后配置的 hook 没有执行；或运维记录页出现 `hook_failure` 告警。

**根因**：hook 动作失败不重试也不去重（git 失败、webhook 不可达、shell 非零退出/超时），每次失败都直接告警。没触发则常见于：手工编辑 config.yaml 漏了 `id`（缺失 id 的条目不执行且无任何痕迹）、`events` 拼写不在 11 状态枚举（含 `all-done` 伪事件）内、`enabled: false`（审计记 skipped）、保存后未满 30 秒热更新窗口。

**处置**：先查 `.fenix/hook_audit.jsonl`（或 Dashboard Hook 页签「最近执行」）按 spec 找记录：status=skipped 是被停用；status=failure 是动作报错，detail 含输出摘要；完全没有记录则是匹配阶段未命中（核对 id 与 events）。修正配置后 ≤30 秒热更新自动生效。完整键参考见[配置参考](09-config.md#hooks)。

## 13. 配了 Provider 但 Agent 没走它（仍打到默认网关）

**现象**：`agents.models` 给某角色分配了 Provider，但从时间轴的 `model@provider` 标记或账单看，请求仍打到 cc-switch 等默认网关。

**根因**：常见四类：角色键配错或用了未知角色键（未知键降级跳过并 ERROR 告警）；Provider 名拼错（`llm.providers` 注册表中无此 `name`，候选被跳过）；候选链上所有候选都处于切换冷却或熔断中（chain_exhausted，本次派发直接失败、不消耗 spec 重试，冷却窗口过后自动恢复）；或配置保存后未过 30 秒热更新窗口。

**处置**：先在 SPEC 详情时间轴看该 run 实际驱动的 `model@provider` 确认通道；再逐字符核对 `agents.models.<角色>.provider` 与 `llm.providers[].name` 是否一致。注意 Agent 通道与用户会话是隔离的（[LLM Provider 隔离](02-concepts.md#llm-provider-隔离)）：Agent 是否走 Provider 只由 `agents.models` 分配决定，改用户 `~/.claude/settings.json` 不会影响已分配的 Agent。

## 14. 模型链上有被拒模型（unrecognized_model / model-chain-unavailable）

**现象**：日志反复出现 WARNING `Unrecognized model rejected by provider ... provider='<名>' model='<模型名>'`；或 spec error / Dashboard 告警含 `[model-chain-unavailable] 全链模型不可用：provider '<名>' 拒绝模型 '<模型名>'`——文本直接点名了要摘的 provider 与模型名。

**根因**：`agents.models.<角色>.provider` 候选链上存在 provider 明确拒绝的模型名，属确定性失败，与网关负载无关——重试、等待、重派都不会自愈。框架只做 run 内沿链 failover（每个被拒条目仍会让当次 run 白烧一次进程启动 + 一条失败告警），**不会**自动修改配置；链尾无更多候选时 run 以 `[model-chain-unavailable]` 归因收场，派发器不重派、不增 retry、不翻转状态机，spec 原状等人工摘除。

**处置**：模型链定义在**运行时** `.fenix/config.yaml` 的 `agents.models`（模板只有注释示例，不含活动链）。人工删除被拒条目（daemon 无需重启，每次派发都重新解析链）：多角色共享同一条目时每个引用处都要摘；摘后核对各链剩余条目 ≥3（不足时先补入其它可用组合再摘）。随后清除 spec 的 `error` 字段触发重派，并在 `.fenix/todo.md` 登记摘除跟进提醒，避免数周后链纵深缩水无人知晓。摘除条目的恢复条件（全部满足才加回）：provider 侧确认支持该模型名 + 手工探针调用成功无 `unrecognized_model` + 加回后首个 run 不再出现该 WARNING；模型名变更（升级到新版本名）不算「同一模型恢复」，按新条目重新探针。

相关：[配置参考](09-config.md#agents)

## 15. 吞吐与排水调优（并发槽位 / merge-back 预检 / 重启排水）

以下三项都只改运行时 `.fenix/config.yaml`，约 30 秒热更新生效，无需重启 daemon。

**想调派发并发**：`agents.max_concurrent`，代码缺省 5；未写该键即用缺省。上调前自查两件事：`worktree.base_dir` 所在盘剩余空间（每个并发实现 run 一个独立 worktree，约占 N × 仓库大小）与模型网关的并发配额。多个 run 同时到收尾回归检查点时由 full-suite.lock 主机级互斥锁串行，上调并发只增加锁排队时长、不改变互斥语义。回退即改回原值或删除该键，正在飞的 run 不受影响。

**merge-back 被拦截升级**：merge-back 发起前预检「主树 WIP 脏文件集 ∩ 分支触碰文件集」，交集非空时不发起 merge，发人工升级告警（含交集文件清单与两侧来源）。处置：人工清理主树 WIP（`git add/commit` 或 `git stash push`）后 ready 重派该 spec。判据是保守的（不同 hunk 本可自动合并的重叠也会拦），确认无真实冲突时可临时开逃生门 `worktree.merge_precheck_bypass: true` 直接 merge，用完改回 false。策略键 `worktree.mergeback_wip_overlap_policy`：缺省 `escalate`（拦截升级人工）；`auto` 保留旧自动收纳语义（重叠改动 stash 收纳、merge 后恢复）；`block` 与 escalate 同为拦截。

**规划性重启把在飞 run 直接杀了 / 排水为 0**：restart（`.fenix/restart_request` 触发）的排水窗口由 `agents.run_drain_max_seconds` 管（代码缺省 60 秒），且须 ≤ `admin.shutdown_drain_seconds`（shutdown>0 时；两者均显式配置且违反时配置加载直接报错）。restart 流程：停新派发 → 向每个在飞 run 广播一次 checkpoint 旗标（促使实现侧尽快落盘收尾）→ 等至多排水窗口 → 超窗 run 强杀并保全分支续做（排水集合还覆盖 ocr 等登记车道进程）。排水起止看 daemon 日志 `Drain: planned restart ...` / `Drain finished after ...` 两行；出现 WARNING `Drain: planned restart but drain window is 0s` 说明 run_drain 被显式置 0，属配置误置（在飞工作将不经排水直接终止），调回正值即可。存量部署若 `admin.shutdown_drain_seconds: 0`（旧版本会把重启排水清零、直接 SIGTERM 在飞 run），人工调为正值即可先行恢复排水。

相关：[配置参考](09-config.md)、[调度与治理规则](06-governance.md)

## 16. code-fix 不派批 / 周期审查 run 僵死

**现象**：周期审查 run 长时间不收尾（典型形态：ocr scan 阶段网络僵死，数小时仅几十秒 CPU）；或 code-fix 台账迟迟不派新批。

**根因**：两者相互独立。code-fix 批派发的守卫链（enabled / 自身单飞 / 无 open 条目 / WIP 预检 / 回归契约）**不含**「审查 run 在飞」——审查在飞不挡派批，这是结构性解耦并有回归测试钉住（`tests/test_codefix_review_decoupling.py`）；不派批最常见的原因就是台账没有 open 条目（checkpoint 如实空转）或被 WIP/回归守卫拦截。审查 run 侧的问题是没有自动收走机制时，僵死占道上界无限制，产物滞留在 `out-<run_id>.jsonl` 不入台账。

**处置**：审查 run 疑似僵死时，admin monitor 看门狗按「产物 mtime（含分片）+ 进程 CPU 时间」双判据判定——任一有进展即重置计时，双停持续 `admin.review_stall_minutes`（缺省 30，正整数）自动取消该 run，run 收尾后既有急救落账路径自动把滞留 findings 转正入台账，`review_stall_watchdog` 告警留痕；人工取消同样触发急救落账。看门狗误杀代价 = 急救落账后下轮重审（upsert 按指纹幂等，已完整落盘的产物不丢），项目页「代码审查」分面手动再触发一次即可；判别误杀对照告警 evidence 里的 mtime/cpu_seconds 与实际值，读数与事实不符先怀疑巡检粒度再调大阈值。阈值权衡：调小（如 15）僵死收走更快，但慢 IO/长网络等待的正常 run 误杀率上升；调大（如 60）接近零误杀，占道上界随之放大。

相关：[日志体系](11-logs.md)

## 相关文档

- [核心概念与架构](02-concepts.md)、[生命周期与状态机](03-lifecycle.md)
- [验证体系](05-verification.md)、[调度与治理规则](06-governance.md)
- [配置参考](09-config.md)、[文件与数据地图](10-artifacts.md)
