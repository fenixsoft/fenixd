# quality-gates-progress 能力增量（fix-quality-gates-terminal-blindspot）

> 终态盲区修复：①ocr 门指纹校验增加 merge-back 豁免——pushed 后 merge-base 构造性前移到分支尖，产物 merge_base 必然失配致已完成审查恒 pending，属显示缺陷非质量问题；②full-suite 门增加终态豁免——终态（verified/done/pushed）后框架回归产物指纹必然陈旧且 run 自查键缺位，恒 pending 语义错误。本 delta 仅改这两处读侧合成规则；键名全集、状态枚举、其余 4 道门、fail-open 语义与非终态数据源优先级全部保持不变（原文各 Scenario 继续有效，其中指纹陈旧场景收窄为 head 前移情形）。

## MODIFIED Requirements

### Requirement: 读侧合成 6 道门禁状态（fail-open）

Dashboard 数据层 MUST 提供门禁状态解析函数：输入 spec 名，输出统一 6 道门列表 `items: [{id, desc, status, detail}]`，其中 `frontend-build`/`interaction-contract` 取 quality-gates.json；`full-suite`（全量回归）自 add-impl-selfcheck-model-probe 起按数据源优先级取值，并自 fix-quality-gates-terminal-blindspot 起增加最高优先级终态豁免：⓪终态豁免——spec status ∈ {verified, done, pushed} 时 MUST 直接合成 `skipped`（detail 固定为「SPEC 已终态，全量回归跟踪移交主树」，计入 done；终态豁免是确定性显示语义——门的历史使命已了结，不随后续 main 推进或回归重跑摆动）；①框架侧回归产物（`core/regression.py` 产出、带分支指纹的回归结果快照，指纹校验对齐 ocr 门 `(branch, merge_base, head_commit)` 语义，指纹陈旧按不可见处理不采信）②quality-gates.json 的 run 内自查值（存量与降级兼容来源）③两者皆无 → `pending`（全量回归判定责任已单点化到验证链，implementer 收尾不再必跑回归，读侧因 full-suite 项 pending 而呈现的缺口 MUST NOT 触发任何打回；①②③仅在非终态生效）；框架守卫 **3 项**合成：`result-artifact-gate`（结果文件产物硬门）取最新 impl run 终态——run 过门进入 implemented 及之后状态为 `passed`、最新 run 为 gate-blocked 为 `failed`（detail 含截断归因原文）、implementing 在飞且无 gate-blocked 痕迹为 `pending`；`deliverable-guard`（交付物守卫与格式复检）取 STATE 状态——status ∈ {implemented, testing, verified, done, pushed} 为 `passed`，blocked 且 error 归因命中交付物/dispute 关键词为 `failed`（detail 含归因），否则 `pending`（关键词以子串匹配，词表固化为：`交付物`/`deliverable`/`dispute`/`格式复检`；实现时若实际 blocked 归因措辞超出词表，按实际文案扩充词表并同步测试注入样本）；`code-review`（ocr 代码审查与处置）取 ocr 异步车道产物 `.fenix/verify-progress/<spec>/code-review.json`（worktree 优先、主树兜底，与 run 内 3 项同一读取策略）——车道在飞或产物 `status == "running"` 为 `running`、`status == "completed"` 为 `passed`（detail 附 findings 与处置计数摘要）、`status == "unavailable"` 为 `skipped`（detail 附非空 reason，与车道降级不阻塞语义一致）、产物不可见为 `pending`。读侧 MUST 校验产物 `(branch, merge_base, head_commit)` 指纹，并自 fix-quality-gates-terminal-blindspot 起按以下细化：`branch` 与 `head_commit` MUST 与当前指纹全等，任一不等按不可见处理（pending，不采信 stale 报告；修复轮 head 前移的重审语义不变）；`merge_base` 比对在当前指纹 `merge_base == head_commit`（分支已完整合入主基线——merge-back 完成的构造性判据，不依赖状态枚举）时 MUST 跳过——此时产物记录的评审基线是历史事实而非陈旧，merge_base 不等 MUST NOT 触发不可见；其余情形（分支未合入）merge_base 不等仍按不可见处理。状态缺数据时一律 `unknown`（如 quality-gates.json 不存在/损坏的历史 spec，仅影响对应数据源的条目）；解析 MUST 全程 fail-open，任何缺失/损坏不抛异常、不产生 error 字段（与 `parse_verify_progress` 的容错语义一致）。implementing 且 worktree 存在时 MUST 优先读 worktree 内的 quality-gates.json（run 进行中即可见渐进进展，复用 tasks.py 的 worktree 优先先例），run 结束后读主树拷回版本；「优先」含回退分支——worktree 内无该文件时 MUST 回退读主树版本（fast-track 等持主树 verify-progress 写授权的车道——`_NO_MAIN_TREE_VERIFY_PROGRESS_LANES` 仅排除 implementer/repair/spec-review——可能将产物直接落主树而非 worktree），双位置兜底才不致 implementing 态漏读。`desc` 使用固定中文文案：全量回归测试 / 前端构建与类型检查 / ocr 代码审查与处置 / 交互契约自查 / 结果文件产物硬门 / 交付物守卫与格式复检。`done` 计数 = passed + skipped 数（skipped 表示该门已了结），`total` = 6。

#### Scenario: run 进行中读 worktree 渐进数据

- **WHEN** 某 spec 状态 implementing、在飞 run 已完成全量回归并落盘 quality-gates.json（仅 full-suite 一项），主树尚无该文件（未拷回）
- **THEN** 解析输出 full-suite 为 `passed`、其余 run 内项为 `pending`（unknown 与否以文件是否可见为准——worktree 优先使此时为 pending），框架 3 项为 `pending`

#### Scenario: ocr 车道进行中 code-review 门 running

- **WHEN** 某 spec 状态 testing、ocr 车道在飞且产物 `code-review.json` 可见 `status == "running"`
- **THEN** `code-review` 门 status 为 `running`、detail 为「ocr 并行审查进行中」；车道产物落 `completed` 后该门转 `passed`（detail 含 findings 计数摘要）

#### Scenario: ocr 车道降级 unavailable 时 skipped

- **WHEN** 某 spec 的 ocr 车道因超时/provider 不可达写 `status == "unavailable"` + 非空 `reason`
- **THEN** `code-review` 门 status 为 `skipped`（计入 done——已了结而非未做），detail 含该 reason

#### Scenario: ocr 车道产物指纹陈旧不采信（head 前移）

- **WHEN** 某 spec 的 `code-review.json` 存在但 `branch` 或 `head_commit` 与当前指纹不符（如修复轮后分支 head 前移）
- **THEN** `code-review` 门按产物不可见处理（`pending`），MUST NOT 呈现 stale 报告的状态；merge-back 豁免不覆盖本情形（豁免仅跳过 merge_base 比对）

#### Scenario: merge-back 后 ocr 产物采信（核心修复）

- **WHEN** 某 spec 已 push（merge-back 完成，当前指纹 merge_base == head_commit == 分支尖），`code-review.json` 可见 `status == "completed"`，产物 `branch`/`head_commit` 与当前全等，产物 `merge_base` 为评审时基线（≠当前 merge_base）
- **THEN** `code-review` 门按产物状态合成为 `passed`（detail 含 findings 计数摘要），MUST NOT 因 merge_base 失配判 stale

#### Scenario: 分支未合入时 merge_base 失配仍不采信

- **WHEN** 某实现分支尚未合入主基线（当前指纹 merge_base ≠ head_commit），`code-review.json` 的 merge_base 与当前指纹不等
- **THEN** `code-review` 门按产物不可见处理（`pending`），既有 stale 拒采信语义不变

#### Scenario: full-suite 终态豁免

- **WHEN** 某 spec status ∈ {verified, done, pushed}，框架侧回归产物指纹陈旧（main 已前进）、quality-gates.json 亦无 full-suite 键
- **THEN** full-suite 门呈现 `skipped`（detail 为固定文案「SPEC 已终态，全量回归跟踪移交主树」），计入 done；其余 5 道门不受影响

#### Scenario: 终态豁免优先于框架产物

- **WHEN** 某 spec 已 pushed 且框架侧回归产物指纹恰好仍匹配（main 未前进）
- **THEN** full-suite 门仍呈现 `skipped`（终态豁免优先级最高，终态显示语义不随后续回归结论摆动）

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

#### Scenario: 非终态框架侧回归产物优先于 run 内自查

- **WHEN** 某非终态 spec（如 testing）的框架侧回归产物（指纹匹配当前分支）与 quality-gates.json 的 full-suite 自查值同时存在且结论不一致（产物 failed / 自查 passed）
- **THEN** full-suite 门呈现 `failed`（以框架侧产物为准），detail 可溯源到产物路径

#### Scenario: 非终态双源皆无呈现 pending 零打回

- **WHEN** 某非终态 spec 既无框架侧回归产物、quality-gates.json 亦无 full-suite 项（implementer 按新契约未跑回归）
- **THEN** 该门呈现 `pending`，不抛异常、不产生任何打回/失败终态，其余 5 道门呈现不受影响
