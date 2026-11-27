# narrative-investigation-upgrade Spec

## REMOVED Requirements

### Requirement: 按 signal_type 的证据采集
**Reason**: 生成链整体退役（用户决策不再派 Agent 生成调查报告），证据采集仅服务于叙事生成，无保留对象。
**Migration**: 采集器与 prompt 注入逻辑随 `core/adjudication_narrative.py` 退役删除；`spec/changes/<spec>/verification-report.md` 等产物仍由其所属能力正常产出，不受影响。

### Requirement: 四段叙事结构
**Reason**: 无生成即无输出结构；四段校验随生成链退役。
**Migration**: 无迁移；历史侧车中的三段/四段文本均按普通 Markdown 原样渲染。

### Requirement: 异步补叙（告警零阻塞落盘）
**Reason**: 生成链退役后不存在补叙任务；告警发射点回归零后台叙事线程。读侧侧车合并语义保留（迁移至 adjudication-alert-narrative MODIFIED「前端告警区渲染叙事」约束）。
**Migration**: 拆除发射点后台生成线程与原子补写调用；`.fenix/admin_alerts_narrative/` 历史侧车文件保留只读合并，告警清理时级联删除行为不变；叙事让位判定（链头派发 vs 直达人工队列）语义迁出叙事模块、随 escalation 链路保留。

### Requirement: 连续失败熔断
**Reason**: 无生成即无失败熔断面。
**Migration**: 无迁移；熔断器随模块退役删除。
