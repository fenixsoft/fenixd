# 验证报告：evo-add-impl-wallclock-budget-sizing

> ⚠️ 本报告由框架于 2026-10-03T21:28:06Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。
> 报告时效标记（判定本报告是否属上一轮）：合成源轮次指纹：report.json@2026-10-03T21:28:05.935927+00:00+run-result@mtime1791062885973335842

## 结论：✅ 通过（verified）

**状态：verified — 16/16 场景通过，0 失败，0 错误（全部场景通过）**

全绿快道: 16/16 场景通过、0 失败 0 警告——无分类对象，跳过 judge 机械 verified

| 指标 | 数量 |
| --- | --- |
| 通过 | 16 |
| 失败 | 0 |
| 错误 | 0 |
| 产品 Bug | 0 |
| 本链增量 Token（输入） | 2.92M |
| 本链增量 Token（输出） | 0.07M |


## 场景结果

| 场景 | 描述 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- | --- |
| wc-sizing-config-defaults | 墙钟 sizing 配置归一化缺省：get_impl_wallclock_sizing_config({}) 返回单源缺省 enabled=True/full_scale_threshold=45/extra_extensions=2，与 core.config.IMPL_WALLCLOCK_SIZING_DEFAULTS 逐键一致（core/fast_track_result.py:502、core/config.py:70） | pass | 0/5 | - |
| wc-deadline-impl-lane-lift | impl 车道 deadline 判定按 sizing 抬续期预算：base 2→4 抬升、非 impl 车道不抬、无 impl_scale 时与现状逐位一致（core/agent_runner/liveness.py:1300-1330） | pass | 0/4 | - |
| wc-deadline-remaining-tasks-kill-evidence | 扩容预算耗尽击杀：reason 保留 extension budget exhausted 子串（budget.py:340 豁免判据依赖）、evidence 附 remaining_tasks、不因剩余任务新增分支（core/agent_runner/liveness.py:1314） | pass | 0/4 | - |
| wc-deadline-tier-idempotent-and-cap | deadline 判定档位幂等与封顶不变：推进中 remaining_tasks 递减不回撤已抬档位、absolute_max_seconds 仍无条件封顶（core/agent_runner/liveness.py:1314、design 档位幂等约束） | pass | 0/3 | - |
| wc-deadline-reason-exempt-contract | 墙钟 sizing 生效后豁免口径复核：extension budget exhausted/absolute_max 封顶/stagnant 仍不可豁免，infra 类 reason 仍可豁免（core/pm_engine/budget.py:330-345，design 决策 5） | pass | 0/4 | - |
| wc-deadline-scale-single-source | 规模与剩余任务数同源取数：_impl_wallclock_scale 与 estimate_spec_scale 单点同源、_remaining_tasks_now 走 parse_tasks_md 与 finally run_metrics 一致（core/agent_runner/runner.py:6226） | pass | 0/4 | - |
| wc-deadline-state-override-preferred | STATE 覆盖键优先且只抬不压：impl_wallclock_extension_override 正整数优先于规模推算、STATE 缺失容忍（core/agent_runner/runner.py:6198、liveness.py:1300） | pass | 0/3 | - |
| wc-timeout-extension-event-field | timeout_extension 事件携带 remaining_tasks 观测字段：事件构造含 remaining_tasks 键且既有字段零改动（core/agent_runner/runner.py:5584-5590，结构回归点） | pass | 0/4 | - |
| wc-usage-note-kill-without-result | 击杀且无 CLI result 落用量缺失注记：kill loop 抬升预算生效且 run_metrics 附用量注记（原因+transcript 粗估维度），不臆造 cost（core/agent_runner/runner.py finally 块） | pass | 0/4 | - |
| wc-usage-note-success-unchanged | 成功 run 与带 result 的击杀 run 不落用量注记：成功路径落盘行为不变（core/agent_runner/runner.py:5730-5733 行为零改动） | pass | 0/3 | - |
| wc-turn-sizing-regression-suite | 既有轮数 sizing 套件 37 例不回退：tests/test_impl_run_budget_sizing.py 全量通过（轮数 sizing 语义零改动的回归证明，tasks 3.2） | pass | 0/2 | - |
| wc-new-suite-full-green | 新增墙钟 sizing 套件全量绿灯：tests/test_impl_wallclock_budget_sizing.py 55 项（parametrize 展开）全部通过，覆盖 sizing 归一化/阈值/覆盖键/扩容判定新分支/用量注记（tasks 3.1） | pass | 0/2 | - |
| wc-sizing-config-invalid-fallback | 墙钟 sizing 配置非法值逐项回退：enabled 非布尔/threshold 越界与非整/extra 非整均回退缺省不抛异常（core/fast_track_result.py:502） | pass | 0/9 | - |
| wc-sizing-config-explicit-section | 墙钟 sizing 显式配置生效与关闭：enabled=false 关闭、threshold=50 独立生效、extra=0 合法（显式不抬非回退）（core/fast_track_result.py:528-539） | pass | 0/5 | - |
| wc-lift-tier-scale-threshold | 档位函数规模阈值判定：scale 严格大于阈值才抬（60>45 抬、45 等值不抬、10 不抬）、只抬不压、disabled/非法 scale 回 base（core/fast_track_result.py:556） | pass | 0/8 | - |
| wc-lift-tier-idempotent | 档位幂等契约：同 scale 重复调用结果恒定（档位入参取启动同源总规模，不以 remaining_tasks 回算的基础保证）（core/fast_track_result.py:556） | pass | 0/5 | - |

## 本轮场景集变更

当前稳定场景集共 16 个（第 1 轮）。

- 首轮写入 16 个场景

