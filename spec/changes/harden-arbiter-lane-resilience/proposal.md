# Proposal — arbiter 车道故障分级复位与前置自检

## 问题陈述

arbiter（与 repair）裁决车道今日（2026-11-09）上午因基础设施故障整体挂死约 8 小时，期间所有触发它的阻塞信号全部升级人工；故障修复后，已 dead-man 的签名依然永久人工。两处框架缺口：

1. **失败不分级**：`ArbiterEngine._on_run_failed`（core/pm_engine/arbiter.py:1290-1362）对 run 失败只做连败计数，`count >= max_consecutive_failures` 或预算耗尽即 `_deadmanned.add(sig)` + 台账 kind=dead-man（:1305/:1318）。基础设施秒挂（0 rounds，无 API 往返，单 run ≈0.2s）与真实判断失败不可区分地累积同一计数器。
2. **dead-man 无复位**：台账 dead-man 是「跨重启永久单次例外」（:383-388 持久读、:425-436 升级判定、:1592 注释「不复位」），无解除 API；`_ledger_sigs`（:626）只读不写。环境修复后签名无法恢复自主处置资格。
3. **无前置自检**：车道 CLI/凭据可用性没有启动探测。dispatch 车道已有「派发前置 harness 可达性自检与 PATH 自愈」范式（知识域 dispatch-scheduling），arbiter/repair 车道没有对等物，故障只能靠阻塞堆积后倒查。

## 证据锚点（2026-11-09 事故现场，cloud-phone 项目）

- `.fenix/arbiter_ledger.jsonl`：本地 09:01–09:08（UTC 01:01–01:08）四签名 `failed→dead-man→recurrence-escalation→chain-escalated` 四连，`arbiter_rulings=0`；failure_reason 两层：
  - `dsh: skipping profile bundle "fenix-dsh-bundle": Plugin ...@0.1.0 incompatible with dsh 0.2.2-rc.1`
  - `dsh: MISSING_CREDENTIAL: llm-deepseek: no API key for provider route "deepseek-official"`
- fenixd.log:2258/2306/2312：`latency: run arbiter-...: 0 rounds（无 API 往返样本）`；单 run 0.002s（budget.elapsed_s，wallclock 1800s 预算几乎全额剩余）。
- 前日首败（2026-11-08T08:07Z，ledger 首条）：`[Errno 2] No such file or directory: 'claude'`——同一车道、同类基础设施故障。
- 修复对照：config.yaml 2026-11-09 17:07:35 显式模型链（bigmodel-cn/glm-5.3-flash）落地后，17:29 p2p::impl_budget_exhausted 车道正常产裁决包——车道能力无问题，问题全在环境面与（环境恢复后的）资格恢复缺失。

## 目标

- R1 基础设施故障分级：0 rounds + 环境指纹的 run 失败不计入 dead-man 连败计数，走独立的 infra 失败通道（冷却重试 + 台账 kind=infra-failed）。
- R2 infra 资格复位：车道健康探针成功（启动/周期/派发前置）即清除 infra 计数与 infra 停机标记，签名恢复自主处置资格；judgment dead-man 语义不变、无复位。
- R3 前置自检：daemon 启动与裁决派发前探测车道健康（CLI 可达 + 凭据路由可解析），不健康时跳过本次裁决派发并告警（单发），fail-open 不阻塞 daemon。
- R4 全量回归绿 + 知识页回填。

## 非目标

- 缺口③升级件自环回派（arbiter todo 自理）。
- 推送/git 凭据面（fix-push-credential-env-and-retry-rearm 已承接）。
- 改变 judgment dead-man 的永久语义或台账历史条目（append-only 纪律，arbiter.py:180-184）。

## 影响面

core/pm_engine/arbiter.py（失败分级 + infra 计数/复位）、core/agent_runner/（新增前置探针模块，复用 provider_circuit/latency 既有判定面）、fenixd.py（启动与周期接线）、tests/test_arbiter_lane_resilience.py（新增）。台账格式向后兼容（新 kind 不破坏既有读侧）。
