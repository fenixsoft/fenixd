# design: add-impl-run-budget-sizing

## Context

- 轮数上限读点：`core/agent_runner/runner.py:2695`（实现车道 `_run_claude` 调用，`max_turns=self._get_config("agents.max_turns", 300)`；同型读点 :1266 dispute-judge、:1407 spec-review、maintenance_runs.py:318/601/985）。pm_engine 零处引用 max_turns——轮数是 runner 启动期一次性注入的静态值。
- 扩容判定：`runner.py:2201` `_turn_limit_action`，封闭矩阵（封顶→分支提交增量→60s tool_result 流量→双无 kill）；调用点 `runner.py:5278-5284` 手握 `run_file / spec_name / cwd`（worktree 路径）与 `turn_extensions_used`。事件留痕在调用点 `append_run_line`（:5288 附近），`turn_step`/`evidence`/`new_turn_cap` 逐字段写入。
- 常量：`runner.py:374-376` `TURN_EXTENSION_STEP_FRACTION=0.25 / TURN_EXTENSION_MAX=2 / TURN_EXTENSION_WINDOW_SECONDS=60.0`（模块级、不进 config.yaml 的先例注释）。
- 可复用基建：`core/fast_track_result.py:152` `estimate_spec_scale`（未勾选任务×1 + 非引用交付物×2）与 :305 `get_scale_precheck_config`（非法值回退缺省的单点归一化范式）；`core/run_task_track.py:109/119` `tasks_md_path`/`parse_tasks_md`（三处消费的单一正则口径）；run_metrics 每工具直方图产出点 `runner.py:4867/4945/5413-5436`。
- 覆写先例：STATE 字段 `impl_run_budget_override` 已存在（impl run 次数预算的 spec 级覆写）；`_fast_track_scale_tier` 标记（queue.py:1060 写 / liveness.py:1247 读）是「派发期算、run 期消费」的既有通路。
- 约束源：ADR-103（knowledge/adr/ADR-103）确立「任一活性即 extend、不腰斩健康推进 run」；在途 evo-add-run-stop-loss 确立「灰度判停缺省关闭」先例。

## Goals

- 大任务面 spec 在 impl 车道不再以统一 400/600 轮预算硬扛：规模超阈即获得更高起点上限，消除 cimbar 形「烧满熔断→续做再耗 311 轮」的主浪费段。
- 扩容决策与事件带上剩余工作量观测面，使「差一点还是差很远」在留痕里可判。
- 末位不济时提前收口的能力以缺省关闭的守卫形态落地，不动摇 ADR-103 不变量。

## Decisions

- **D1 sizing 落在 runner 启动点而非 pm_engine 派发点**：轮数只在 `_run_claude` 注入处被消费，启动点已有 project_root/spec_name/STATE 访问（同对象族 liveness.py 有 `state_machine.read_one` 先例），无需新增 pm_engine→runner 传递面，也免去 `_fast_track_scale_tier` 式状态标记的写读两侧。推算函数与配置归一化放 core/fast_track_result.py（与 estimate_spec_scale、get_scale_precheck_config 同文件单点，禁止再造第二套 tasks.md/交付物解析）。
- **D2 修订增量不作首版输入**：派发时点不存在实现产物，「修订增量→轮数」无可观测源。首版 sizing 输入 = estimate_spec_scale（任务数 + 交付物数）；若未来需要，可在续做 run（resume 场景）用分支 commit 数作增量信号，留作后续项。
- **D3 生效序 = override > 推算 > base**：override 用 STATE `impl_turn_cap_override`（沿 impl_run_budget_override 命名与语义先例），仅接受正整数；推算只在 enabled 且规模分 > full_scale_threshold 时抬到 max(base, suggested_turn_cap)，永不低于 base。
- **D4 剩余任务数读 main 树口径（project_root）**：与 result_gate 硬门、`_task_completion_blocker` 同一 tasks_md_path 口径；worktree 内 tasks.md 未合回时会滞后，main 树口径与完成度门禁判据一致，避免双口径漂移（run_task_track docstring 的「禁止第二套正则」约束）。
- **D5 簿记占比只观测不改判**：占比高是低效/打转信号但非失败证据（大 spec 首轮建任务簿记天然高），单独作为 kill 依据会误伤；仅 WARNING + evidence 注记。占比计算从 `_run_claude` 已维护的 tool_metrics 直方图派生，不新增转录扫描。
- **D6 kill_early 缺省关闭、条件三重与**：末次扩容判定点 + 剩余任务超阈 + run 内进度近零，三条件同时成立才提前 kill；收口复用 ADR-103 既有 kill+WIP 保全锚点，零新增收口代码。关闭路径零行为变化（测试断言同输入同输出）。
- **D7 配置键**：`agents.turn_budget_sizing.{enabled, full_scale_threshold, suggested_turn_cap, bookkeeping_share_threshold, kill_early.{enabled, remaining_tasks_threshold, progress_floor}}`，归一化单点 `get_turn_budget_sizing_config`（非法值逐项回退缺省，风格对齐 get_scale_precheck_config），与设置界面读侧同源。

## Risks

- **推算过高大 spec 长跑**：suggested_turn_cap 缺省 800 较 base +50%，失控 run 的最坏墙钟增幅由既有 60s 无活性 kill 兜底（无活性一次扩容都拿不到，ADR-103 已证）；可在 config 按项目收敛。
- **kill_early 误杀慢热 run**：三重与条件 + 缺省关闭 + 勾选进度地板三重护栏；开启项目首次触发需在告警证据中复核。
- **evidence/事件新字段破坏读侧**：turn_extension 读侧按既有字段消费（dashboard/自省），新增键为附加不替换；`append_run_line` 侧同步（runner.py:5288 附近）保持单点。
- **与 evo-add-run-stop-loss 边界**：该 SPEC 管 run 级止损（取消旗标/retry 让位/停滞判停），本 SPEC 管轮数预算轴；两者都改 runner.py 时注意 rebase 顺序，语义无交叠。
- **tasks.md 中途被实现者勾选导致 remaining_tasks 波动**：字段是观测值非判定唯一依据，文档写明口径为「判定时点快照」。