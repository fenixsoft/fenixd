# deliverable-declaration-triage — 增量规格（车道无关裁决流水线）

## ADDED Requirements

### Requirement: 裁决流水线车道无关

交付物缺件的裁决流水线（陈日声明前置分类 → 预分类软化 → LLM 终审 → 机械执行 →
防洗白复检）MUST 为**车道无关**的统一流水线，full 车道与 fast-track 车道 MUST
接入同源实现，MUST NOT 各自维护分叉的缺件处置逻辑。

流水线 MUST 以统一的输入契约（spec 名、实现结果、缺件清单、声明上下文）与统一的
输出契约（`action: proceed | handled` 及处置明细）供两车道调用。**输入契约的
「缺件清单」MUST 为守卫的结构化返回全量**（`violation ∈ {missing, undeleted,
removed}`，见 `implementer-deliverable-gate`）——收缩违规（`removed`）与缺件同源
入流水线，MUST NOT 被排除在车道无关处置之外。

#### Scenario: full 与 fast-track 共用同源流水线

- **WHEN** full 车道或 fast-track 车道判定缺件
- **THEN** 二者调用同一裁决流水线入口
- **AND** 陈日前置分类、预分类软化、终审、机械执行、防洗白复检的行为对两车道一致

#### Scenario: 输出契约为车道无关的 action

- **WHEN** 流水线完成一次缺件处置
- **THEN** 返回 `{"action": "proceed"}`（放行）或 `{"action": "handled"}`（已终态处置）
- **AND** 车道调用方按 action 决定 merge 推进或直接 return

### Requirement: fast-track 车道接入 LLM 终审

fast-track 车道判定缺件后 MUST NOT 直接落入「缺件 → 打回重派」（当前行为）；MUST
接入与 full 同源的 LLM 终审与机械裁决通道：命中陈日信号的缺件走重定位、可软化的
走预分类软化、判据不明的转 LLM 终审、确认缺失的方走既有重派。

fast-track 的终审进行期状态处置、judge run 前缀与输出契契约 MUST 与 full 车道一致。

#### Scenario: fast-track 缺件走终审而非直落重派

- **WHEN** fast-track 实现 agent 报成功但生效声明判定缺件
- **THEN** 缺件进入 LLM 终审/机械裁决通道（与 full 同源）
- **AND** MUST NOT 直接按缺件重派

#### Scenario: fast-track 陈日声明走重定位

- **GIVEN** fast-track 车道缺件路径在基线树已被上游删除（陈日信号命中）
- **WHEN** 处置缺件
- **THEN** 走重定位通道（替换为分支存在的替代路径）并审计留痕
- **AND** MUST NOT 因该陈日缺件重派

### Requirement: 双车道缺件处置预算对齐

两车道的缺件重派预算计数与封顶语义 MUST 对齐：经流水线确认缺失（`missing`/`unclear`
且转打回）的轮次计数与封顶阈值 MUST 与既有重派路径同源，MUST NOT 因接入流水线而
丢失或重复计数；重定位与软化（非重派归宿）MUST NOT 消耗重派预算。

#### Scenario: 重定位不消耗重派预算

- **WHEN** 某轮缺件经重定位放行
- **THEN** 该轮 MUST NOT 递增缺件重派计数

#### Scenario: 确认缺失正常计数与封顶

- **WHEN** 某轮缺件经终审确认 `missing` 走重派
- **THEN** 该轮正常递增重派计数
- **AND** 达到封顶阈值时按既有语义转 blocked

## MODIFIED Requirements

### Requirement: 守卫缺件 LLM 终审

收工守卫（`_deliverable_gate_missing`）判定缺件后、执行打回/重派前，**两车道**
MUST 派轻量单轮 judge run（复用既有 planner-judge 范式，run 前缀 `dispute-judge-`，
主树只读上下文、无 worktree），输入 SHALL 包含：缺件清单、spec 语境摘录
（proposal/design/tasks 相关段落）、实现 run 的 `.fenix-run-result.json` findings、
全部缺件路径的 basename 模糊匹配候选。judge 输出为固定契约裁决 JSON
（`.fenix-run-result.json`：顶层 `status: "success"` + `verdicts` 数组，每项含
`element`/`verdict`（`typo`|`reference`|`missing`|`unclear`）/`actual_path`/
`reasoning`/`confidence`）。终审进行期间 spec SHALL 置 blocked（error 注明
「LLM 终审进行中」）以阻断重派竞态；judge run 失败、超时或输出不合法 SHALL
等价于 `unclear`。

**前置分类**：进入 judge 之前，陈日声明确定性分类与预分类软化 SHALL 先行执行；
全清则放行且不派 judge。`typo` 裁决对陈日声明 SHALL 复用重定位协议（凭据三要素
齐备方改写，见 `declaration-relocation-protocol`）。

#### Scenario: 缺件触发终审而非立即打回

- **WHEN** 收工守卫判定缺件 `[core/verification.py]` 且实现 run 未登记该缺件的 dispute
- **THEN** daemon 派 `dispute-judge-` run 并把 spec 置 blocked（error 注明终审中），
  不立即打回重派

#### Scenario: fast-track 缺件同源触发终审

- **WHEN** fast-track 车道收工守卫判定缺件
- **THEN** daemon 同样派 `dispute-judge-` run 并置 blocked
- **AND** 行为与 full 车道一致

#### Scenario: judge 失败等价 unclear

- **WHEN** judge run 写出 `status: "error"` 或超时未产出合法裁决 JSON
- **THEN** 全部待裁缺件按 `unclear` 处理，走既有 dispute 转人工通道

### Requirement: 裁决机械执行与审计留痕

daemon 消费合法裁决 JSON 后 SHALL 机械执行（不经 agent 手改文档）：
`typo` → 将**生效声明**对应条目的 `path` 确定性替换为 `actual_path`（若同名
条目已存在 actual_path 则去重；命中陈日信号时须满足重定位凭据三要素；若生效声明
已无该条目——实现方先行对齐——则按 `declaration-relocation-protocol` 的**凭据
登记**落册，MUST NOT 因条目缺失卡死）→ 重跑守卫对账 → 通过则正常合并推进；`reference` → 将该条目 `kind` 改为 `reference`（移入
references 软校验）→ 继续推进；`missing` → 走既有打回/重派路径（带精准缺件清单）；
`unclear` → 既有 dispute blocked 转人工通道。每条裁决的执行 SHALL 落 dispute
审计流（裁决 JSON 全文、修正前后 diff、run 关联 id、时间戳），人工可复核；人工
回滚 = 恢复声明段原文 + 触发重派。无对应人工裁决记录时，任何缺件 MUST NOT 被
静默放行。

**执行目标**：声明改写 SHALL 作用于**生效声明所在位置**（经统一解析入口决定：
worktree 内文件 → 分支 → 主树回退）。改写 MUST 在**实现分支上提交**（worktree 存在
时以 `git -C <worktree> commit` 固化；worktree 已清理时经 `worktree_manager` 重新
挂载该分支的 worktree、提交后移除），MUST NOT 仅写文件不提交，也 MUST NOT 用
`git -C <project_root> commit` 直提（该命令提交到主树当前分支，非实现分支）。主树
对齐由 merge-back 携带分支提交自然完成（`git merge <branch>` 只搬运分支提交，未提交
的 worktree 改动不会被带入主树），故 MUST NOT 另行单独写主树声明——消除「分支已改、
主树仍旧」的错层复发。

#### Scenario: typo 裁决自动修正声明并放行

- **WHEN** judge 裁决 `core/verification.py` 为 `typo`、`actual_path` 为
  `core/pm_engine/verification.py`、confidence 高
- **THEN** daemon 将生效声明段 path 替换为 actual_path，审计流落 diff，
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
