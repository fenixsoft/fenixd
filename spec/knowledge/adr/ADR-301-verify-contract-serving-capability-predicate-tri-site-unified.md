# ADR-301：验证契约服务能力谓词三方同口径（serve 段或非占位 start），静态检查/前置探测/执行期兜底单一谓词

date: 2026-10-30
status: accepted

## Context

验证契约的「服务能力」判定散布在三处且口径一度不一致：出题期契约静态检查 `scan_contract` 在 serve 段缺失时整段早退返回空（三条 serve 规则全部只在 serve.cmd 存在时生效）；`verify_contract_missing` 信号的前置探测只验「契约可解析」即免唤起；执行期 `_ensure_app_reachable` 则按「serve 段缺失时直接回退 commands.start」兜底。2026-10-10 pack2-live-stream-player 实测该错位的代价：场景集含 api/web 而契约无 serve 段，缺口一路漏到验证执行期，35 秒内 3 轮 fail-fast（0 场景执行）、spec blocked 约 51 分钟等 Administrator 补契约，期间 3 条 verify_contract_missing 信号被「可解析即满足」的宽松前置探测错误 auto-resolve，靠指纹升级才打破。若把静态检查简单改成「无 serve 段即打回」，会误伤存量可用形态（serve 缺失但 commands.start 非占位的项目，执行期本就靠 commands.start 兜底运行），并与前置探测口径自相矛盾——同一契约状态在出题期被打回、在前置探测处被放行闭环。

## Decision

- 服务能力谓词唯一：「契约具备服务能力」定义为 serve 段存在，或 `commands.start` 非占位（非空且非占位哨兵 `echo 'No start command configured yet'`），两者取 OR。三个判定点统一执行同一谓词：出题期静态检查交叉规则（serve 缺失 × kind 集含 api/web × start 无有效兜底 → 报 serve 缺失 finding）、`verify_contract_missing` 前置探测免唤起判定（能力可覆盖在途场景 kind 需求才满足）、执行期 serving 无契约路径的 commands.start 回退；契约文档语义同口径。
- 静态检查与运行探测分层：静态检查只按执行 kind 原样统计场景集合做配置形态校验，不做应用运行状态探测；可达性归执行期 `_ensure_app_reachable` 兜底，两层各司其职，静态检查不前移运行时语义。
- serve-None 早退只对新交叉规则放开：serve 段缺失时既有三条 serve 规则（serve_entry_missing / serve_entry_vs_start_mismatch / serve_entry_no_port_injection）维持早退不报，避免对无 serve 契约的存量项目误报既有类别；serve 段存在时三条规则语义不变。
- 后续任何新增的契约能力判定点（autodraft 自证、豁免判定等）MUST 沿用同一谓词，不得单点另立口径。

## Consequences

- 误打回被双白名单收窄：场景全 cli 且无 serve 段、以及 serve 缺失但 start 非占位的存量形态均不报，存量项目零迁移；前置探测收紧会少量增加 Administrator 唤起（契约可解析但缺能力形态），这是意图内行为——该形态本就该唤起起草而非静默闭环。
- 谓词口径成为三处同步义务：修改谓词（如占位哨兵文案、OR→AND）必须三方同改，单一处改动即产生同一状态双重判定的矛盾；kind 统计口径与验证执行期判定一致（按执行 kind 原样），计入 mock/跳过类场景即误报。
- 静态检查的结论只针对配置形态，不能替代执行期可达性：应用起不来仍由执行期 fail-fast 与 env-block 通道负责，「env 阻塞属 infra」的退款归类不受本裁定影响。
- 替换 commands.start 兜底语义、或将前置探测改回「可解析即满足」、或让静态检查探测运行状态，均须显式 supersede 本 ADR。
