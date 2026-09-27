<!-- knowledge: capability=deliverable-declaration-triage rev=3 sources=spec/archive/2026-09-12-add-deliverable-declaration-triage,spec/archive/2026-09-19-add-deliverable-delete-kind,spec/archive/2026-09-23-add-declaration-relocation-protocol -->

# 交付物声明对账与裁决流水线

「声明 × 仓库现实」错位的三层对账体系：晋升 lint 拦在前、派发处方教在先、守卫缺件经车道无关的裁决流水线收敛。

## 现行规则

- 车道无关统一裁决流水线：交付物缺件的裁决流水线为**陈日声明前置分类 → 预分类软化 → LLM 终审 → 机械执行 → 防洗白复检**的统一流水线；full 与 fast-track 两车道接入同源实现，不得各自维护分叉的缺件处置逻辑。输入契约为守卫的结构化返回全量（`violation ∈ {missing, undeleted, removed}`，收缩违规同源入流水线）；输出契约为 `action: proceed`（放行）或 `action: handled`（已终态处置）及处置明细。
- 晋升 lint 存在性校验（`lint_declared`）：`kind: modify` 与 `kind: reference` 的路径必须在主树存在，不存在即拒绝晋升并停留 drafted（附 error）；`kind: new` 路径不存在时做 basename 模糊匹配（排除 `.git`/`node_modules`/`dist` 等产物目录），仓库内唯一命中判疑似笔误拒绝晋升（违规消息直接给出疑似目标路径）；零命中或多命中放行（fail-open，交后续层兜底）；lint 自身故障 fail-open（返回空清单放行晋升）。
- 派发前声明现实处方：dispatch 构建实现者提示词时干跑 `extract_declared` 并对每个 `new`/`modify` 路径做主树存在性检查与 basename 匹配，将「声明清单 × 仓库现实」快照注入提示词——存在的 modify 路径标注为修改目标，不存在的路径标注并列出全部 basename 候选。注入文案约定：实现者判断声明路径系笔误时，以实际正确路径实现并在 `.fenix-run-result.json` 的 findings 登记 `deliverable-dispute`（含 element/current/suggestion），不得静默改变交付落点。快照覆盖 `kind: delete` 条目：路径在主树存在 → 标注删除目标确认；不存在 → 标注疑似笔误并列候选；delete 条目保留 `kind` 字段。无声明段或干跑异常时跳过注入（fail-open）。
- 守卫缺件 LLM 终审：守卫判缺件后、打回/重派前，两车道派轻量单轮 judge run（前缀 `dispute-judge-`，主树只读上下文、无 worktree），输入含缺件清单、spec 语境摘录、实现 run findings、全部缺件路径的 basename 候选。judge 输出固定契约裁决 JSON（顶层 `status: "success"` + `verdicts` 数组，每项含 `element`/`verdict`（`typo`|`reference`|`missing`|`unclear`）/`actual_path`/`reasoning`/`confidence`）。终审进行期 spec 置 blocked（error 注明「LLM 终审进行中」）以阻断重派竞态；judge 失败、超时或输出不合法等价 `unclear`。前置分类先行：陈日分类与预分类软化先于 judge 执行，全清则放行且不派 judge。
- 裁决机械执行：`typo` → 将生效声明对应条目 path 确定性替换为 `actual_path`（同名去重；命中陈日信号须满足重定位凭据三要素；生效声明已无该条目时按 `declaration-relocation-protocol` 凭据登记落册，不因条目缺失卡死）→ 重跑守卫对账；`reference` → 条目 kind 置为 `reference` 移入软校验 → 继续推进；`missing` → 既有打回/重派路径（带精准缺件清单）；`unclear` → dispute blocked 转人工。
- 执行目标与提交：声明改写作用于**生效声明所在位置**（经统一解析入口决定：worktree 内文件 → 分支 → 主树回退）；改写在实现分支上提交（worktree 存在时 `git -C <worktree> commit` 固化；worktree 已清理时经 `worktree_manager` 重挂该分支 worktree、提交后移除），不得仅写文件不提交，不得 `git -C <project_root> commit` 直提（该命令提交到主树当前分支）。主树对齐由 merge-back 携带分支提交自然完成，不另行单独写主树声明。
- 审计留痕：每条裁决的执行落 dispute 审计流（裁决 JSON 全文、修正前后 diff、run 关联 id、时间戳），人工可复核；人工回滚 = 恢复声明段原文 + 触发重派。无对应人工裁决记录时，任何缺件不得被静默放行。
- `delete` 裁决归宿收窄：LLM 终审对 `kind: delete` 条目拒绝 `reference` 归宿（`reference` 语义是转为仅审计不再硬校验，施加于 delete 即让删除要求静默消失）；judge 给出 `reference` 时机械执行层改写为 `unclear` 转人工并留审计痕迹（保留 judge 原始 verdict 与改写事实）。delete 条目可用归宿为 `typo`/`missing`/`unclear`。
- 违规话术按 kind 分化：结构化条目贯穿 dispute 匹配、终审输入与重派话术三处消费点——`undeleted` 表述为「未删除该路径」语义，`missing` 维持「缺件」语义；对 `delete` 条目不得使用「缺件」表述（文件明明存在，该表述误导人工阅读与 judge 归因）。
- 预算对齐：两车道的缺件重派预算计数与封顶语义同源——经流水线确认缺失（`missing`/`unclear` 转打回）的轮次计数与封顶阈值与既有重派路径一致，不丢失不重复计数；重定位与软化（非重派归宿）不消耗重派预算。

## 溯源

- 2026-09-12 2026-09-12-add-deliverable-declaration-triage — 建立三层对账：晋升 lint 存在性校验、派发前声明现实处方注入、守卫缺件 LLM 终审与裁决机械执行审计
- 2026-09-19 2026-09-19-add-deliverable-delete-kind — 处方覆盖 `delete` 条目（双形态标注）、delete 裁决归宿收窄（拒 reference）、违规话术按 kind 分化
- 2026-09-23 2026-09-23-add-declaration-relocation-protocol — 收敛为车道无关统一裁决流水线（结构化全量输入、action 输出）、fast-track 同源接入终审、执行目标改为生效声明所在层 + 分支提交、预算对齐
