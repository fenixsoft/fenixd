## 2026-09-06

### 可改进
- {'impact': '中断 run 永久漏记终态 + verify 尝试计数跨重启清零：当日 5 run 中 3 个「在跑/无终态」（60%），其中 2 个实为已死 run 将永远停留该状态污染后续聚合；三次连续派发均打 attempt 1/3，毒 spec 可借反复重启绕过 3 次上限无限重验（复发敞口：每轮白白消耗一次完整验证 ≈32 分钟 / 3.2M cache-read token）。', 'evidence': '框架聚合「在跑/无终态: 3」，其中 planner-judge-…-1788625917/1788627192 已确认被 SIGKILL；fenixd.log 行 41440/41513/41598 三次均印「(attempt 1/3)」。', 'suggestion': 'daemon 关停路径对在途 run 补写 interrupted 终态（run 文件尾 + STATE），verify attempt 计数持久化进 STATE（参照 _impl_run_budget_used 的持久化方式）。'}

- {'impact': 'pushed→pushed 幂等自迁移被记为 ERROR 假告警：今日唯一 ERROR 即此类噪声，历史已累计 40 次（8 月下旬 27 次、9 月以来 13 次），基本每次归档必触发，稀释 ERROR 聚合信噪比（复发敞口：每归档一个 spec 产生 1 条 ERROR 噪声）。', 'evidence': 'fenixd.log 09-05T17:33:05「Invalid transition: add-planner-efficiency pushed → pushed」与 STATE 更新同秒；全量 grep 同型 40 条（state_machine）。', 'suggestion': '状态机将 pushed→pushed 判为幂等自迁移降级 INFO/DEBUG，或按 _merge_fp/事件指纹去重，ERROR 仅保留给真实非法迁移（如 ready→verified 竞态）。'}
