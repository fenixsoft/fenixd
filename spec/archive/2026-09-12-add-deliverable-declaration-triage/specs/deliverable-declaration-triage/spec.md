# deliverable-declaration-triage — 交付物声明三层对账

## ADDED Requirements

### Requirement: 晋升 lint 存在性校验
晋升 lint（drafted → ready，`lint_declared`）SHALL 对 Deliverables 声明段执行
「声明路径 × 仓库现实」存在性校验，与既有形态规则（占位符/目录声明）同层：
`kind: modify` 与 `kind: reference` 的路径 MUST 在主树存在，不存在即拒绝晋升并
停留 drafted（附 error）；`kind: new` 路径在主树不存在时 SHALL 做 basename 模糊
匹配（排除 `.git`/`node_modules`/`dist` 等产物目录），仓库内唯一命中时判疑似
笔误拒绝晋升，违规消息 MUST 直接给出疑似目标路径；零命中或多命中 SHALL 放行
（fail-open 取向，交由后续层兜底）。lint 自身故障 SHALL fail-open（返回空清单
放行晋升）。无声明段的存量 spec 不在 lint 职责内（行为不变）。

#### Scenario: modify 路径不存在被拦
- **WHEN** 声明段含 `- {path: core/verification.py, kind: modify}` 且主树无该文件
- **THEN** drafted → ready 晋升被拒绝，spec 停留 drafted，error 含该路径与「必须存在」语义

#### Scenario: new 路径唯一 basename 命中判疑似笔误
- **WHEN** 声明段含 `- {path: core/verification.py, kind: new}` 且主树无该文件，
  但 `core/pm_engine/verification.py` 是仓库内唯一 basename 命中
- **THEN** 晋升被拒绝，违规消息给出疑似目标 `core/pm_engine/verification.py`

#### Scenario: 多命中与零命中放行
- **WHEN** `kind: new` 声明路径不存在且 basename 在仓库命中多个文件（或零命中）
- **THEN** lint 放行晋升（不拦截），该矛盾由派发处方与守卫终审层兜底

#### Scenario: reference 路径不存在被拦
- **WHEN** 声明段含 `- {path: third-party/manifest.json, kind: reference}` 且主树无该文件
- **THEN** 晋升被拒绝（reference 语义即既有引用，不存在即声明有错）

### Requirement: 派发前声明现实处方注入
dispatch implementer 构建提示词时，若 SPEC 存在 Deliverables 声明段，SHALL 干跑
`extract_declared` 并对每个 `new`/`modify` 声明路径做主树存在性检查与 basename
匹配，将「声明清单 × 仓库现实」快照注入实现者提示词：存在的 modify 路径标注为
修改目标；不存在的路径标注并列出全部 basename 命中候选（若有）。注入文案 MUST
约定：实现者判断声明路径系笔误时，以实际正确路径实现并在
`.fenix-run-result.json` 的 findings 登记 `deliverable-dispute`（含 element/
current/suggestion），MUST NOT 静默改变交付落点。无声明段或干跑异常时 SHALL
跳过注入（fail-open，不阻塞派发）。

#### Scenario: 疑似笔误候选随任务书注入
- **WHEN** 实现者被派出且声明段含主树不存在的 `core/verification.py`，
  basename 命中 `core/pm_engine/verification.py`
- **THEN** 实现者提示词含「声明 core/verification.py 在主树不存在，疑似目标
  core/pm_engine/verification.py」及 deliverable-dispute 登记约定

#### Scenario: 干跑异常不阻塞派发
- **WHEN** 处方干跑抛出异常（如 spec 目录读取失败）
- **THEN** 派发照常进行，提示词不含声明现实快照段

### Requirement: 守卫缺件 LLM 终审
收工守卫（`_deliverable_gate_missing`）判定缺件后、执行打回/重派前，daemon SHALL
派轻量单轮 judge run（复用既有 planner-judge 范式，run 前缀 `dispute-judge-`，
主树只读上下文、无 worktree），输入 SHALL 包含：缺件清单、spec 语境摘录
（proposal/design/tasks 相关段落）、实现 run 的 `.fenix-run-result.json` findings、
全部缺件路径的 basename 模糊匹配候选。judge 输出为固定契约裁决 JSON
（`.fenix-run-result.json`：顶层 `status: "success"` + `verdicts` 数组，每项含
`element`/`verdict`（`typo`|`reference`|`missing`|`unclear`）/`actual_path`/
`reasoning`/`confidence`）。终审进行期间 spec SHALL 置 blocked（error 注明
「LLM 终审进行中」）以阻断重派竞态；judge run 失败、超时或输出不合法 SHALL
等价于 `unclear`。

#### Scenario: 缺件触发终审而非立即打回
- **WHEN** 收工守卫判定缺件 `[core/verification.py]` 且实现 run 未登记该缺件的 dispute
- **THEN** daemon 派 `dispute-judge-` run 并把 spec 置 blocked（error 注明终审中），
  不立即打回重派

#### Scenario: judge 失败等价 unclear
- **WHEN** judge run 写出 `status: "error"` 或超时未产出合法裁决 JSON
- **THEN** 全部待裁缺件按 `unclear` 处理，走既有 dispute 转人工通道

### Requirement: 裁决机械执行与审计留痕
daemon 消费合法裁决 JSON 后 SHALL 机械执行（不经 agent 手改文档）：
`typo` → 将 tasks.md 声明段对应条目的 `path` 确定性替换为 `actual_path`（若同名
条目已存在 actual_path 则去重）→ 重跑守卫对账 → 通过则正常合并推进；
`reference` → 将该条目 `kind` 改为 `reference`（移入 references 软校验）→ 继续
推进；`missing` → 走既有打回/重派路径（带精准缺件清单）；`unclear` → 既有
dispute blocked 转人工通道。每条裁决的执行 SHALL 落 dispute 审计流（裁决 JSON
全文、修正前后 diff、run 关联 id、时间戳），人工可复核；人工回滚 = 恢复声明段
原文 + 触发重派。无对应人工裁决记录时，任何缺件 MUST NOT 被静默放行。

#### Scenario: typo 裁决自动修正声明并放行
- **WHEN** judge 裁决 `core/verification.py` 为 `typo`、`actual_path` 为
  `core/pm_engine/verification.py`、confidence 高
- **THEN** daemon 将 tasks.md 声明段 path 替换为 actual_path，审计流落 diff，
  守卫重跑对账通过后正常合并，不重派、不烧新一轮实现

#### Scenario: reference 裁决软化校验
- **WHEN** judge 裁决某缺件为 `reference`（运行时写入目标，非本仓库交付物）
- **THEN** daemon 将该条目 kind 改为 reference 并审计留痕，该路径转为软校验，
  实现成果正常推进

#### Scenario: unclear 裁决转人工
- **WHEN** judge 裁决为 `unclear` 或裁决 JSON 不合法
- **THEN** spec 保持 blocked，error 沿用既有 deliverable-dispute 人工裁决话术，
  不自动重派

#### Scenario: 审计可复核
- **WHEN** 任意 judge 自动裁决（typo/reference）执行完毕
- **THEN** dispute 审计流含裁决 JSON 全文、声明段修正前后 diff 与触发 run id，
  人工可据其回滚
