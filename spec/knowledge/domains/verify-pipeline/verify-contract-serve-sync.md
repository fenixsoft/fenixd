# 出题产物契约 serve/ready 段位同步前置校验

<!-- knowledge: capability=verify-contract-serve-sync rev=1
     sources=spec/changes/evo-verify-contract-serve-sync-precheck -->

出题产物（场景集）的场景 kind 需求与验证契约（`.fenix/verify.yaml`）serve/ready 段位之间的同步缺口，在出题轮内的产物写盘点与验收点即以 info 级情报信号前置暴露，实现期即可安排补段，不必等消费期静态门打回再消耗 admin run 代起草与验证时延。

## 规则

**前置校验挂点与命中判据**

- 两个前置挂点：planner-plan 产物落盘点（plan-ready 确认处）与并行出题产物验收点（可解析 + load_scenarios 验收通过后、消费短路前）。两处按产物场景 kind 集调用 serve_missing_for_scenario_kinds 交叉规则，校验契约 serve/ready 段位齐备性。
- 命中条件三条同时成立：kind 集含 api 或 web（需被验证应用可服务的形态）、契约无 serve 段、config.commands.start 无有效兜底（空或占位哨兵）。段位齐备或 kind 集不含 api/web 时零新增信号。
- kind 集按执行 kind 原样统计（缺失 kind 缺省 web），不做应用运行状态探测——可达性归执行期兜底。

**信号语义（info 级一次性）**

- 命中经 verify_contract_missing 通道出单条 info 级信号：只沉淀告警账本、不召唤 Administrator；不阻断产物落盘、不触发 planner replan——出题挂点语境是代起草情报提示，不是验证拦截。
- info 级判定不挂状态机窗口：出题产物挂点由验证流水线派发，spec 可处于 testing 或并行出题时的 implementing，凡写盘/验收挂点命中一律 info（不沿用周期预检的 ready/implementing 窗口判定）。
- info「沉淀不召唤」的落库形态：info 记录以 escalated=True 落库、预先消费「写入即待唤起」语义（摄取循环对 STORED_SIGNAL_TYPES 无 severity 过滤，未 escalated 的 info 记录会被覆写为 major 召唤）；handled 保持 False。
- 同 spec 同缺口一次性：写盘点与验收点跨挂点去重，判据复用 store.has_unhandled_signal(spec, "verify_contract_missing")（持久化随告警账本、daemon 重启不重发、处置后复位允许再次提示）；去重只约束前置挂点自身。

**定向补段情报**

- 信号 evidence 携带 rule_id、scenario_kinds、契约文件路径（`.fenix/verify.yaml`）、缺失段位清单与 commands.start 现值，admin/code-fix 代起草处置可据此直接补段，无需重新考古出题产物。

**fail-open 分层与最后防线**

- 前置校验全程 fail-open：产物缺失/不可解析/kind 集为空 → 零情报放行（验收与执行期门禁各有既有处置，前置不重复拦截）；契约文件缺失或解析失败由扫描器既有 fail-open 承接（api/web kind 集下该形态本身即 serve 缺失命中，照常出情报信号）；任何异常记 WARNING 放行，绝不阻断出题主流程。
- 消费期静态门保留为最后防线且行为不变：进入验证期未补段仍按既有 major 打回 + 召唤 Administrator；消费期门不受前置去重抑制。
- 信号通道 severity 参数化：verify_contract_missing 写入通道默认 major（消费期既有调用点零变化），前置挂点传 info。

**边界**

- 契约代起草职责不动：仍归 admin/code-fix 车道且有起草自证门（`bin/fenix_verify_contract.py`）；前置校验只补情报，不让出题方（planner）代起草契约。

## 代码锚点

- 前置校验入口与信号通道：`core/pm_engine/verification/scenario_gate.py`（preflight_contract_serve_sync；scan_serve_missing_for_kinds 为交叉规则可独立调用入口；serve_missing_findings 为 serve 命中单源筛选；_write_verify_contract_missing severity 参数化）
- 前置挂点：`core/pm_engine/verification/pipeline.py`（planner-plan 产物落盘点与并行产物验收点两处；消费期统一挂点行为不变）
- 交叉规则本体：`core/verify_engine/scenario_static_check.py`（SERVE_MISSING_RULE_ID）
- 场景文件写/读端：`core/verify_engine/scenarios.py`（write_scenarios_array / load_scenarios）
- 守卫测试：`tests/test_contract_kind_serve_precheck.py`

## 溯源

- 2026-11-16 evo-verify-contract-serve-sync-precheck（spec/changes/evo-verify-contract-serve-sync-precheck/） — 新建本能力页：出题产物写盘/验收点前置校验（info 级一次性 + 定向补段情报、不拦截不 replan），信号通道 severity 参数化，消费期门确认最后防线不变（此前 kind 集扩容与契约段位的同步缺口要到实现合并消费期才被打回，4 天三度缺口各耗一次 admin run 代起草）
