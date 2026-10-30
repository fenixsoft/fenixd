# design

- 裁决权威：daemon run_metrics 终态（_run_terminal_success，core/self_review.py:556）已存在并被 signal= 守卫消费，直接复用；不新增数据源。
- 扩界点：_is_phantom_signal_failure（core/self_review.py:580-590）改为三分支形态判定——detail 前缀 signal=（现状）、detail 为 Exit code/CLI 错误形态（新增）、marker= 命中（新增，需把样本侧 collect_failed_run_samples 对 marker= 的排除同步放开）；docstring（:586-588）同步改写为「daemon 终态权威裁决」。
- 消费点：计数侧 collect_runs_stats（:695-700）与样本侧 collect_failed_run_samples（:777-784）共用同一谓词，改谓词即两侧同时生效；告警复用 :593 的幻影告警通道，kind=self_review_phantom_failure。
- 指标透传：登记点在 core/agent_runner/maintenance_runs.py:1500-1517（run_evolution 产物直读分支，run_ok=True 处），从档案 result 事件读 total_cost_usd 与轮次（context metrics 行 turns），传入既有 run_metrics 写入调用；读取失败时保持现状记 0 并 DEBUG 留痕，不阻塞落地主链。
- 保守性：查无 run_metrics 行（索引缺失/档案缺失）一律保持 failed，与 tests/test_self_review_terminal_crosscheck.py:269 既有语义一致；daemon=error 反例（:311）不得回归。
- 测试：tests/test_self_review_terminal_crosscheck.py 新增三夹具（error+success 否决、marker+success 否决、error+无账面行保持），夹具形态取自 evo-1792692791 档案真实尾行。