# run 时间轴 agent 标签映射

<!-- knowledge: capability=run-visual-agent-labels rev=1
     sources=spec/knowledge/_inbox/done/distill-econnreset-misattrib-recover-sweep-race.md -->

dashboard run 流事件（SPEC 时间轴、活动记录、run 弹窗）中的 agent 身份显示由 `runVisual.ts` 的两张映射表承担：agent 名经 `AGENT_LABEL` 解析显示名、run_id 前缀经 `RUN_ID_PREFIX_LABEL` 解析车道标签；未收录条目一律回退显示「未知 Agent」。

## 规则

- 新 agent 车道上线必须同步登记 `AGENT_LABEL` 与 `RUN_ID_PREFIX_LABEL` 两表（中文名 + run_id 前缀）并配套前端单测用例；漏登记车道的 run 在时间轴与活动记录中一律显示「未知 Agent」。
- 登记纪律与生命周期序枚举同型（见 [spec-timeline-accuracy](spec-timeline-accuracy.md)）：映射表晚于车道建设即漏登记；新增车道或 run 前缀引入时，排查前端按车道/前缀枚举分支的全部显示表一并登记，不得依赖运行期「未知 Agent」回退兜底。
- `knowledge-distiller` 车道显示名「知识蒸馏 Agent」、run_id 前缀标签同表收录，配套 `runVisual.test.mjs` 用例覆盖。

## 溯源

- 2026-11-04 distill-econnreset-misattrib-recover-sweep-race（spec/knowledge/_inbox/done/distill-econnreset-misattrib-recover-sweep-race.md） — 新建本页：AGENT_LABEL/RUN_ID_PREFIX_LABEL 登记纪律（漏登记车道 run 回退「未知 Agent」，arbiter 与 knowledge-distiller 两起同型先例）；knowledge-distiller 车道补登记为交互会话原地修复（显示名 + 前缀标签 + 配套单测）
