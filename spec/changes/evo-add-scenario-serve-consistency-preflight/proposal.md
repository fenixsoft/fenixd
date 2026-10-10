## Why

2026-10-10 pack2-live-stream-player 首轮验证：场景集含 api、cli、web 三类（test_scenarios.json 25 场景 = cli 23 + api 1 + web 1），但 .fenix/verify.yaml 是上一纯 CLI spec cimbar-airgap-transfer 遗留、无 serve 段——首轮 35 秒内 3 轮 fail-fast（0 场景执行），spec blocked 约 50.5 分钟等 administrator 起草契约（提交 2842c29，+88 行 serve/ready 段），预算豁免还把退款记到已完成实现工作约 2.5 小时前的 impl run 上（fenixd.log:13362，幂等跳过再记 2 条 :13375/:13384）。代码层三处互证缺口：契约静态检查 scan_contract 在 serve 缺失时直接空返回（core/verify_engine/scenario_static_check.py:654），「场景 kind 集 ⊆ serve 能力」交叉校验全库不存在；挂点只覆盖新鲜出题验收路径（core/pm_engine/verification/pipeline.py:3059），冻结复用/并行产物路径从未执行（本 spec 全日志零条契约静态检查日志、无 contract_findings.json，对照组 spec 均有）；前置探测对 verify_contract_missing 只验「契约可解析」即免唤起（core/admin_monitor.py:2949-2952），本轮 3 条信号被错误 auto-resolve（fenixd.log:13403-13405）、循环靠指纹 742cfaea 升级才打破。归档前作 2026-09-18-add-verify-preflight-gate 与 2026-10-07-evo-add-verify-contract-preflight 已建机制但均不覆盖本形态。2026-10-02 cimbar 契约首建 26 分钟与本次 51 分钟同构——「全 cli 故 serve 全省」的当时合理决策成了下一个 spec 的陷阱。

## What Changes

1. 静态检查补交叉规则：scan_contract 入参补场景 kind 集合，serve 段缺失（serve 为 None）且 kind 集含 api/web 时产出 serve 缺失 finding——须解除 :654 serve-None 早退对该规则的屏蔽（serve 缺失时既有三条规则维持早退，避免对历史纯 CLI 契约误报）。
2. 挂载补全：契约静态检查挂进冻结场景复用与并行出题产物消费路径（现仅新鲜出题验收路径挂载），任一路径产物都过同一检查。
3. 前置探测收紧：verify_contract_missing 的 pre-probe 满足判定从「契约可解析」收紧为「serve 段存在或 commands.start 非占位（OR），且能力可覆盖在途场景 kind 需求」，能力缺口未补齐不 auto-resolve。
4. 兜底：纯 cli 场景 + 无 serve 契约维持合法（cimbar-airgap-transfer 历史形态不回归）。

## Out of Scope

- 不动「env 阻塞属 infra」的 R2 退款归类（core/pm_engine/escalation.py:611-620 明文设计决策，本窗口零实际损失；确定性配置缺口 vs 瞬态 infra 的分类分拆另议）。
- 不改 verify.yaml 契约格式与 serve/ready 探测实现（core/pm_engine/verification/serving.py）。
- 不做契约自动起草（仍由 administrator 起草，预检只负责出题期打回）。