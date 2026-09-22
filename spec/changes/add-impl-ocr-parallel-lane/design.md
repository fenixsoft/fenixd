# Design: add-impl-ocr-parallel-lane

## Context

`add-impl-code-review-gate` 交付的收尾审查把 ocr（open-code-review，外部 npm 包，经 `bin/ocr_review.py` 包装器、run 级 provider 注入）绑死在实现者 run 进程内：提示词段（`core/agent_runner/prompt_builder.py` `_impl_code_review_section`，对 implementer 与 fast-track 注入）要求收工前前台跑完审查并落盘 `code-review.json`，`core/agent_runner/result_gate.py` `_check_impl_code_review_artifact`（result_gate.py:595，调用点 :850）在同 run 结束点硬校验。ocr 单轮 20~40 分钟 vs 工具调用硬上限约 600s vs 全量回归实测 275s（`impl-add-code-review-auto-fix-1790046405` 时间线：前台 570s 截杀→后台重跑→sleep 轮询烧轮次→网关 stall 挂死 42 分钟→daemon 判死重派→中间产物作废）。

框架现状对本设计友好的既有机制：状态机 `testing → bug_found → implementing` 打回通道（`core/state_machine.py` VALID_TRANSITIONS）；维护车道形态（`core/agent_runner/maintenance_runs.py` `run_code_review`:755 / `run_regression`:1056）；run 级 ocr provider 注入（`core/agent_runner/runner.py` `_write_run_ocr_config`:1321）；tester 单飞（`tester_run` 字段）；陈旧报告指纹治理先例（仪表盘陈旧验证报告轮次指纹重合成）；文件信号/唤醒机制（scheduling kick 族）。

## Goals

- 实现者 run 的墙钟时间与 ocr 解耦：收工即结束，不再有 ocr 等待、不再有 sleep 轮询轮次。
- ocr 与测试验证并行，join 于 testing 出口；join 语义机械化、可恢复、可观测。
- ocr 慢/挂不再产生「run 挂死→重派→白跑」的失败链。
- 复用既有通道（bug_found 打回、维护车道、provider 注入、指纹治理），不新造平行机制。

## Non-Goals

- 不改 code-review agent 与仓库级周期审查车道（`run_code_review`）的既有行为。
- 不改 code-fix 自动修复车道（本设计的台账转投正是喂给它）。
- 不提升 ocr 上游审查质量/速度本身（并发缺省调整除外）。
- 不做 findings 的 AI 裁决（join 只机械分类；真伪裁量归修复轮实现者）。
- fast-track 车道不改其「单 run 实现+验证」形态，仅同 treatment 摘除内联段并接入框架侧车道。

## Decisions

### D1：ocr 车道 = 维护 run，启动时点 = merge-back 成功后的 tester 派发点

`run_impl_ocr` 对齐 `run_code_review`/`run_regression` 形态（`maintenance_runs.py` 新函数）：`_execute_agent` 之外、不占 spec 预算与 agent 轮次；run_id 前缀 `impl-ocr-`（`RUN_ID_AGENT_PREFIXES` 登记保证时间线归属）。审查对象 = 实现分支 head（merge-back 不改分支 ref，分支头在 testing 窗口内稳定；检出用 verify-serving 同款轻量 detached worktree 或直接复用为 tester 建的检出）。provider 注入复用 `_write_run_ocr_config` 同源机制（框架侧直调，不经 agent 提示词）。

理由：merge-back 成功才启动——避免为最终未合并的内容白跑审查；与 tester 同点启动——并行窗口最大化（ocr 20~40min ⊇ testing 分钟级）。

### D2：join 于 testing 出口，打回复用 BUG_FOUND 通道

`testing → verified` 的门禁自动路径增加 ocr 完成判据（产物在 + status 白名单 + 指纹新鲜）。tester 先完成 → spec 停 testing 等 ocr 完成事件唤醒（文件信号/既有唤醒机制），tester_run 单飞语义不变。gate 档下发现非 rejected findings → `testing → bug_found`（reason=ocr findings）→ implementing 修复轮——与验证失败的既有打回同通道，零新状态。ocr 修复轮计数器 `_ocr_fix_rounds` 持久化于 spec entry，上限 1：第二轮仍出的 findings 全部转台账 deferred，join 放行（防死循环，`fenix-token-waste-incident` 教训）。

### D3：gate | advisory 双档，缺省 gate

`verify.impl_code_review_mode`：gate（缺省，保守——实现者对当场产出质量负责，join 打回）；advisory（findings 一律入台账 `items.jsonl` 喂 code-fix 车道，join 永不打回）。读取器单点 + 白名单校验 + 设置页「验证」面板受管键 UI（新配置键必须带 Dashboard 界面——既有约定）。

### D4：指纹读侧 fail-closed、车道失败 fail-open 的分界

- 产物 `completed` 但 `(branch, merge_base, head_commit)` 指纹不新鲜 → **不得采信、不得放行**（fail-closed，陈旧报告洗白防线，先例：陈旧 dist verified 治理）；处置 = 车道按当前指纹重跑。
- 车道超时/非零退出/环境不可用 → `unavailable` + 非空 reason → join 放行 + WARNING 审计（fail-open，与现行「环境不可用降级照常收工」语义一致——质量审查缺位不阻塞交付，但必须留痕）。

### D5：实现者/fdt 内联段摘除与修复轮 findings 段

`_impl_code_review_section` 对 implementer/fast-track 的注入移除（开关关闭时本就零注入，现在改为该段退役）；`result_gate` 实现者门摘除 `_check_impl_code_review_artifact` 调用（函数保留供 join 侧复用其校验逻辑）。修复轮实现者提示词注入「ocr findings 修复义务」动态段：findings 清单 + disposition 契约（fixed/rejected/deferred + 非空 reason）+ 修码后重验要求（定向测试+全量回归，有界入口前台直跑）。路径语义沿用 worktree 相对路径教训（fix-impl-code-review-writepath）：修复轮产物仍写 worktree 内 `.fenix/verify-progress/<spec>/`，拷回单向 worktree→主树。

### D6：增量游标

`.fenix/verify-progress/<spec>/ocr-cursor.json`（运行时文件，不进交付声明）记 `last_reviewed_commit`；车道重跑时优先增量 `--from <cursor> --to HEAD`，cursor 缺失/非祖先回退全量。恢复续做轮因此不再全量重审。

### D7：并发缺省 2→4

实测 concurrency 2 对大 diff 明显喂不饱（570s 连第一组都没跑完）。缺省调至 4，显式配置不受影响；`--effort` 仍由框架注入不变。

## Risks

- **修码后重验成本**（gate 档）：修复轮触发定向测试+全量回归重跑（实测 275s，可接受）；轮次上限 1 封顶最坏情形。
- **join 停等期间占坑**：spec 停 testing 等 ocr 时段内不重派 tester（单飞语义保证）；ocr 完成事件驱动推进，无惰性到期风险（唤醒机制已有先例 `_wake_dispatch_after_break`）。
- **ocr 上游行为漂移**：车道内部解析对原始报告保持宽松（「具体键名以现场跑出的原始报告为准」教训延续），指纹机制兜底一切 stale 情形。
- **摘除段的存量 spec**：处于 implementing 的存量 spec 在本能力上线后自然走新车道（提示词与门同源切换），无需迁移；带旧 `code_review` 收工义务的恢复轮实现者按新车道语义收工即可（提示词已不再要求该段）。
