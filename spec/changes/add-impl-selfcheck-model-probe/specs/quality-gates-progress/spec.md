# quality-gates-progress 能力增量（add-impl-selfcheck-model-probe）

> `full-suite` 门数据源扩展：全量回归由验证链单点执行后，该门读侧合成从「run 内自查单源」改为「框架侧回归产物优先 + run 内自查降级兼容 + 皆无 pending」。本 delta 仅改数据源优先级；键名全集、状态枚举、其余 5 道门与 fail-open 语义全部保持不变（原文各 Scenario 继续有效）。

## MODIFIED Requirements

### Requirement: 读侧合成 6 道门禁状态（fail-open）

Dashboard 数据层 MUST 提供门禁状态解析函数：输入 spec 名，输出统一 6 道门列表 `items: [{id, desc, status, detail}]`，其中 `frontend-build`/`interaction-contract` 取 quality-gates.json；`full-suite`（全量回归）自 add-impl-selfcheck-model-probe 起按数据源优先级取值：①框架侧回归产物（`core/regression.py` 产出、带分支指纹的回归结果快照，指纹校验对齐 ocr 门 `(branch, merge_base, head_commit)` 语义，指纹陈旧按不可见处理不采信）②quality-gates.json 的 run 内自查值（存量与降级兼容来源）③两者皆无 → `pending`（全量回归判定责任已单点化到验证链，implementer 收尾不再必跑回归，读侧因 full-suite 项 pending 而呈现的缺口 MUST NOT 触发任何打回）；框架守卫 **3 项**合成：`result-artifact-gate`（结果文件产物硬门）取最新 impl run 终态——run 过门进入 implemented 及之后状态为 `passed`、最新 run 为 gate-blocked 为 `failed`（detail 含截断归因原文）、implementing 在飞且无 gate-blocked 痕迹为 `pending`；`deliverable-guard`（交付物守卫与格式复检）取 STATE 状态——status ∈ {implemented, testing, verified, done, pushed} 为 `passed`，blocked 且 error 归因命中交付物/dispute 关键词为 `failed`（detail 含归因），否则 `pending`（关键词以子串匹配，词表固化为：`交付物`/`deliverable`/`dispute`/`格式复检`；实现时若实际 blocked 归因措辞超出词表，按实际文案扩充词表并同步测试注入样本）；`code-review`（ocr 代码审查与处置）取 ocr 异步车道产物 `.fenix/verify-progress/<spec>/code-review.json`（worktree 优先、主树兜底，与 run 内 3 项同一读取策略）——车道在飞或产物 `status == "running"` 为 `running`、`status == "completed"` 为 `passed`（detail 附 findings 与处置计数摘要）、`status == "unavailable"` 为 `skipped`（detail 附非空 reason，与车道降级不阻塞语义一致）、产物不可见为 `pending`；读侧 MUST 校验产物 `(branch, merge_base, head_commit)` 指纹，指纹陈旧的产物按不可见处理（pending，不采信 stale 报告）。状态缺数据时一律 `unknown`（如 quality-gates.json 不存在/损坏的历史 spec，仅影响对应数据源的条目）；解析 MUST 全程 fail-open，任何缺失/损坏不抛异常、不产生 error 字段（与 `parse_verify_progress` 的容错语义一致）。implementing 且 worktree 存在时 MUST 优先读 worktree 内的 quality-gates.json（run 进行中即可见渐进进展，复用 tasks.py 的 worktree 优先先例），run 结束后读主树拷回版本；「优先」含回退分支——worktree 内无该文件时 MUST 回退读主树版本（fast-track 等持主树 verify-progress 写授权的车道——`_NO_MAIN_TREE_VERIFY_PROGRESS_LANES` 仅排除 implementer/repair/spec-review——可能将产物直接落主树而非 worktree），双位置兜底才不致 implementing 态漏读。`desc` 使用固定中文文案：全量回归测试 / 前端构建与类型检查 / ocr 代码审查与处置 / 交互契约自查 / 结果文件产物硬门 / 交付物守卫与格式复检。`done` 计数 = passed + skipped 数（skipped 表示该门已了结），`total` = 6。

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

#### Scenario: 框架侧回归产物优先于 run 内自查

- **WHEN** 某 spec 的框架侧回归产物（指纹匹配当前分支）与 quality-gates.json 的 full-suite 自查值同时存在且结论不一致（产物 failed / 自查 passed）
- **THEN** full-suite 门呈现 `failed`（以框架侧产物为准），detail 可溯源到产物路径

#### Scenario: 双源皆无呈现 pending 零打回

- **WHEN** 历史 spec 既无框架侧回归产物、quality-gates.json 亦无 full-suite 项（implementer 按新契约未跑回归）
- **THEN** 该门呈现 `pending`，不抛异常、不产生任何打回/失败终态，其余 5 道门呈现不受影响
