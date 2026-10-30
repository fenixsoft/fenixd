## Context

验证执行期校验：_ensure_app_reachable（core/pm_engine/verification/serving.py:902，报错文案 :1104）由 pipeline.py:2208「阶段2.5 应用可达性自愈」调用，serve 缺失报「场景集含 api、cli、web 场景但无 serve 配置」。出题期形式上有检查、实质不覆盖：scenario_gate.py:847 _run_contract_static_check → core/verify_engine/scenario_static_check.py:624 scan_contract，但 :654 早退（serve 为 None 即返回空 findings），三条规则全在 serve.cmd 存在时才生效；挂点只挂 pipeline.py:3059 新鲜 planner-plan 验收通过路径（注释明言冻结复用路径不经过此处）；消费期 selfcheck_contract_light（pipeline.py:3153-3155）同样只在 serve 段存在时校验。信号侧：core/admin_monitor.py:2949-2952 _preprobe_signal_satisfied 对 verify_contract_missing 只验「契约可解析」——2026-10-10 03:22:24Z 三条该信号被批量 pre-probe auto-resolve（fenixd.log:13403-13405），起草诉求未满足却闭环，最终靠指纹 742cfaea 升级才打破。事件链：fenixd.log:13361/13372/13387 三轮 fail-fast（03:21:03→03:21:38Z 恰 35 秒、0 场景执行），告警 dd4d6742f92d（verify_env_blocked，admin_alerts.json:2328），契约补课提交 2842c29（12:12:08 +0800，+88 行 serve/ready），blocked 约 50.5 分钟；admin-global-1791602544 3831.5s/156 轮/75 工具调用（fenixd.log:13462）。场景集：verify-progress/pack2-live-stream-player/test_scenarios.json 25 场景 = cli 23 + api 1 + web 1。config.yaml commands.start 至今仍为占位 echo（.fenix/config.yaml:95）——实际修复走 serve 段路线。前作：2026-09-18-add-verify-preflight-gate（scan_contract 机制落地，16/16 通过）、2026-10-07-evo-add-verify-contract-preflight（_detect_verify_contract_unresolved 模板态前置检出，11/11 通过，只认文件不可解析）。

## Goals / Non-Goals

- Goals：kind 集与契约能力不匹配在出题产物消费期被打回；冻结/并行路径不再绕过静态检查；能力未补的 verify_contract_missing 不再被错误 auto-resolve。
- Non-Goals：不改 R2 infra 退款归类；不改 serve/ready 探测实现；不做契约自动起草；不动验证执行期 _ensure_app_reachable（执行期兜底保留）。

## Decisions

- D1 扩展既有 scan_contract 规则表而非新建预检：serve-None 早退（scenario_static_check.py:654）只对新交叉规则放开——serve 缺失且 kind 集含 api/web 且 commands.start 无有效兜底（空或占位哨兵 `echo 'No start command configured yet'`，判定口径与 serving.py:1098-1099 旧行为完全一致）时产出 serve 缺失 finding，其余三条规则维持早退（避免对无 serve 契约的历史项目误报既有类别）。能力谓词（serve 段 OR 非占位 start）与本 SPEC 前置探测（D3）及 verify_contract.py:97「serve 段（或 commands.start 兜底）必须有效」的契约文档语义三方同口径：serve 缺失但 start 非占位的项目形态执行期本就靠 commands.start 旧行为兜底（serving.py:1097「无契约路径……直接回退 commands.start」），静态检查若单看 serve 段会把该存量可用形态误打回，且与 D3 谓词自相矛盾（同一状态一处打回一处放行）。
- D2 kind 集来源：静态检查入参补场景 kind 集合（从出题产物/冻结场景文件按执行 kind 原样统计），不做应用运行状态探测——那是执行期 _ensure_app_reachable 的职责，两层各司其职。
- D3 preprobe 谓词从「可解析」改为「能力覆盖」：serve 段存在或 start 非占位取 OR（todo 原文写 AND——本次实际修复恰是保留 start 占位、只加 serve 段，按 AND 会把合法修复态判为不合格），且须覆盖在途场景 kind 需求。
- D4 todo 次级建议（无 serve 配置从 infra 退款分类分拆）不入本 SPEC：env 阻塞属 infra 是 escalation.py:611-620 的明文设计（evo-infra-failure-budget-exempt R2），本窗口零实际损失，分类颗粒度复核另议。

## Risks / Trade-offs

- 误打回风险：kind 统计若计入 mock/跳过类场景会误报——按执行 kind 原样统计，与验证执行期判定口径一致；纯 cli 形态显式白名单化（不报）。
- 冻结场景路径补挂载后，存量冻结场景集可能集中暴露契约缺口：暴露的正是本 SPEC 要拦的确定性配置缺口，一次打回补契约优于每轮验证期 env-block。
- preprobe 收紧会少量增加 administrator 唤起（契约可解析但缺能力形态）：这正是本意图，该形态本就该唤起起草而非静默闭环。