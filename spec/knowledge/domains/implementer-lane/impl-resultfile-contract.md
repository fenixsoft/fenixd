<!-- knowledge: capability=impl-resultfile-contract rev=1 sources=spec/archive/2026-09-22-fix-impl-resultfile-contract-gap -->

# 实现者车道结果文件契约

实现者双车道与框架之间关于 `.fenix-run-result.json` 的完整契约：提示词可见的硬门约定、重试轮死因继承、正文 JSON 捞回与缺失归因。

## 现行规则

- 契约段注入：`implementer`（full）与 `fast-track` 两条实现者车道的派发提示词各自包含结果文件硬门契约段，至少声明——本次 run 的成功判定 = 进程正常退出 **且** 结果文件（`<worktree>/.fenix-run-result.json`）已落盘且为可解析的非空 JSON；收工前未写/文件为空/非法 JSON → 判失败并走原地退避重试（整轮 token 重烧）；**正文里的 JSON 不算交付**（框架不解析回复正文，只读文件）；**先落盘再深入**（先写最小可判结果文件，再做全量回归/交付物核实等收尾）。
- 等待编排约束：实现者车道无定时唤醒节拍（`ScheduleWakeup` 在非交互派发下不产生唤醒），但后台 Bash 任务的完成通知真实可用；可能超过 600s 工具上限的长任务用**一次** `run_in_background: true` 启动（存在 600s 内必然返回的有界入口时优先前台直跑），然后等完成通知或做无数据依赖的独立工作；不得用 `sleep`/周期性 `ps` 轮询模拟等待，不得启动即忘。
- 契约段路径按车道分派：实现者车道取该 run 的 worktree 根 `<worktree>/.fenix-run-result.json`；planner-plan/planner-judge/spec-review 三车道维持既有路径语义（如 `.fenix/verify-progress/<spec>/.fenix-run-result.json`）。
- 重试轮继承真实死因：实现者车道被重派时，提示词「上轮失败上下文」携带两类来源——状态机 `error` 字段与上一轮执行器结构化诊断 `_impl_diagnosis`（`terminal`/`attribution`/`conclusion`/`progress`）。两类来源均可达（`error` 为空但诊断存在时，诊断字段仍注入）；同一诊断字段在单次 prompt 中只渲染一次（字段级去重：`_prev_error_section` 只渲染 `error` 原文，`_impl_diagnosis_section` 是唯一把诊断字段作为独立条目渲染的段；`error` 原文包含 `attribution` 子串系同源写入，不计为重复）；因「结果文件缺失」重派的轮次，契约段使 agent 明确得知该死因而非仅「任务未完成」。首次派发无任何上下文时不注入空段。
- 结果文件捞回：实现者车道 run 正常收工但从未写结果文件时，若转录末轮 assistant 文本含合法结果 JSON（fenced 代码块，`status` ∈ 实现者白名单 `{success, partial, error}`），框架代写落盘到 `<worktree>/.fenix-run-result.json`，把「整轮白烧重派」降为零成本回收。约束：目标文件已存在不覆盖；抽不出合法 JSON/白名单外不落盘（交硬门按既有语义判失败）；转录缺失/不可读不落盘且不抛异常；落盘视图与 agent 自写产物同构（顶层含 `spec` 戳）；捞回时点早于 worktree→主树产物拷回（使既有 `role`/`spec` 戳注入与主树副本写入同样生效）；捞回写可观测日志（含 spec/run_id/status）。spec-review 车道既有捞回语义（路径、白名单）保持不变。
- 缺失归因二分：因结果文件缺失判失败时，error 归因复用终态机械特征（读转录末轮 assistant 文本，零 LLM 纯文本匹配）区分两类死法——含假工具调用特征（`<function_calls>`/`<tool_use`/`<parameter`/markdown fenced 工具名）→「格式回退截断」；无特征 →「未收工即停」。归因只用于日志/告警语义区分，不改变处置路径（两者原地重试与 resume 行为相同）；转录缺失/损坏时降级为「未收工即停」且不抛异常。

## 溯源

- 2026-09-22 2026-09-22-fix-impl-resultfile-contract-gap（spec/archive/2026-09-22-fix-impl-resultfile-contract-gap） — 补齐实现者双车道契约段注入、路径按车道分派、重试轮真实死因继承（两源可达 + 字段级去重）、正文 JSON 捞回与缺失归因二分
