# quality-gates-progress 能力增量（add-quality-gates-visibility）

> 质量门禁进展的可观测性契约：implementer 收尾自查 3 项逐项渐进落盘 `.fenix/verify-progress/<spec>/quality-gates.json`，Dashboard 读侧与框架判定（run 终态、STATE 状态、ocr 异步车道产物）合成为统一的 6 道门禁状态，在 spec 详情页以任务清单同款勾选列表 + 从零走的进度条展示。纯可观测性增强，不新增/放宽任何门禁判定。

## ADDED Requirements

### Requirement: quality-gates.json 落盘契约（键名固化）

implementer 收尾检查阶段 MUST 将 run 内自查 **3 项**结果写入 worktree 内 `.fenix/verify-progress/<spec>/quality-gates.json`，文件 MUST 为 UTF-8 JSON，顶层结构固定为 `{"gates": {<gate-id>: {"status": <枚举>, ...详情键}}, "updated_at": "<UTC ISO8601>"}`。gate-id 全集与顺序固化为：`full-suite`（全量回归测试）、`frontend-build`（前端构建与类型检查）、`interaction-contract`（交互契约自查）。status 枚举固化四值：`passed`/`failed`/`running`/`skipped`；未写入的 gate-id 由读侧视为 `pending`。详情键：`full-suite` 可附 `passed`/`failed` 计数，`frontend-build` 的 `skipped` MUST 附非空 `reason`。**`code-review`（ocr 代码审查与处置）不在落盘契约之内**——实现者 run 不再内联跑 ocr（add-impl-ocr-parallel-lane），该门由读侧从 ocr 异步车道产物合成（见「读侧合成」Requirement）；implementer MUST NOT 向本文件写 `code-review` 键（写了也被读侧忽略）。键名 MUST 与本契约逐字一致（历史 impl-code-review-gate 键名漂移事故教训，禁止同义改写）。该文件随既有 verify-progress 目录拷回机制在 run 结束时落主树，runner 侧 MUST NOT 为此新增拷贝逻辑（同目录自动覆盖）。落盘要求属 prompt 软约束：`core/agent_runner/prompt_builder.py` 的 implementer 收尾检查注入段 MUST 包含本契约的路径、schema 与渐进更新要求，并明确「frontend-build 仅涉前端改动时执行，否则写 skipped+reason」，以及「写入前先创建 `.fenix/verify-progress/<spec>/` 父目录（mkdir -p 语义）」——`.fenix/` 运行时目录经 .gitignore（`.fenix/*`）不入库，新建 worktree 不保证已存在该子目录，缺此指示时漏写概率显著上升（fail-open 只会静默表现为 UI 无记录）。

#### Scenario: 完成一项检查即渐进落盘

- **WHEN** implementer 在收尾阶段跑完全量回归（前端构建与交互契约自查尚未开始）
- **THEN** worktree 内 `.fenix/verify-progress/<spec>/quality-gates.json` 已存在且 `gates["full-suite"].status == "passed"`（附计数），此时 `gates` 中无 `frontend-build`/`interaction-contract` 键（读侧该两条目为 pending）

#### Scenario: 无前端改动时 frontend-build 记 skipped

- **WHEN** 某 run 的改动不涉及前端（未触碰 `core/dashboard/static/`）且 implementer 遵循契约
- **THEN** `gates["frontend-build"] == {"status": "skipped", "reason": <非空中文说明>}`

#### Scenario: run 结束后主树可见

- **WHEN** 该 impl run 正常结束（含 gate-blocked 后重试成功的轮次），runner 执行既有 verify-progress 目录拷回
- **THEN** 主树 `.fenix/verify-progress/<spec>/quality-gates.json` 存在且内容为末轮 worktree 版本

### Requirement: 收尾守卫对 quality-gates.json 宽松对账（fail-open）

`core/agent_runner/result_gate.py` 的 impl 产物硬门 MUST NOT 因 quality-gates.json 缺失而判 run 失败（历史 spec 与偶尔漏写的 run 零打回）；文件存在时仅做机械合法性检查（JSON 可解析、status 值在枚举内、gate-id 在全集内），违规 MUST 仅记 WARNING 日志并放行，MUST NOT 产生任何打回/重试/预算消耗。本能力 MUST NOT 在 result_gate 或任何框架守卫中新增针对 quality-gates.json 的失败终态。

#### Scenario: 文件缺失零拦截

- **WHEN** 某 impl run 收工时 worktree 内不存在 quality-gates.json（历史 spec 复跑或 implementer 漏写）
- **THEN** 产物硬门按既有判据正常判定，不因该文件缺失而 gate-blocked，无 WARNING 之外的额外痕迹

#### Scenario: 格式违规仅 WARNING

- **WHEN** quality-gates.json 存在但 JSON 损坏或出现枚举外 status 值
- **THEN** result_gate 记一条 WARNING 日志（含违规明细）后放行，run 终态不受影响

### Requirement: 读侧合成 6 道门禁状态（fail-open）

Dashboard 数据层 MUST 提供门禁状态解析函数：输入 spec 名，输出统一 6 道门列表 `items: [{id, desc, status, detail}]`，其中 run 内 3 项（`full-suite`/`frontend-build`/`interaction-contract`）取 quality-gates.json，框架守卫 **3 项**合成：`result-artifact-gate`（结果文件产物硬门）取最新 impl run 终态——run 过门进入 implemented 及之后状态为 `passed`、最新 run 为 gate-blocked 为 `failed`（detail 含截断归因原文）、implementing 在飞且无 gate-blocked 痕迹为 `pending`；`deliverable-guard`（交付物守卫与格式复检）取 STATE 状态——status ∈ {implemented, testing, verified, done, pushed} 为 `passed`，blocked 且 error 归因命中交付物/dispute 关键词为 `failed`（detail 含归因），否则 `pending`（关键词以子串匹配，词表固化为：`交付物`/`deliverable`/`dispute`/`格式复检`；实现时若实际 blocked 归因措辞超出词表，按实际文案扩充词表并同步测试注入样本）；`code-review`（ocr 代码审查与处置）取 ocr 异步车道产物 `.fenix/verify-progress/<spec>/code-review.json`（worktree 优先、主树兜底，与 run 内 3 项同一读取策略）——车道在飞或产物 `status == "running"` 为 `running`、`status == "completed"` 为 `passed`（detail 附 findings 与处置计数摘要）、`status == "unavailable"` 为 `skipped`（detail 附非空 reason，与车道降级不阻塞语义一致）、产物不可见为 `pending`；读侧 MUST 校验产物 `(branch, merge_base, head_commit)` 指纹，指纹陈旧的产物按不可见处理（pending，不采信 stale 报告）。状态缺数据时一律 `unknown`（如 quality-gates.json 不存在/损坏的历史 spec，仅影响对应数据源的条目）；解析 MUST 全程 fail-open，任何缺失/损坏不抛异常、不产生 error 字段（与 `parse_verify_progress` 的容错语义一致）。implementing 且 worktree 存在时 MUST 优先读 worktree 内的 quality-gates.json（run 进行中即可见渐进进展，复用 tasks.py 的 worktree 优先先例），run 结束后读主树拷回版本；「优先」含回退分支——worktree 内无该文件时 MUST 回退读主树版本（fast-track 等持主树 verify-progress 写授权的车道——`_NO_MAIN_TREE_VERIFY_PROGRESS_LANES` 仅排除 implementer/repair/spec-review——可能将产物直接落主树而非 worktree），双位置兜底才不致 implementing 态漏读。`desc` 使用固定中文文案：全量回归测试 / 前端构建与类型检查 / ocr 代码审查与处置 / 交互契约自查 / 结果文件产物硬门 / 交付物守卫与格式复检。`done` 计数 = passed + skipped 数（skipped 表示该门已了结），`total` = 6。

#### Scenario: run 进行中读 worktree 渐进数据

- **WHEN** 某 spec 状态 implementing、在飞 run 已完成全量回归并落盘 quality-gates.json（仅 full-suite 一项），主树尚无该文件（未拷回）
- **THEN** 解析输出 full-suite 为 `passed`、其余 run 内项为 `pending`（unknown 与否以文件是否可见为准——worktree 优先使此时为 pending），框架 3 项为 `pending`

#### Scenario: ocr 车道进行中 code-review 门 running

- **WHEN** 某 spec 状态 testing、ocr 车道在飞且产物 `code-review.json` 可见 `status == "running"`
- **THEN** `code-review` 门 status 为 `running`、detail 为「ocr 并行审查进行中」；车道产物落 `completed` 后该门转 `passed`（detail 含 findings 计数摘要）

#### Scenario: ocr 车道降级 unavailable 时 skipped

- **WHEN** 某 spec 的 ocr 车道因超时/provider 不可达写 `status == "unavailable"` + 非空 `reason`
- **THEN** `code-review` 门 status 为 `skipped`（计入 done——已了结而非未做），detail 含该 reason

#### Scenario: ocr 车道产物指纹陈旧不采信

- **WHEN** 某 spec 的 `code-review.json` 存在但指纹与当前 `(branch, merge_base, head_commit)` 不符（如修复轮后 head 前移）
- **THEN** `code-review` 门按产物不可见处理（`pending`），MUST NOT 呈现 stale 报告的状态

#### Scenario: 历史 spec 无数据全 unknown

- **WHEN** 某历史 spec（quality-gates.json 从未存在）处于 implementing 之前状态或已完成归档
- **THEN** run 内 3 项 status 为 `unknown`，解析不抛异常；若该 spec 已 implemented 之后则框架守卫 2 项仍可合成 `passed`，ocr 门按产物存在性独立合成

#### Scenario: 产物硬门打回时 failed 带归因

- **WHEN** 某 implementing spec 最新 run 被产物硬门打回（gate-blocked，如归因「缺交付物声明对账项」）
- **THEN** `result-artifact-gate` 项 status 为 `failed`、detail 含该归因文案；进度条不含该项（done 不计 failed）

#### Scenario: merge 完成后框架守卫 2 项 passed

- **WHEN** 某 spec 已进入 implemented（merge-back 成功）
- **THEN** `result-artifact-gate` 与 `deliverable-guard` 均 `passed`，即使 quality-gates.json 缺失（run 内 3 项 unknown 不影响框架项合成）

#### Scenario: 文件损坏时零异常

- **WHEN** 主树 quality-gates.json 为非法 JSON（截断/编码错误）
- **THEN** 解析返回 run 内 3 项 `unknown`，不抛异常、不写 error 字段，其余项照常合成

### Requirement: 详情页「质量门禁」Card 渲染

spec 详情页 MUST 在「任务清单」Card 之后、「验证进度」Card 之前渲染「质量门禁」Card：上部为进度条（复用 `ProgressBarTile` 控件形态，done/total 取读侧合成值，从 0 起走，进度条配色为门禁专属橙色系，区别于任务进度的蓝绿渐变），下部为 6 道门禁的勾选列表，交互形式与任务清单一致（antd Checkbox、disabled、passed 项勾选 + 删除线置灰）。状态渲染 MUST 区分：`passed` 勾选+删除线；`failed` 未勾选+红色文字、detail 归因作为辅助文案展示；`running` 未勾选+「进行中」标识；`pending` 未勾选+灰色；`skipped` 勾选框置灰打勾样式或显式「不适用」徽标+灰色（不与 passed 混淆）；`unknown` 未勾选+「无记录」灰色辅助文案。数据经 `spec_detail` 下发（新增 `quality_gates` 字段：`{exists, done, total, current, items}`），SSE 增量推送自动携带。空态：`exists == false` 且 spec 状态在 implementing 之前（drafted/ready）时不渲染本 Card；其余状态 exists == false 时渲染 Card 并显示「暂无质量门禁记录」提示（与验证进度「暂无验证进度」空态风格一致）。

#### Scenario: 全过门禁的完成态渲染

- **WHEN** 某 implemented spec 的 6 道门禁为 5 passed + 1 skipped（frontend-build 无前端改动）
- **THEN** Card 内进度条满格（done=6/total=6）、6 项全部呈勾选态（skipped 项以不适用样式区分），列表顺序与契约固化顺序一致

#### Scenario: 门禁进行中的中间态渲染

- **WHEN** 某 testing spec 的门禁状态为 full-suite passed、frontend-build skipped、code-review running（ocr 车道在飞）、其余项已了结或 pending
- **THEN** 进度条按 done 计数走（橙色）、code-review 行有「进行中」标识、其余未了结项呈 pending 灰色

#### Scenario: 打回循环中的 failed 渲染

- **WHEN** 某 spec 最新 run gate-blocked（result-artifact-gate failed，归因如「缺交付物声明对账项」）
- **THEN** 「结果文件产物硬门」行红色未勾选，辅助文案显示归因；进度条走到 done/6 为止，用户可直接读出「卡在哪道门」

#### Scenario: 未实现阶段不渲染 Card

- **WHEN** 某 spec 状态为 drafted 或 ready
- **THEN** 详情页不出现「质量门禁」Card（任务清单与验证进度照常）
