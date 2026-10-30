# 验证契约前置预检与 serve 一致性静态检查

<!-- knowledge: capability=verify-contract-preflight rev=2
     sources=spec/archive/2026-10-07-evo-add-verify-contract-preflight,spec/archive/2026-10-30-evo-add-scenario-serve-consistency-preflight -->

验证契约（`.fenix/verify.yaml`）的两类确定性缺口——模板态挂着从未裁决、场景 kind 需求超出契约 serve/start 能力——在实现期巡检与出题产物消费期被前置检出，打回补契约或唤起 Administrator 起草，而非推迟到验证执行期以「应用不可达」fail-fast 空转暴露。

## 规则

**模板态前置巡检（admin_monitor 周期检测器）**

- 触发窗口为 ready/implementing：项目存在该状态的 spec，且 `.fenix/verify.yaml` 存在但 yaml 解析不产生顶层映射（全注释模板、语法损坏、空文件均属此形态）时，写 `verify_contract_missing` 信号。testing 及之后不写——该形态由验证消费期轻量自证 fail-fast 与其信号通道负责，前置窗口与消费窗口互斥不双发。
- 文件缺失不触发：`.fenix/verify.yaml` 不存在是「无契约回退」的合法形态，前置预检只治理「模板态文件挂着从未裁决」，不把无契约项目卷入起草强制流、不扩大触发面。
- 有效契约不触发：可解析为顶层映射（含实质 prepare/regression 或 serve 段）即视为已裁决，不写任何契约信号。
- 项目级单例信号：同项目多个 ready/implementing spec 命中时只产出一条信号（spec 字段取首个命中 spec）。契约是项目级产物（一个项目一份 verify.yaml），既有节流按 (spec, signal_type) 判定、对不同 spec 不互斥，按 spec 数量产信号会把唤起放大 N 倍。
- 处置收尾语义随窗口：前置场景不复位 spec 状态——触发时可能有活跃实现 run，机械复位 ready 会把进行中的实现打回重做、与活跃 run 收尾竞态；前置起草落位即可，spec 推进到验证消费点时经契约 mtime 门直接放行。
- 起草质量门不前移：前置触发只提前起草时机，草稿仍须过三段自证（prepare 执行成功、serve 可探活、ready 探针通过）全通才落位生效，有效契约一律不碰。
- 落点单源：只读判定 `contract_file_unresolvable(project_root)` 收在 `core/verify_contract.py`，内部复用既有 loader 单次读取，以「文件存在且解析为 None」为真、文件缺失为假，不引入第二套解析口径；检测器挂 admin_monitor 周期巡检 `_detect` 汇总，检测器自身异常 fail-open（不阻断其余检测器、不产信号）。

**服务能力谓词（三方同口径）**

- 「契约具备服务能力」的统一谓词：serve 段存在，或 `commands.start` 非占位（非空且非占位哨兵 `echo 'No start command configured yet'`），两者取 OR。契约静态检查、`verify_contract_missing` 前置探测与契约文档语义三方同一谓词——serve 缺失但 start 非占位的项目形态在执行期本就靠 commands.start 兜底（`core/pm_engine/verification/serving.py` 无契约路径直接回退 commands.start），任何一处单看 serve 段都会把该存量可用形态误打回，并造成同一状态一处打回一处放行。

**serve 一致性静态检查（scan_contract 交叉规则）**

- 交叉规则：出题产物场景 kind 集合含 api 或 web、契约 serve 段缺失、且 commands.start 无有效兜底（空或占位哨兵）时，报 serve 缺失 finding——出题产物验收不通过，打回补契约。
- 存量合法形态不报：场景全为 cli 且无 serve 段（存量纯 CLI 项目形态）不报；kind 集含 api/web、serve 缺失但 start 非占位也不报（执行期 commands.start 可兜底，存量零迁移）。
- 规则表隔离：serve 段缺失时只放开上述交叉规则，既有三条规则（serve_entry_missing / serve_entry_vs_start_mismatch / serve_entry_no_port_injection）维持早退不报，避免对无 serve 契约的存量项目误报既有类别；serve 段存在时三条规则语义不变。
- kind 集统计口径：从出题产物/冻结场景文件按执行 kind 原样统计，不做应用运行状态探测——静态配置校验与应用可达性探测分层各司其职，可达性归执行期 `_ensure_app_reachable`（执行期兜底保留）。
- 三路径统一挂载：新鲜出题验收、冻结场景复用、并行出题产物消费三类路径统一执行契约静态检查，任一路径的出题产物不得绕过 serve 一致性检查。

**verify_contract_missing 前置探测（能力覆盖口径）**

- 免唤起判定不只验「契约可解析」：须验契约 serve/start 能力（serve 段存在或 start 非占位）可覆盖在途场景的 kind 需求；契约可解析但能力未补齐时不 auto-resolve，信号保持 open，正常进入 Administrator 唤起流程。
- 契约补齐后免唤起恢复：契约含 serve 段且覆盖在途 kind 需求（或 start 非占位且在途场景全 cli）时，前置探测判满足，免唤起、信号闭环。

**边界**

- 契约起草不做自动代拟，仍由 Administrator 起草，预检只负责出题期打回与唤起。
- 「env 阻塞属 infra」的退款归类不变；serve/ready 探测实现与验证执行期 `_ensure_app_reachable` 兜底均不动。

## 溯源

- 2026-10-07 evo-add-verify-contract-preflight（spec/archive/2026-10-07-evo-add-verify-contract-preflight/） — 新增本能力页：实现期契约模板态前置巡检（ready/implementing 窗口、项目级单例、勿复位收尾），把契约起草从验证消费点前移到实现阶段并行（此前每个新项目首个 spec 首次推进到验证段必卡 blocked 等自主起草解锁，实测单次卡 26 分钟并连发 2 个 admin run）
- 2026-10-30 evo-add-scenario-serve-consistency-preflight（spec/archive/2026-10-30-evo-add-scenario-serve-consistency-preflight/） — 新增 serve 一致性交叉规则与三路径统一挂载，前置探测从「可解析」收紧为「能力覆盖」（此前静态检查 serve-None 早退、只挂新鲜出题验收路径，api/web 场景遇无 serve 契约推迟到执行期 fail-fast：实测 3 轮空转 35 秒 0 场景执行、spec blocked 约 51 分钟等契约补课，且 3 条信号被宽松前置探测错误 auto-resolve）
