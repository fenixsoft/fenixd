# proposal: add-impl-run-budget-sizing

## Why

实现 run 的轮数上限是全局静态值（core/agent_runner/runner.py:2695 统一读 `agents.max_turns`，potplayer-base 配 400），派发前与 spec 任务规模无任何联动；轮次上限活性续期矩阵（ADR-103）的扩容依据只有「分支提交增量 / 尾窗 60 秒 tool_result 流量」两条活性证据（runner.py:2201-2339），无剩余工作量维度。实证（potplayer-base cimbar-airgap-transfer，2026-10-02）：38 任务 + 40 交付物（estimate_spec_scale 口径 118 分，远超现行 30/45 阈值）的 spec 走 impl 车道，首轮 run 烧满 400+100+100=600 轮熔断（error 原文「Max turns (600) reached — turn extension budget exhausted (2/2)」），熔断于真实编辑工作途中；同 session 续做 run 再耗 311 轮 / $10.67 / 2 小时 13 分钟才收尾同一轮实现。同 spec 成功 run 簿记占比（TaskCreate+TaskUpdate / 总工具调用）仅 5.7%（17/300），熔断 run 达 15.5%（61/393）——簿记异常信号已落在 run_metrics 直方图里却无任何消费点。既有 fast-track 规模预检（archive 2026-09-18-evo-add-fast-track-scale-precheck）只覆盖 fast-track 车道且只加成墙钟超时扩容（liveness.py:1241-1252），impl 车道获益为零。不立项则下次任何 33+ 任务量级的 spec 在 impl 车道都会复演同一熔断→续做路径。

## What Changes

- 派发（启动）时按 spec 规模分推算建议轮数上限：复用 estimate_spec_scale（core/fast_track_result.py:152），规模分超阈值的大 spec 将生效轮数上限抬到建议值；spec 可经 STATE `impl_turn_cap_override` 覆写（沿 impl_run_budget_override 字段先例）；规模解析异常保守回退基础值，不阻断派发。
- 轮次扩容判定携带工作量维度：`_turn_limit_action` 的 extend/kill 证据与 `turn_extension` 事件、run_metrics 增记剩余未勾选任务数（run_task_track 单点解析）与簿记占比；簿记占比超阈值只 WARNING 留痕与证据注记，不直接改变判定。
- 末位扩容拆停守卫：缺省关闭（沿 run_stall_budget 缺省关闭灰度先例）；开启时，末次扩容判定点若剩余任务量与 run 内勾选进度表明续期不济，提前走既有 kill+WIP 保全收口（ADR-103 锚点），evidence 注明依据；关闭时判定矩阵与现状逐位一致。

## Capabilities

### New Capabilities

- impl-run-budget-sizing: 实现 run 轮数预算按 spec 规模 sizing——启动时建议上限（可覆写）、扩容判定与事件携带剩余工作量、末位扩容拆停守卫（缺省关闭）。

## Impact

- core/fast_track_result.py：新增 turn budget sizing 配置归一化与推算函数（与 estimate_spec_scale / get_scale_precheck_config 同文件同风格）。
- core/agent_runner/runner.py：实现车道启动处生效上限计算；`_turn_limit_action` 证据与事件增字段；run_metrics 增 remaining_tasks；kill_early 守卫。
- 对 ADR-103 的关系：活性续期矩阵的 extend/kill 语义除「缺省关闭的末位守卫」外零改动；本 SPEC 是对该 ADR 的补充而非修订，需在 knowledge 侧补一条注记说明新字段。
- pm_engine 派发决策、超时扩容（timeout_supervision）、impl_run_budget（run 次数预算）三套机制零改动；不新增 admin 告警类型。