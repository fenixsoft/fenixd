# 验证报告：fix-daemon-lifecycle-races

> ⚠️ 本报告由框架于 2026-09-06T05:53:13Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。

## 结论：❌ 未通过（Bug Found）

**状态：bug-found — 12/14 场景通过，2 失败，0 错误（1 个真实产品 Bug）**

14 个场景中 12 个通过、2 个失败。失败的两场景（web-settings-token-verify-redo-budget 与 cli-config-verify-redo-budget-restore）为同一根因的产品缺陷：agents.verify_redo_budget 未进入 core/dashboard/data.py 的配置合并白名单（_AGENTS_MANAGED_SUBKEYS / _deep_merge_managed），Dashboard 保存该配置时被静默丢弃，未持久化落盘。两场景 grep 代码交叉佐证：前端 TokenBudgetPanel.tsx 与核心消费端 state_machine.py 均已实现，唯后端 Dashboard 保存链路遗漏。判定 product-bug（major），验证不通过，需在 data.py 补齐 verify_redo_budget 的合并分支与白名单后重验。

| 指标 | 数量 |
| --- | --- |
| 通过 | 12 |
| 失败 | 2 |
| 错误 | 0 |
| 产品 Bug | 1 |
| 本链增量 Token（输入） | 13.03M |
| 本链增量 Token（输出） | 0.10M |


## 真实产品 Bug

### BUG-01（severity=major）· text_match / json_output（配置持久化断言）

- 关联场景：web-settings-token-verify-redo-budget、cli-config-verify-redo-budget-restore
- 描述：Dashboard 设置页「预算」页签的「重启重验预算」（agents.verify_redo_budget）保存持久化完全失效：用户在输入框输入 4 并点击保存后，输入框值仍为默认值 3，未出现「保存成功」提示；~/.fenix/config.yaml 中亦未落盘该键（persisted=null）——保存被静默丢弃，配置未生效。
- 根因：core/dashboard/data.py 的受管配置合并层缺少 verify_redo_budget：_AGENTS_MANAGED_SUBKEYS 白名单（data.py:3000）与 _deep_merge_managed 的 agents 合并分支（data.py:3371 起）均未包含 verify_redo_budget，导致 POST /api/config 提交的 agents.verify_redo_budget 在合并时被静默丢弃、不写入配置文件。前端 TokenBudgetPanel.tsx（19/27/39/101 行）已实现表单项并提交该键，核心消费端 state_machine.py recover_interrupted（651-700 行）也已完成，唯独 Dashboard 后端保存链路遗漏，实现不完整。
- 证据（场景 web-settings-token-verify-redo-budget 结构化证据，引用）：
  - failed_assertions: [{"type": "text_match", "selector": "#verify_redo_budget", "expected": "4", "actual": "3"}, {"type": "text_contains", "text": "保存成功", "expected": "保存成功后出现「保存成功」提示", "actual": "提示未出现"}]
  - screenshots: ["/root/fenixd/.fenix/verify-progress/fix-daemon-lifecycle-races/screenshots/web-settings-token-verify-redo-budget_assert_fail.png"]
  - first_failed_step: 步骤5: 在「重启重验预算」输入框输入 4 并点击「保存」后，输入框值仍为 3 且无「保存成功」提示——agents.verify_redo_budget 未进入后端配置合并白名单，保存被静默丢弃


## 场景结果

| 场景 | 描述 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- | --- |
| cli-transition-idempotent-pass | 状态机幂等自迁移（state-transition-idempotency）：已处 pushed 终态的 spec 再次 transition(pushed) 返回 True 且不打「Invalid transition」ERROR（INFO Idempotent 日志）；transition_gate 对 old==new 同型幂等返回 True；真实非法迁移 implemented→verified 仍返回 False 并记 ERROR。功能出处：core/state_machine.py:538-548（transition 幂等短路）、:586-596（transition_gate 幂等短路）、~/.history scratch 沙箱隔离运行实例。 | pass | 0/7 | - |
| cli-verify-redo-increment-persist | 重启重验计数递增与持久化（verify-recovery-budget）：testing 中断 spec 经 recover_interrupted 恢复（testing→implemented 重验路径）计数 _verify_redo_count +1 并落盘 STATE.md；新 StateMachine 实例（模拟新 daemon）读到同值（跨重启持久化）；implementing 中断不递增（仅重启恢复递增）；未达阈值不冻结、正常过渡 implemented。功能出处：core/state_machine.py:664-704（recover_interrupted 递增分支 + D3 冻结）、VERIFY_REDO_COUNT_FIELD state_machine.py:89。 | pass | 0/8 | - |
| cli-verify-redo-budget-freeze | 重验超限冻结（verify-recovery-budget 毒 spec 第三次重启触发冻结）：_verify_redo_count=2 的 spec 再重启恢复 → 递增至达阈值 3 → freeze_spec 结构化冻结（status=blocked + frozen=True + error 注明「重启重验超限」），本次启动不再重派 verifier（冻结 spec 保持 blocked，不进入重派路径）。功能出处：core/state_machine.py:684-698（达阈值冻结分支）、freeze_spec；agents.verify_redo_budget 缺省 3（DEFAULT_VERIFY_REDO_BUDGET state_machine.py:92）。 | pass | 0/6 | - |
| cli-verify-redo-unfreeze-clears | 人工解冻恢复并清零（verify-recovery-budget 人工解冻恢复）：超限冻结 spec 执行 unfreeze_spec(status) 后恢复指定状态、frozen 清除、_verify_redo_count 一并清零（人工放行后预算重新起算）。功能出处：core/state_machine.py:474-486（unfreeze_spec 解冻并清零）。 | pass | 0/6 | - |
| cli-terminal-sweep-patch-untracked | 启动终态补写扫描——SIGKILL 遗留 run 补写终态（daemon-drain-integrity）：runs_dir 下尾部无终态事件（result/interrupted/error/cancelled）的 run 文件被追加 {"type": "interrupted", "reason": "startup terminal-state sweep"}。补写不检查遗留进程存活（纯文件扫描，孤儿 claude 进程不阻塞——文件由 daemon 侧转写）。功能出处：core/agent_runner/liveness.py:39-96（sweep_runs_without_terminal_state）、RUN_TERMINAL_EVENT_TYPES liveness.py:42-47；调用时序接入 fenixd.py:289-304。 | pass | 0/4 | - |
| cli-terminal-sweep-terminal-runs-untouched | 启动终态补写扫描——含终态 run 不受影响（daemon-drain-integrity 正常运行不误伤）：尾部含 result/interrupted/error/cancelled 任一终态事件的 run 不被补写；sweep 幂等（重复执行不重复追加）；损坏 JSON 行不阻断扫描；runs 目录缺失返回空。功能出处：core/agent_runner/liveness.py:39-96。 | pass | 0/10 | - |
| cli-supervisor-runtime-write | supervisor SIGKILL 等待窗口自报（daemon-drain-integrity 启动上报等待窗口）：supervisor 启动路径原子覆写 .fenix/supervisor_runtime.json，含 sigkill_wait（= admin.shutdown_drain_seconds+120，drain≤0 时回退 60）与 started_at。功能出处：bin/fenixd_supervisor.py:96-140（_write_supervisor_runtime + _sigkill_wait_seconds）、main() 启动自报 :153-157。 | pass | 0/4 | - |
| cli-drain-consistency-check | drain 窗口一致性自检（daemon-drain-integrity 旧代码 supervisor 被检出 / 一致配置静默通过）：daemon 启动自检在 drain>0 时比对 supervisor_runtime.json——文件缺失（旧代码 supervisor 未上报）→ WARNING + 项目日志提示重启 supervisor；sigkill_wait < drain+120 → WARNING「排水期可能被截断」；started_at 与 daemon 启动漂移超阈值 → WARNING「残留自此前 supervisor 进程」；一致配置静默通过；drain≤0 跳过自检。功能出处：fenixd.py:828-898（_check_supervisor_drain_consistency）、启动接入 :310-320。 | pass | 0/7 | - |
| cli-push-singleflight-double-path | done→pushed 双路径并发单飞（done-push-dedup 双路径并发仅一次 push）：verify 成功后同步直调 + event_bus 事件双路径并发 approve_push → 实例级互斥锁内 check-then-act 原子化，仅第一个流执行 git push main 与 done→pushed 迁移；第二流排队后见 pushed 幂等跳过（返回 True），无双 push、无重复 project log、无 pushed→pushed ERROR。功能出处：core/pm_engine/engine.py:87-96（_push_lock）、:1001-1084（approve_push 全临界区持锁）。 | pass | 0/6 | - |
| cli-push-diff-specs-serialized | 不同 spec 并发 push 串行化（done-push-dedup 串行化不同 spec 的 push）：两个不同 spec 的 approve_push 并发到达经全局 push 锁串行执行，各自仅一次 git push main，推送到 pushed 无竞态。功能出处：core/pm_engine/engine.py:87-96（_push_lock 全局锁，design D5 否决 per-spec 锁）。 | pass | 0/5 | - |
| cli-stale-verdict-discard-zero-dispatch | 在飞 verify 结果状态判据——旧结果静默丢弃零派发（stale-verdict-race-guard 状态被拨回后旧结果静默丢弃 / 被拒结果零派发）：legacy 流水线入口 spec 状态非 testing（stale-result 防护已拨回 implemented）→ 结果按 DEBUG 丢弃（注明当前状态），不执行 verifier 派发、不迁移、不触发 fallback 回退重派整轮 verifier（02:13 事故路径已拆除）。功能出处：core/pm_engine/verification.py:799-808（legacy 入口判据）、:1637-1643、:1728-1737（应用点判据 + 拆除旧 reconcile 重派）。 | pass | 0/7 | - |
| cli-stale-verdict-normal-path-clear-budget | 在飞 verify 结果状态判据——正常路径不受影响 + 验证通过清零（stale-verdict-race-guard 正常结果处理不受影响 / verify-recovery-budget verify 自然通过清零）：spec 处于 testing 时 verifier 正常返回 verified → 结果照常消费 testing→verified 迁移；迁移落定清零点把 _verify_redo_count 归零（与 _verify_fail_rounds 清零点对齐的 legacy 清零点）。功能出处：core/pm_engine/verification.py:799-808（正常路径放行）、:1816（legacy verified 清零点）、dispatch.py:2200 / verification.py:1353（另两处对齐清零点）。 | pass | 0/4 | - |
| web-settings-token-verify-redo-budget | 设置页「预算」页签 TokenBudgetPanel 新增 agents.verify_redo_budget 配置项（重启重验预算）：navigate 到 dashboard 设置页（hash 路由出处 core/dashboard/static/config/config.ts:15 history.hash；设置页路由 core/dashboard/static/src/app.tsx:111；TokenBudgetPanel 在 token 页签渲染 core/dashboard/static/src/pages/settings/index.tsx:196；表单项 name=verify_redo_budget 出自 core/dashboard/static/src/pages/settings/components/TokenBudgetPanel.tsx:99-115；端口默认 8787 core/dashboard/server.py:5——验证实例端口按运行实例实际配置改写），切预算页签后断言「重启重验预算」输入框可见、可编辑、输入 value 正确、保存按钮可点，点击保存走既有配置热更新链路，随后由 cli-config-verify-redo-budget-restore 核对持久化值并恢复环境。 | failed（已修正） | 2/7 | product-bug |
| cli-config-verify-redo-budget-restore | TokenBudgetPanel 保存持久化核对与环境恢复：web 场景在「预算」页签把 verify_redo_budget 输入为 4 并保存（POST /api/config 既有热更新链路，core/dashboard/server.py:1384 _api_config_post → data.py write_config 原子写）——本场景读取用户级配置 ~/.fenix/config.yaml 核对 agents.verify_redo_budget 已持久化为 4，随后移除该行恢复环境（默认值 3 语义不变，config 其余内容逐字节保留）。 验收要点：保存后配置必须真实落盘（task 6.1「保存后经现有配置热更新生效」）；若本场景 persisted 断言失败，说明 `agents.verify_redo_budget` 未进入 core/dashboard/data.py:2921 `_AGENTS_MANAGED_SUBKEYS` 合并白名单（保存被静默丢弃），需在实现侧补齐后再验。 | failed（已修正） | 2/3 | product-bug |


## 断言级豁免清单

以下失败断言被归类为非产品缺陷（不记产品 Bug），逐条列出供人工复核豁免是否掩盖真实缺陷（场景级一句话归因不足以复核）。

无非 product-bug 的被豁免失败断言。

## 本轮场景集变更

当前稳定场景集共 14 个（第 1 轮）。

- 首轮写入 14 个场景

