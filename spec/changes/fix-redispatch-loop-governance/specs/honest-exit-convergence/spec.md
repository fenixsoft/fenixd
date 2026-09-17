# honest-exit-convergence

## ADDED Requirements

### Requirement: 收敛判据

实现 run 以 `status: "partial"` 收工、且**未完成任务的缺口全部 ⊆ 结果文件顶层 `unattainable` 申报**时，框架 MUST 判为「诚实退出收敛」：视同成功收口，MUST NOT 因缺口非空而判失败或重派。

判据 MUST 为：`缺口集合`（由结果文件 `unfinished` 采信，或以 `completed_tasks` 反推）减去 `unattainable` 申报集合后为空。

#### Scenario: 缺口全部已申报 → 收敛

- **WHEN** 结果文件为 `status: "partial"`、`completed_tasks` 列出全部已完成任务、`unattainable` 申报了剩余未完成的任务，且 `result.success` 为真
- **THEN** 收敛成立，spec 状态推进为 `implemented`，MUST NOT 进入重派通道

#### Scenario: 存在未申报缺口 → 不收敛

- **WHEN** 任一未完成任务既不在 `unfinished`、也不在 `unattainable` 申报中
- **THEN** 收敛不成立，按既有失败通道处置（防 partial 洗白）

#### Scenario: 无 unattainable 申报 → 不收敛

- **WHEN** 结果文件为 `partial` 但顶层无 `unattainable` 数组（或为空）
- **THEN** 收敛不成立，按既有失败通道处置

### Requirement: 缺口口径单点

缺口集合的解析 MUST 走唯一实现点 `core.run_task_track.gap_from_result`（`unfinished` 非空则直接采信；否则以 `全部数字任务 − completed_tasks` 反推）。

MUST NOT 存在任何「缺 `unfinished` 时回退读主树 `tasks.md` 勾选状态」的缺口推导路径——主树 `[x]` 由 `_sync_task_progress` 只在成功/merge-back 路径回写，partial 收敛走不到该路径，读它会把**已完成任务也算成缺口**，构成读侧自锁（2026-09-17 事故）。

#### Scenario: 主树未勾选不影响判据

- **WHEN** 主树 `tasks.md` 全部为未勾选（`_sync_task_progress` 尚未回写），而结果文件 `completed_tasks` 列出 14 项已完成、`unattainable` 申报剩余 1 项
- **THEN** 缺口集合为那 1 项、收敛成立

#### Scenario: 三处消费点同源

- **WHEN** 审查 `dispatch._honest_exit_gap` / `engine._partial_attribution` / `engine._task_completion_blocker` 的缺口推导
- **THEN** 三者均调用 `gap_from_result`，无一处自行解析 tasks.md 勾选

### Requirement: 收敛后的收口动作序列

收敛成立后，run MUST 沿**既有成功路径**继续，MUST NOT 短路跳过其中的门：

1. 零变更哨（`_implementer_zero_change`）——收敛后的 run 有真实提交，哨兵 MUST NOT 误判为空转；若误判，须以「交付物齐备 + 分支有提交」放行（既有确认型 no-op 语义）。
2. 交付物守卫（`_deliverable_gate_missing`）——按声明段机械对账。
3. tasks.md relint。
4. merge-back（分支并入主树）。
5. 入队 verifier（`transition(implemented)` 后 `_enqueue(spec, "verifier")`）。

#### Scenario: 收敛后走到 verifier

- **WHEN** 诚实退出收敛成立且交付物齐备
- **THEN** 分支被 merge-back 进主树，spec 进入 `implemented`，verifier 被入队

#### Scenario: 收敛后不因缺口跳过门

- **WHEN** 收敛成立但声明段交付物缺件
- **THEN** 仍走交付物守卫的既有处置（缺件不合并、按既有通道处置），MUST NOT 因已收敛而放行缺件

### Requirement: 两条车道对称

full 车道（`dispatch._run_agent_worker`）与 fast-track 车道（`dispatch._run_fast_track_flow`）的诚实退出收敛 MUST 使用**同一判据**（`gap_from_result`）、产生**同语义收口**（不重派 + 转成功收口），并留下**同形态可观测留痕**（人工待办告警 + 日志）。

两条车道的差异（如 fast-track 的单 run 全包、无 verifier 车道）MUST 在 design 中显式记录，MUST NOT 出现「一条车道收敛、另一条不收敛」的不对称。

#### Scenario: fast-track 车道同样收敛

- **WHEN** fast-track run 以 `partial` 收工且缺口全部 ⊆ `unattainable`
- **THEN** 该车道同样收敛（不重派），且 MUST 到达验证入口——`partial` 结果文件必然不含合法 `verification` 段，故 MUST NOT 被 fast-track 硬校验（要求 scenarios 非空 + verdict ∈ {verified, bug-found}）判失败打回；收敛后按 design D2a 降级完整模式补独立验证

#### Scenario: fast-track 车道可用的验证入口

- **WHEN** fast-track 车道的诚实退出收敛成立
- **THEN** spec 进入可被三阶段独立验证的状态（mode 改写为 `full` + `implemented` + 入队 verifier），MUST NOT 停在 fast-track 单 run 自证路径上等待

### Requirement: 收敛点对非法申报 fail-closed

收敛判据 MUST NOT 部分采信 `unattainable` 申报：存在**非法条目**（非映射 / task 非合法 id / 缺 reason）时 MUST 判不收敛并走失败通道，MUST NOT「合法项生效、非法项静默忽略」。

（动机：产物硬门正常时非法申报已被拦，但「只卡第一次」降级放行后非法条目可抵达收敛点；部分采信等于开了洗白窗口。）

#### Scenario: 含非法条目则不收敛

- **WHEN** 结果文件 `unattainable` 数组中含一项非法条目（如 `task` 非合法 id），且其余条目恰好覆盖全部缺口
- **THEN** 收敛 MUST NOT 成立，按失败通道处置

#### Scenario: 条目全合法才收敛

- **WHEN** `unattainable` 全部条目合法（合法 task id + 非空 reason）且覆盖全部缺口
- **THEN** 收敛成立

#### Scenario: 留痕对称

- **WHEN** 任一车道发生诚实退出收敛
- **THEN** 均写出「哪些任务交给了人工」的人工待办告警，且日志含收敛判据与缺口清单

### Requirement: 不使用绝对行号锚定

任务与交付物 MUST 以函数名 / 类名 / 信号名锚定，MUST NOT 以绝对行号作为唯一锚点。

#### Scenario: 任务锚点为符号名

- **WHEN** 审阅 tasks.md
- **THEN** 每项任务以函数名或信号名定位
