# degrade-annotation Specification

## ADDED Requirements

### Requirement: 降级合成报告标注降级原因与代价

新验证流程（planner 出题→judge）降级到 legacy verifier 后，若最终验证报告由框架合成（报告文件缺失时的合成路径），报告 SHALL 携带降级标注：降级原因（planner 阶段失败归因，如「Planner 未生成有效场景，status=不可读(missing)」）与被降级轮次的代价（planner run 时长与成本）。降级上下文由 pm_engine 阶段1 降级判定点采集（`plan_result.duration_seconds`、cost、失败归因文案）并传递至 `verify_report` 合成路径。无降级发生的正常报告 SHALL NOT 携带该标注（字段缺省不渲染）。

#### Scenario: 降级后合成报告携带标注

- **WHEN** 新验证流程 planner 阶段失败（如 2026-09-09 事故：status=None 降级），legacy verifier 跑完且报告文件缺失由框架合成
- **THEN** 合成报告包含降级标注：降级原因文本 + 被降级 planner run 的时长（分钟）与成本（美元），验证报告页/报告数据结构可见该标注

#### Scenario: 正常新验证流程报告无降级标注

- **WHEN** 新验证流程全链成功（planner 出题→judge 裁决），报告正常产出
- **THEN** 报告不携带降级标注（字段缺省），前端渲染无降级提示

#### Scenario: 标注随报告数据结构持久化

- **WHEN** 降级合成报告落盘 report.json
- **THEN** 降级标注字段随 report.json 持久化（非仅日志），后续读取报告（时间轴/报告页/CLI）能还原降级事实与代价
