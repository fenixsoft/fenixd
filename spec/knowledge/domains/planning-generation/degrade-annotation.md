# 验证降级报告注解（degrade-annotation）

<!-- knowledge: capability=degrade-annotation rev=1
     sources=spec/archive/2026-09-16-add-planready-artifact-gate -->

新验证流程降级 legacy verifier 后框架合成报告的留痕机制：降级事实与代价随报告持久可见，合成报告必带降级标注。

## 规则

- 新验证流程（planner 出题→judge）降级到 legacy verifier、且最终验证报告由框架合成（报告文件缺失时的合成路径）时，报告携带降级标注：降级原因（planner 阶段失败归因文本）与被降级轮次的代价（planner run 时长与成本）。
- 降级上下文由 pm_engine 阶段1 降级判定点采集（`plan_result.duration_seconds`、cost、失败归因文案），并传递至 `verify_report` 合成路径。
- 降级标注字段随 report.json 持久化（非仅日志）；时间轴、验证报告页、CLI 读取报告时可还原降级事实与代价。
- 无降级发生的正常报告不携带标注：字段缺省不渲染，前端无降级提示。

## 溯源

- [2026-09-16 2026-09-16-add-planready-artifact-gate](spec/archive/2026-09-16-add-planready-artifact-gate/) — 新增降级合成报告的标注契约（降级原因 + 被降级轮次代价，采集点、持久化与缺省不渲染）。
