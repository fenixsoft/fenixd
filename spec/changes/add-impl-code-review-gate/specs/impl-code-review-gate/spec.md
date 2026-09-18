## ADDED Requirements

### Requirement: 收尾审查任务注入

`verify.impl_code_review` 为 `true` 时，系统 SHALL 向**实现车道**（implementer 与
fast-track 两条车道）的派发提示词注入「收尾代码质量审查」段。该段 MUST 明确
告知实现者：

- 触发时机：在全部 tasks.md 任务完成并提交之后、写 `.fenix-run-result.json`
  之前执行；
- 审查范围：本次改动本身（即实现分支相对其基线的 diff）；
- 审查工具：仓库内包装器 `bin/ocr_review.py`（而非直接调 `ocr`），因为该包装器
  承载 run 级 provider 配置；
- 评估义务：逐条评估审查发现，判断哪些是真实问题、哪些是误报，并修正真实问题
  （裁量权归实现者）；
- 落盘义务与结果登记格式（见下方两条 Requirement）。

开关为 `false` 时该段 MUST 零注入 —— 提示词与未引入本功能时逐字节一致。

#### Scenario: 开启时注入到两条实现车道

- **WHEN** 开关为 `true`，分别派发 implementer 与 fast-track
- **THEN** 两者的提示词 MUST 均包含收尾审查段，且段内 MUST 出现
  `bin/ocr_review.py`、报告落盘路径与结果登记格式

#### Scenario: 关闭时零注入

- **WHEN** 开关为 `false`
- **THEN** 提示词 MUST NOT 包含任何收尾审查相关内容，且 MUST 与未引入本功能时
  的提示词逐字节一致

#### Scenario: 段内声明裁量权归实现者

- **WHEN** 检查注入段文本
- **THEN** MUST 明确声明「发现的真实问题应修正、误报可驳回，判定裁量权归实现
  者」，MUST NOT 要求实现者机械修正全部发现

#### Scenario: 注入位置在项目级附加段之前

- **WHEN** 检查提示词段序
- **THEN** 收尾审查段 MUST 位于非交互契约段之后、项目级附加提示词段之前，
  MUST NOT 破坏既有「项目级附加段位于 prompt 末尾」的约定。段序须由
  `_build_prompt` 的**单一收尾注入点**保证（非交互契约段与项目级附加段之间），
  MUST NOT 在 implementer / fast-track 分支内各自追加（分支内追加必然排到
  非交互契约段之前）

### Requirement: run 级 ocr provider 注入

系统 SHALL 使收尾审查复用**分配给本次 implementer run 的那一个 provider**
（provider 名 / baseurl / apikey / model 与实现 run 一致），其成本 MUST 与
fenix 的 provider 记账同源。

- 注入 MUST 通过 run 级隔离实现：框架为本 run 写一份专属 HOME 目录下的
  `.opencodereview/config.json`，并把该 HOME 经环境变量传给包装器
  `bin/ocr_review.py`；包装器把 `HOME` 指向该目录后 exec `ocr`。
- 注入 MUST NOT 读写用户全局 `~/.opencodereview/`，MUST NOT 覆盖用户既有 ocr
  配置。
- 多个 run 并发（`agents.max_concurrent > 1`）时各 run 的 ocr 配置 MUST 相互
  隔离，MUST NOT 串扰。
- 包装器 MUST 透传 `ocr` 的退出码，使实现者能据以判断审查是否成功执行。

#### Scenario: 使用实现 run 的 provider

- **WHEN** 开关为 `true`，本次实现 run 选定的 provider 为 P（含 baseurl 与 model）
- **THEN** 收尾审查 MUST 以 P 的 baseurl / apikey / model 发起，审查报告的
  `llm` 字段 MUST 指向 P

#### Scenario: 不触碰用户全局配置

- **WHEN** 用户主目录已存在 `~/.opencodereview/config.json`
- **THEN** 该文件 MUST 保持逐字节不变，且审查 MUST NOT 读取其内容作为 provider 来源

#### Scenario: 并发 run 互不串扰

- **WHEN** 两个实现 run 并发、各自选定不同 provider
- **THEN** 各自的审查 MUST 使用各自的 provider，任一 run 的配置写入 MUST NOT
  影响另一 run 的审查结果

#### Scenario: 退出码透传

- **WHEN** 底层 `ocr` 以非零码退出
- **THEN** 包装器 MUST 以同一非零码退出，供实现者区分「审查失败」与「审查通过」

### Requirement: 审查报告落盘

实现者 SHALL 把审查结果落盘到 `.fenix/verify-progress/<spec>/code-review.json`，
并在 `.fenix-run-result.json` 顶层的 `code_review` 段登记逐条发现的处置结论。

`code-review.json` MUST 至少包含：

- `status`：`"completed"`（审查成功执行）或 `"unavailable"`（环境不可用，见下条）；
- `llm`：本次审查实际使用的 provider 名与 model；
- `findings`：审查工具的原始发现清单（逐条含文件路径、严重度、描述）；
- 供实现者追加的处置字段：逐条发现的 `disposition`，取值
  `"fixed"` / `"rejected"` / `"deferred"`，`rejected` 与 `deferred` MUST 附
  `reason`。

`code-review.json` 是本框架的规整契约，MUST NOT 假定审查工具的原生报告同构：
实测 `ocr review --format json` 的顶层键为 `status`（`"complete"` / `"failed"`）/
`llm` / `comments`（发现数组，逐条含 `path` / `start_line` / `category` /
`severity` / `content`）/ `summary` / `manifest`。实现者 MUST 把原生报告的发现
数组规整进 `findings`、把原生 `status` 映射为规整枚举
（`"complete"` → `"completed"`；底层非零退出或 `"failed"` → `"unavailable"` +
非空 `reason`），并 SHOULD 保留原生报告副本（如报告同目录下的
`code-review-raw.json`）以供审计。

`.fenix-run-result.json` 的 `code_review` 段 MUST 含 `report_path`（相对路径）
与逐条处置摘要，使框架无需解析 `code-review.json` 即可机械对账。

报告 MUST 经既有 worktree → 主树的产物回拷机制归档，使 spec 归档后报告仍
可追溯。

#### Scenario: 成功执行时落盘报告

- **WHEN** 审查成功执行且发现 N 条问题
- **THEN** `.fenix/verify-progress/<spec>/code-review.json` MUST 存在，
  `status` MUST 为 `"completed"`，`findings` MUST 含 N 条，
  `.fenix-run-result.json` 的 `code_review` 段 MUST 登记 N 条处置

#### Scenario: 报告经回拷机制归档

- **WHEN** run 收尾
- **THEN** worktree 内的报告 MUST 被拷回主树同路径，且 MUST 遵守既有 mtime
  守卫（主树版本较新时不覆盖）

#### Scenario: 处置取值受限

- **WHEN** 实现者登记某条发现为 `rejected`
- **THEN** 该条 MUST 附非空 `reason`；缺 `reason` 的 `rejected` / `deferred`
  MUST 被判为登记非法

### Requirement: 审查报告产物硬门

开关为 `true` 时，实现 run 的成功收口 SHALL 经一道机械产物硬门，校验审查
报告存在且逐条发现都有处置登记。该硬门 MUST 复用既有实现产物硬门的实现点
（`_check_impl_result_artifact`），MUST NOT 另立并行的门函数。

- 缺失 `code-review.json`、JSON 非法、`status` 不在允许枚举内、`findings` 条数
  与 `code_review` 处置条数不匹配、或存在缺 `reason` 的驳回/搁置项 → MUST 判
  失败，走既有「原地重试 / 打回重派」通道。
- `status` 为 `"unavailable"` 时 MUST 放行（见下条降级 Requirement），MUST NOT
  要求 `findings` 与处置对账。
- 开关为 `false` 时该硬门 MUST 零校验（与未引入本功能时行为一致）。
- **末轮零误拦边界**：审查任务只在「全部任务完成并提交之后、写结果文件之前」
  执行，故硬门 MUST 只对**实现者自报本轮成功**的收口生效——即结果文件顶层
  `status == "success"` 与 fast-track 的 `verification.verdict == "verified"`
  两种形态。实现者诚实申报未完成（`status` 为 `"error"` / `"partial"`，或
  fast-track `verdict` 非 `"verified"`）时，未附审查报告 MUST NOT 被判为交付物
  缺口，MUST NOT 因此重派（覆盖审查属「实现流程已跑完」的收尾义务，不是对
  「本轮没做完」的额外惩罚）。

#### Scenario: 报告缺失判失败

- **WHEN** 开关为 `true`，run 报 `status: "success"` 但未写 `code-review.json`
- **THEN** 硬门 MUST 返回失败原因（含报告路径），run MUST NOT 被视为成功收口

#### Scenario: 发现与处置条数不匹配判失败

- **WHEN** `findings` 含 5 条但 `code_review` 处置仅登记 3 条
- **THEN** 硬门 MUST 判失败，失败原因 MUST 指出条数不匹配的缺口

#### Scenario: 驳回缺理由判失败

- **WHEN** 某条发现的处置为 `rejected` 但未附 `reason`
- **THEN** 硬门 MUST 判失败，失败原因 MUST 指出缺少理由的发现

#### Scenario: 开关关闭时零校验

- **WHEN** 开关为 `false`，run 未写任何审查报告
- **THEN** 硬门 MUST 不因审查产物缺失而失败

#### Scenario: 末轮诚实申报不因缺审查报告被拦

- **WHEN** 开关为 `true`，实现者自报未完成（`status: "partial"` 或 `"error"`，
  或 fast-track `verdict` 非 `"verified"`）且未写审查报告
- **THEN** 硬门 MUST NOT 以「审查报告缺失」为由判失败，MUST 按既有任务完成度
  判据（或 error 早退）处置

#### Scenario: 硬门失败走既有重派通道

- **WHEN** 硬门判失败
- **THEN** 处置 MUST 复用既有产物硬门的失败通道（原地重试、打回重派），
  MUST NOT 引入新的处置路径

### Requirement: 环境不可用时降级放行

当审查工具不可用（`ocr` 未安装 / provider 不可达 / 当前目录非 git 仓库 /
审查过程异常终止）时，实现者 SHALL 记录不可用状态与原因，并按正常流程收工。
框架 MUST NOT 因此判失败或重派。

- 降级记录写入 `code-review.json` 的 `status: "unavailable"` 与 `reason`
  （非空）；`code_review` 段 MUST 相应标注未执行，并 SHOULD 登记不可用原因。
- 该降级 MUST NOT 阻断 run 的 `success` 收口，MUST NOT 消耗重试预算。

#### Scenario: ocr 未安装时降级

- **WHEN** 开关为 `true` 但环境不存在 `ocr` 命令
- **THEN** 实现者 MUST 写 `status: "unavailable"` 与原因，run MUST 照常以
  `success` 收口，硬门 MUST 放行

#### Scenario: provider 不可达时降级

- **WHEN** 审查请求因 provider 网络错误失败
- **THEN** 实现者 MUST 记录不可用原因并收工，MUST NOT 触发框架重派

#### Scenario: 降级原因必须非空

- **WHEN** 实现者写 `status: "unavailable"`
- **THEN** `reason` MUST 非空；空原因的不可用记录 MUST 被判为登记非法（防止
  「一律写 unavailable 绕过审查」）
