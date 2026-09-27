# 被测服务不可达快速失败
<!-- knowledge: capability=verify-unreachable-failfast rev=1 sources=spec/archive/2026-09-18-add-verify-unreachable-failfast -->

可达性自愈失败即整轮 fail-fast：不跑场景、不产报告、直接落 blocked 升级环境处置。

## 现行规则

- 短路条件：验证阶段 2.5 中 `_ensure_app_reachable` 返回 `(reachable=False, user_blocked=False)` 时，立即结束本轮验证——不重读场景文件、不创建/运行 `VerifyEngine`（场景执行数=0）、不退回 plan 重排；调用 `_escalate_env_blocked` 落 blocked（自动呼叫 Administrator，连续 2 轮冻结转人工）并自本验证轮 return。
- 证据与产物：升级的 violations/evidence 使用 `reach_note`（内嵌 boot.log 尾部）；短路路径不产生 `verification-report.md` / `report.json`（与消费期轻量自证短路同语义）。
- 契约缺失子案不重写信号：场景集含 web/api 但无 serve 配置时（`_ensure_app_reachable` 内部已自写一条 `verify_contract_missing` 信号并返回 note），短路仅调用 `_escalate_env_blocked`，不追加第二条信号，告警 store 中该 spec 的该信号保持一条。
- prepare 失败同款短路：契约 prepare 步骤执行失败返回 `(False, False, note)` 时与探针超时同款处理——0 场景、blocked、升级失败原因，不继续跑场景。
- 可达时行为不变：`reachable=True`（或纯 cli 场景集 / 无 navigate 依赖等恒放行路径）时短路点不触发，验证流程照常——重读场景、运行 `VerifyEngine`、走判定链，无新增失败类型。
- user_blocked 守卫：短路条件显式包含 `not user_blocked`；`user_blocked=True`（需用户参与而无法自动验证的预留判定位）时不进入短路分支、不落 blocked，为「收验证码/登录」类场景保留不误杀的通道。

## 溯源

- 2026-09-18 add-verify-unreachable-failfast — 新增不可达即整轮短路 fail-fast（此前不可达仍走场景执行与判定链，空跑整轮验证后才得结论），升级证据内嵌 boot.log 尾部直达 admin
