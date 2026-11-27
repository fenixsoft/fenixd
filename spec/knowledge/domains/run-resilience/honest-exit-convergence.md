<!-- knowledge: capability=honest-exit-convergence rev=2 sources=spec/archive/2026-09-22-fix-redispatch-loop-governance,spec/archive/2026-11-27-fix-success-unattainable-alert-gap -->

# 诚实退出收敛

实现 run 以 partial 收工且缺口全部申报为不可达成时视同成功收口的判定与收口协议，以及不可达申报（unattainable）的人工感知通道：承认诚实的部分交付，同时堵死 partial 洗白与申报静默丢失。

## 现行规则

- 收敛判据：run 以 `status: "partial"` 收工、且未完成任务缺口全部 ⊆ 结果文件顶层 `unattainable` 申报（`缺口集合 − unattainable 申报集合` 为空）时，判为「诚实退出收敛」，视同成功收口，不因缺口非空判失败或重派。无 `unattainable` 数组（或为空）、或存在未申报缺口时不收敛，按既有失败通道处置。
- 缺口口径单点：缺口集合解析走唯一实现点 `core.run_task_track.gap_from_result`（`unfinished` 非空则直接采信，否则以全部数字任务 − `completed_tasks` 反推）。不存在「缺 `unfinished` 时回退读主树 tasks.md 勾选状态」的推导路径——主树 `[x]` 只在成功/merge-back 路径回写，partial 收敛走不到该路径，读它会把已完成任务也算成缺口。`dispatch._honest_exit_gap`、`engine._partial_attribution`、`engine._task_completion_blocker` 三处消费点同源调用该函数，无一处自行解析 tasks.md 勾选。
- 非法申报 fail-closed：`unattainable` 中存在非法条目（非映射 / task 非合法 id / 缺 reason）时申报整体不生效——不收敛、不写告警、不产生门禁注记、不参与任何放行豁免，沿既有 fail-closed 通道处置，不「合法项生效、非法项静默忽略」；全部条目合法（合法 task id + 非空 reason）且覆盖全部缺口才收敛。申报合法条目的解析走单点薄封装 `core.run_task_track.declared_unattainable`（内部复用 `parse_unattainable`，禁第二解析点）。
- 感知通道与顶层 status 解耦：不可达申报的人工感知通道（告警 + 门禁注记）触发条件是「申报存在且全部条目合法」，与结果文件顶层 `status` 取值无关——fast-track 顶层合同唯一合法顶层值为 `success`（verified/bug-found 属于 verification.verdict），`success + unattainable` 是合法申报形态，不因收工形态非 partial 而静默（见 [ADR-359](../../adr/ADR-359-declaration-perception-status-decoupled-perception-enforcement-split.md)）。
- 告警面唯一出口：两车道收口路径凡合法申报非空即写 `impl_unattainable_tasks` ESCALATION 告警（severity=warning，含 SPEC 名与申报清单）——partial 收敛分支与 success 正常收工分支各有写入点、两分支互斥不重复告警；告警一律经 `engine._note_unattainable_todos` 写入（signal_type / severity / 消费出口固定），不新增第二告警出口；告警写失败仅 debug 不阻断收口。
- 告警语境随放行形态：partial 全申报收敛后门禁放行，告警用既有「门禁已放行」放行语境文案；success 收工路径门禁将 fail-closed 拦截，告警 MUST 传「门禁将拦截待人工裁决」拦截语境文案（`description` 为可缺省形参，缺省保持既有放行文案，既有调用点零变化）——「已放行」文案在拦截语境下失实会误导人工以为无需动作。
- 门禁注记：verified→done 门禁因未勾任务拦截且缺口与合法申报交集非空时，task-gap error 文案尾部追加注记 ` （其中 N 项已申报不可达）`，人工裁决无需翻结果文件即知申报已在场；fail-closed 拦截行为与放行路径不变，无申报或申报非法时不追加。注记素材取结果文件申报，不读主树 tasks.md 勾选态（沿「缺口口径不回读主树」纪律）；注记格式受回炉提取器机读契约约束（见 [ADR-360](../../adr/ADR-360-task-gap-error-text-machine-readable-contract.md)）。
- 无申报零误报：run 以 success 收工且 `unattainable` 缺失或为空时，不写告警、不产生注记、门禁不消费申报，车道正常收口零打扰。
- 感知与放行分离：告警与注记只改变人工感知，不改变任何门禁放行语义——success + unattainable 的 SPEC 仍被 verified→done 门禁 fail-closed 拦截，人工裁决出口（补勾 / 回炉 / 诚实退出豁免）不变。
- 收敛后的收口动作沿既有成功路径继续、不短路跳过其中的门：零变更哨（收敛 run 有真实提交，误判时以「交付物齐备 + 分支有提交」放行）→ 交付物守卫（缺件不放行、按既有通道处置）→ tasks.md relint → merge-back → transition(implemented) 后入队 verifier。
- 两条车道对称：full 与 fast-track 车道使用同一判据（`gap_from_result`）、同语义收口（不重派 + 转成功收口）、同形态留痕（人工待办告警 + 日志含收敛判据与缺口清单），成功收口申报告警写入点两车道对称、同 helper 同信号。fast-track 收敛后改写 mode 为 `full`、进入 `implemented` 并入队 verifier，不停在单 run 自证路径上等待（partial 结果文件不含合法 verification 段，不被 fast-track 硬校验判失败打回，按设计降级完整模式补独立验证）。

## 代码锚点

- 判据与解析单源：`core/run_task_track.py`（`gap_from_result` 缺口解析单点、`honest_exit_convergence_gap` 收敛判据、`parse_unattainable` / `declared_unattainable` 申报合法条目单源薄封装）
- 消费方：`core/pm_engine/dispatch/fast_track.py`、`core/pm_engine/dispatch/queue.py`（两车道收敛门与成功收口申报告警写入点）；`core/pm_engine/engine.py`（`_note_unattainable_todos` 告警唯一出口、`_task_completion_blocker` task-gap 申报注记）；`core/pm_engine/task_reflow.py`（`_extract_gap_tasks` 回炉提取器，task-gap error 文案反解消费方）
- 守卫测试：`tests/test_honest_exit_convergence.py`

## 溯源

- 2026-09-22 fix-redispatch-loop-governance（spec/archive/2026-09-22-fix-redispatch-loop-governance） — 确立 partial + unattainable 全覆盖的收敛判据、`gap_from_result` 缺口单点解析、非法申报 fail-closed 与两车道对称收口
- 2026-11-16 fix-success-unattainable-alert-gap（spec/archive/2026-11-27-fix-success-unattainable-alert-gap/） — 申报感知通道与顶层 status 解耦：两车道成功收口新增 `impl_unattainable_tasks` 告警写入点（拦截语境 description）与 verified→done 门禁 task-gap 申报注记，堵死 success+unattainable 静默丢申报；partial 收敛判据、告警出口与 fail-closed 语义不变
