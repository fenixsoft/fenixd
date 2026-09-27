# ADR-095：frozen/cancelled 让位零写入，裁决失败分型侧车

date: 2026-09-15
status: accepted

## Context

在飞 judge run 期间人工冻结 spec，重试派发被 frozen 门拦截的失败被并入「二次不合规」路径，产出假 critical 告警 + 伪 blocked + 硬编码文案；同函数内多条同型坍缩路径（异常后复读旧产物文件 / 派发失败 / 产物丢失）使归因失真。frozen 与取消旗标均为人式决策载体，自动链路不得代理其后果。

## Decision

- 裁决校验重试返回结构化 cause（violations / dispatch_frozen / dispatch_cancelled / dispatch_failed / dispatch_exception / report_missing），异常不做控制流；派发异常路径立即返回，禁止落至复读旧产物文件（假 ERROR 根除）。
- frozen / cancelled = 让位语义零写入：不 update_spec、不发任何告警，仅 INFO 留痕——spec 已在人工手里，让位路径完全不触状态机（天然规避 update_spec 带 status 键的副作用）。frozen 判定文案与 runner 门共用导出常量防漂移；取消走结构化字段非字符串匹配。
- 只有 cause=violations（重试成功返回且新产物仍违规，唯一真二次违规）产出「二次不合规」告警与 blocked；violations 明细结构化透传进告警 evidence 与 STATE。
- 失败历史侧车 `.fenix/verify-progress/<spec>/fail_history.json`：每轮裁决采纳失败原子追加 {round, cause_type, failed_scenarios}，spec 转出终态时清空；升级闸门读侧车生成分型（evidence-invalid / real-bugs / repeat）并附相邻两轮失败集 diff——「相同失败集连续出现」即无进展循环的机械可识破信号。
- 未知 cause 保守按 violations 处置并 ERROR 留痕（fail-closed 不静默放行）；侧车写盘失败静默降级、分型标 unknown 不阻断升级闸门。
- 两套轮次计数语义不同、均保留，文案显式命名（「原地打回第 N 轮」vs「升级闸门连续失败第 N 轮」）杜绝口径歧义。

## Consequences

- 人工冻结 / 取消不再产出假告警与伪终态；真二次违规的告警携带逐条 violations 明细。
- 无进展循环有了可识破依据，误置冻结类事故可被分型数据复盘。
- 结构化返回与既有校验器值分支风格统一，全库调用点单提交原子切换。
