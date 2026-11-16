# Design: fix-success-unattainable-alert-gap

## Context

`fix-spawn-attribution-hardening` 事故复盘（2026-11-16）：实现者以 fast-track 车道诚实收口，结果文件 `status="success"` + `completed_tasks` 19 项 + `unattainable=[6.3, 7.2]`（win-test 通道冻结，证据 `.fenix/verify-evidence/fix-spawn-attribution-hardening/win-test-channel-freeze.md`）。申报三处消费点均以 `partial` 为前提：`core/pm_engine/dispatch/fast_track.py:391-392`（`if result.success and ft_result.get("status") == "partial":`）、`core/pm_engine/dispatch/queue.py:2032`、`core/pm_engine/engine.py` partial 豁免分支——success+unattainable 形态在车道告警与门禁消费双双静默。判据单点 `core/run_task_track.py` 的 `honest_exit_convergence_gap`（gap_from_result + parse_unattainable，非法申报 fail-closed）本身不区分 status，可直接复用。既有告警写入点 `_note_unattainable_todos`（engine.py，写 AdminStore ESCALATION，signal_type=`impl_unattainable_tasks`，severity=warning）保留为唯一告警出口。

## Goals

- 申报的感知通道（告警 + 门禁注记）与顶层 status 解耦：申报存在且合法即感知，堵死 success+unattainable 静默丢申报。
- partial 既有语义（收敛判据、放行豁免、告警）与无申报路径（零误报）零变化。

## Non-Goals

- 不改收敛判据本身（partial + 全覆盖才收敛、非法 fail-closed 维持 D2b）。
- 不改 fast-track 顶层合同取值面（success 仍是唯一合法顶层值，verified/bug-found 仍属 verification.verdict）。
- 不新增告警信号类型或新的消费出口。

## Decisions

### D1 — 车道成功收口路径新增申报告警写入点（partial 收敛门不动）

两处既有消费点语义辨析：fast_track.py:391-392 与 queue.py:2030-2033 的 partial 前置块是**收敛门**（partial + 全覆盖才收敛、不重派），非本 SPEC 触碰面——收敛判据维持 partial 前置不变。缺口在**成功收口路径**：success+unattainable 落入正常收工分支后无任何申报感知。修法：两车道成功收口点各新增一个申报告警写入——`declared_unattainable(result)` 非空即调用既有 `_note_unattainable_todos`（信号名/severity/消费出口不变）；partial 走既有分支告警、success 走新写入点，两分支互斥不重复告警。语境约束：既有 `_note_unattainable_todos` 的 description 硬文案「门禁已放行」（engine.py:2991-2994）在 success+unattainable 路径失实——该路径 verified→done 门禁按 D4 fail-closed 拦截不放行。新写入点 MUST 传拦截语境 description：实现上为该函数加可缺省 `description` 形参、默认值保持既有文案（既有三调用点零变化），两车道新调用点传「门禁将拦截待人工裁决」语义文案；signal_type/severity/消费出口不变。申报解析新增模块级 helper `core/run_task_track.declared_unattainable(result) -> list`（内部复用既有 `parse_unattainable`，非法条目整体返回空——不告警、不豁免、不注记），不新增第二解析点，两车道对称调用（既有纪律）。

### D2 — 门禁 task-gap error 注记申报上下文（engine）

`engine.py` `_task_completion_blocker` 计算 gap 后，对 gap ∩ 合法申报集合非空的情形在既有 error 文案尾部追加注记 ` （其中 N 项已申报不可达）`。注记格式 MUST 为「前置空格分隔 + 不罗列任务 id」：人工回炉提取器 `task_reflow._extract_gap_tasks`（task_reflow.py:298）按 `[、,，;；:：\s]+` 从 error 文本反解 gap id，且尾部标点剥离集（`。.；;`）不含「（」——注记直接粘连会吞掉末位 gap id（"7.2（其中" 非合法 id 被弃），注记罗列 id 则在回炉留痕中重复计数；空格分隔后注记碎片均非合法 id，提取结果与无注记时全等。拦截行为、放行路径、人工补勾清除逻辑全部不变。无申报或申报非法时不追加。注记素材取结果文件申报，不读主树 tasks.md 勾选态（沿既有「缺口口径不回读主树」纪律）。

### D3 — 契约注释澄清（fast_track.py:408-410）

顶层合同注释补一行：`success + unattainable` 是合法申报形态，车道收口时触发 `impl_unattainable_tasks` 告警；verified/bug-found 仍属 verification.verdict。

### D4 — 场景判定不依赖告警放行

告警与注记只改变「人工感知」，不改变任何门禁放行语义：success+unattainable 的 SPEC 仍被 task-gap fail-closed 拦截在 verified→done（本事故中该拦截是唯一兜底，保留）；人工裁决路径（补勾 / reflow / 诚实退出豁免）不变。

## Risks

- 双消费点改动漂移：两车道必须同语义——用同一 helper（D1）+ 对称测试锚定（既有 `tests/test_fasttrack_wip_defer_branch_anchor.py` 已有车道锚定先例）。
- 误报面：D1 前提放宽后，若某 run 恰好 success 且申报为空/缺失，必须零告警——场景 3 显式覆盖；非法申报不告警——场景 5 显式覆盖。
- error 文案变化波及既有断言：task-gap error 注记仅追加尾部，前缀 `task-gap:未完成任务：` 不变；`TASK_GAP_ERROR_PREFIX`（core/pm_engine/__init__.py:33）前缀锚定消费方不受影响（task_reflow 回炉资格判定、engine:4499 blocker 改述、_clear_task_gap_error 均只认前缀）。唯一非前缀消费点 `task_reflow._extract_gap_tasks` 已按 D2 格式约束对账（空格分隔、不罗列 id → 提取全等），场景 1.4 锚定；全量回归验证。

## 交付面

`core/run_task_track.py`（helper）、`core/pm_engine/dispatch/fast_track.py`、`core/pm_engine/dispatch/queue.py`、`core/pm_engine/engine.py`（注记）、对应测试文件（tests/test_honest_exit_convergence.py 扩展 + 车道锚定）。
