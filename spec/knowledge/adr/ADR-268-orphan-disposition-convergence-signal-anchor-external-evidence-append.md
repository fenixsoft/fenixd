# ADR-268：孤儿处置收敛锚定未收口信号、外部证据核查、台账 append 补记

date: 2026-10-11
status: accepted

## Context

admin 处置台账存在「动作已执行、终态未落账」窗口：admin agent 可经 Bash 直调执行处置动作（框架在动作时刻无法感知），run 死亡后留下「partial 终态 + 关联信号未收口 + pending 占位」组合。既有孤儿升级扫描对 final 处置组无条件跳过，该形态永久滞留。判别锚点取证表明：DISPOSITION 记录的 handled 字段无任何 mutator（实测恒 false）、健康组的 pending 占位同样永久在场，二者都不能当「滞留」判据——唯一可锚定的是关联底层 SIGNAL 记录仍未收口（且 SIGNAL 记录 spec=null 与 DISPOSITION 记录 spec="global" 的记法差异须归一化匹配，否则永不命中）。

## Decision

- 孤儿处置收敛侧是主承力点：admin agent 的 Bash 直调动作通道不做执行时刻拦截（框架无法感知），处置窗口缩短类加固只作辅助；滞留兜底一律放在收敛侧事后核查。
- 滞留判据唯一锚定「关联底层 SIGNAL 记录未收口」（escalated=true 口径、None ↔ "global" 归一化匹配），处置记录自身字段与组内 pending 占位一律不得作滞留判据。
- 生效核查证据权威是外部真实状态：STATE 的 frozen/status 与 fenixd.log 的 Transition 留痕（global/None 组以日志时间窗对账），处置记录自身文本严禁自证；证据不足默认维持滞留走升级，绝不强行补 resolved（fail-closed）。
- 处置台账 DISPOSITION 一律 append 新记录（补记注明 backfill 与依据），禁就地改写既有 pending 或终态记录；幂等靠「组内 backfill 记录在场即跳过」判据，不靠改写标记位。
- 收敛侧小步落账的逐动作留痕事件禁携带 admin_run_id（防 `_merge_admin_runs` 并组提前 final、破坏「在飞 = has_pending 且非 final」判据）；信号收口以 choice 整体执行 ok 为准，失败不预写 resolved（延续 ADR-260 结果前置纪律）。
- 组内已有 escalate=true 终结记录或同 spec 存在在飞 admin run 时跳过收敛——升级人工与在飞语义优先于事后补记。

## Consequences

- 「final 即跳过」的孤儿扫描盲区关闭，存量滞留组由下一扫描周期自然消费，无需手工清洗台账。
- 后续处置台账类判定不得引用 disposition.handled 或组内 pending 占位作状态依据；新增留痕/补记事件一律 append 形态且禁携 run_id（除非显式接续在飞判据重构）。
- 生效核查依赖 STATE 与日志的真实状态证据形态，新增处置动作若不落 Transition 留痕或不改 STATE 可观测字段，则对 global/None 组不可核查、只能滞留升级——新增动作须保证至少一条外部证据通道可对账。
