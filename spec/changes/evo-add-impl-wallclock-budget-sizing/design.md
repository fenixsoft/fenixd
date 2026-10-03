# 设计（add-impl-wallclock-budget-sizing）

## 现状与根因

- 墙钟构成：run_timeout_seconds＋timeout_supervision（extension_seconds/max_extensions/absolute_max_seconds）；potplayer-base 实配 9000＋1800×2，框架缺省见 core/config.py:38-45 SUPERVISION_DEFAULTS（absolute_max 7200）、runner.py:6005-6008 回退 base 3600。
- 扩容判定矩阵：core/agent_runner/liveness.py:1200-1330 _supervision_deadline_action（封顶/扩容次数 :1314-1318/流可读/零事件/LLM 活性），无 remaining_tasks 入参；timeout_extension 事件（runner.py:5464-5471）不带 remaining_tasks。
- 既有先例：fast-track higher 档 max_extensions 2→4（liveness.py:1249-1266，常量 core/config.py:50 SUPERVISION_FAST_TRACK_EXTRA_EXTENSIONS）——按规模抬续期预算的机制形状已在框架内存在，仅 impl 车道为零。
- 轮数 sizing 参照：core/fast_track_result.py:376 get_turn_budget_sizing_config、:448 suggested_turn_cap_for_scale；runner.py:6062 _impl_turn_budget 装配。
- 用量落盘点：聚合 usage 只随 CLI result 事件落盘（runner.py:5730-5733）；finally run_metrics 块（runner.py:5618-5705）kill 亦写 turns/tools/remaining_tasks，但无 token/cost 维度且 provider 逐轮 usage 恒零。
- 豁免口径：core/pm_engine/budget.py:330-345 _is_exemptable_reason 将「extension budget exhausted」列为不可豁免。

## 方案决策

1. **sizing 函数仿轮数版**：在 core/fast_track_result.py 增墙钟 sizing 配置读取与档位函数（规模阈值复用 agents.turn_budget_sizing 的 full_scale_threshold 判定形态），输出 max_extensions 抬升档位；只抬不压、缺省向后兼容；STATE 覆盖键（如 impl_wallclock_extension_override）优先。配置缺省键落 core/config.py SUPERVISION_DEFAULTS 旁。
2. **liveness 判定接入**：_supervision_deadline_action 增 remaining_tasks 入参（由 runner 超时收口 :5482-5489 传入），按 sizing 档位抬 max_extensions（泛化 :1249-1266 先例）；absolute_max_seconds 封顶不变——sizing 只扩「续期预算」，不触碰绝对上限，防失控 run 无限独占车道。
3. **evidence/事件同型扩展**：extend/kill evidence 与 timeout_extension 事件携带 remaining_tasks，与 turn_extension/轮数 kill_early 证据同型，供事后归因与扩容判定复盘。
4. **用量缺失注记而非伪数据**：finally 块在「击杀且无 CLI result」时附加用量注记（原因=provider 无逐轮上报＋transcript 字节数/轮数粗估维度），不臆造 cost 数值；成功路径（:5730-5733）行为不变。provider 侧逐轮上报列为非目标。
5. **口径复核**：budget.py:330-345 不可豁免口径在墙钟 sizing 生效后复核（仍不可豁免，避免 sizing 被当成预算放宽后豁免误判）；config.py:2327 supervision_floor 派生下限与新档位协同复核。

## 风险

- sizing 抬续期预算会拉长失控 run 的车道独占——absolute_max 封顶＋停滞判停（evo-add-run-stop-loss，缺省关闭）＋kill_early 守卫（轮数侧既有）多重兜底，实现时验证三者协同。
- remaining_tasks 入参在 kill 收口路径的取数时点可能与 context metrics 略有偏差——以 finally 块同一取数源为准，保证 evidence 与 run_metrics 一致。