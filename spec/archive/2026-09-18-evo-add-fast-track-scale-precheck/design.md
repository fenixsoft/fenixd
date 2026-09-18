# 设计：fast-track 派发前规模预检与 extension 末位自动保全

## Context

fast-track 派发路径（core/pm_engine/dispatch.py fast-track 分支）的预算/extension 派生当前无任务规模输入。fix-root-init-import-shadow 实证（fenixd.log 4163/4733/5278）：同一 spec 三次 12600s 超时、第三次 91 轮仍被杀，而小 spec 单轮成功——统一档位把大任务面与大轮次 run 同规格对待。add-impl-wip-checkpoint 已提供 WIP 保全能力，但只在 run 终结时触发，extension 末位无提前保全。

## Goals / Non-Goals

- **Goals**：大任务面 spec 首次派发即获得与其规模匹配的预算档；extension 末位自动保全已完成的轮次工作。
- **Non-Goals**：不做历史轮次预测（转录盲区已由 fix-run-latency-toolresult-parser 解决）；不改 implementer 预算次数闸门（_check_impl_budget_exhausted 语义不变）；不引入预测式 LLM 评估。

## Decisions

### D1：规模预估用任务条数文件面，不用 LLM

**选择**：tasks.md 未勾选任务条数 + spec 目录 .py/.ts/.tsx 文件数作为轻量静态预估。

**理由**：零成本、确定性、可单测；LLM 预估成本高且不稳定，与预检的『廉价前置』定位不符。对照样本（fix-root-init-import-shadow tasks.md 多任务 vs fix-dispatch-wakeup-gap 单任务）验证可区分。

### D2：预检失败保守低档放行

**选择**：tasks.md 缺失/读取失败时按低档放行并 WARNING。

**理由**：预检是优化不是门禁——不可因预检失败阻塞合法派发（与 add-spec-content-integrity-gate 的 IO 异常保守放行同理由）。

### D3：末位保全挂在 agent_runner 超时监督路径

**选择**：在 fast-track 超时监督（_supervision_deadline_action 相似环节）判定『进入 extension 末位窗口』时，先调既有 commit_wip_checkpoint 再走超时收口。

**理由**：复用 add-impl-wip-checkpoint 已论证的 helper 与降级语义；触发点与超时判定同层，时序最靠近真正的数据损失点。