<!-- knowledge: capability=honest-exit-convergence rev=1 sources=spec/archive/2026-09-22-fix-redispatch-loop-governance -->

# 诚实退出收敛

实现 run 以 partial 收工且缺口全部申报为不可达成时视同成功收口的判定与收口协议：承认诚实的部分交付，同时堵死 partial 洗白。

## 现行规则

- 收敛判据：run 以 `status: "partial"` 收工、且未完成任务缺口全部 ⊆ 结果文件顶层 `unattainable` 申报（`缺口集合 − unattainable 申报集合` 为空）时，判为「诚实退出收敛」，视同成功收口，不因缺口非空判失败或重派。无 `unattainable` 数组（或为空）、或存在未申报缺口时不收敛，按既有失败通道处置。
- 缺口口径单点：缺口集合解析走唯一实现点 `core.run_task_track.gap_from_result`（`unfinished` 非空则直接采信，否则以全部数字任务 − `completed_tasks` 反推）。不存在「缺 `unfinished` 时回退读主树 tasks.md 勾选状态」的推导路径——主树 `[x]` 只在成功/merge-back 路径回写，partial 收敛走不到该路径，读它会把已完成任务也算成缺口。`dispatch._honest_exit_gap`、`engine._partial_attribution`、`engine._task_completion_blocker` 三处消费点同源调用该函数，无一处自行解析 tasks.md 勾选。
- 收敛点对非法申报 fail-closed：`unattainable` 中存在非法条目（非映射 / task 非合法 id / 缺 reason）时整体判不收敛并走失败通道，不「合法项生效、非法项静默忽略」；全部条目合法（合法 task id + 非空 reason）且覆盖全部缺口才收敛。
- 收敛后的收口动作沿既有成功路径继续、不短路跳过其中的门：零变更哨（收敛 run 有真实提交，误判时以「交付物齐备 + 分支有提交」放行）→ 交付物守卫（缺件不放行、按既有通道处置）→ tasks.md relint → merge-back → transition(implemented) 后入队 verifier。
- 两条车道对称：full 与 fast-track 车道使用同一判据（`gap_from_result`）、同语义收口（不重派 + 转成功收口）、同形态留痕（「哪些任务交给了人工」的人工待办告警 + 日志含收敛判据与缺口清单）。fast-track 收敛后改写 mode 为 `full`、进入 `implemented` 并入队 verifier，不停在单 run 自证路径上等待（partial 结果文件不含合法 verification 段，不被 fast-track 硬校验判失败打回，按设计降级完整模式补独立验证）。
- 任务与交付物以函数名 / 类名 / 信号名锚定，不以绝对行号作为唯一锚点。

## 溯源

- 2026-09-22 fix-redispatch-loop-governance — 确立 partial + unattainable 全覆盖的收敛判据、`gap_from_result` 缺口单点解析、非法申报 fail-closed 与两车道对称收口
