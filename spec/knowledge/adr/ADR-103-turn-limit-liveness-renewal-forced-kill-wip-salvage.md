# ADR-103：轮次上限活性续期矩阵，强杀收口接 WIP 保全

date: 2026-09-17
status: accepted

## Context

turn-limit（Max turns reached）强杀是三不管死法：未提交现场不保全、健康推进被无差别腰斩（实证第 378 轮仍在正常勾选任务）、消耗按零记账。超时路径已有「extend 有据、封顶有限、每次留痕」的封闭续期矩阵先例；WIP 检查点已有排水 / 瞬断退避两个锚点，共用「可证明静默窗口」前提。

## Decision

- turn-limit 命中不再无条件 kill：按封闭矩阵判定——run 表现真实推进活性（判定窗口内分支有新提交，**或**有新 tool_result 事件流量，任一即活性）且续期未封顶 → 按固定步长（max_turns 的 25%）extend 上限量，以 `turn_extension` 事件落 run 文件留痕（含序号 / 步长 / 证据摘要 / 新上限）；无活性或封顶才 kill。与超时矩阵同构但计数相互独立、事件 type 分流，读侧零改动。
- 强杀收口点接 WIP 保全（新锚点）：调用点钉在「proc 终止 + 读线程 join 后」——可证明 agent 不再写盘的静默窗口，与既有锚点同前提；kill 前提交被否决（agent 尚在写盘，会提交半写文件）。turn-limit 与 timeout 两条强杀路径共用同一收口方法。
- 强杀路径消耗记账区分「unobserved」与「zero」：usage 不可观测时打 unobserved 标识，日志不得写「counted as 0」；STATE 累计保持不伪造原则——无可展示的真实数字就不展示，不新增展示字段。

## Consequences

- 健康长任务不再被腰斩；无活性 run 一次续期都拿不到。最坏墙钟增幅有界（步长 25% × 封顶 2 次，仅对真活性 run 发生）。
- WIP 保全窗口族扩展到强杀收口；锚点产生的 `fenix(wip):` 提交由 merge-back 前既有塌缩机制清理，零新增塌缩逻辑。
- 活性判定引入的 git 子进程调用只在触发判定时执行，不进常规轮询周期。
