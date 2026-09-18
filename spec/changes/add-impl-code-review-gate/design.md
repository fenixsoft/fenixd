## Context

实现阶段现有闸门全部是**结构性 / 功能性**的：交付物存在性守卫、tasks.md 勾选
一致性、零变更哨、测试套件。缺一道**代码质量**闸门。

2026-09-18 的实测证据：对 `fix-dashboard-fault-isolation` 的归档物（6 文件
581 行）跑 alibaba open-code-review（`ocr` v1.12.5），用框架自身的 maomaoai
provider 配置驱动，1m46s / 92 万 token 命中 11 条发现（2 high / 3 medium /
6 low）。其中「`overview()` 降级路径非事务性——`project_summary` 的计数已入
`totals` 后才调 `parse_state`，异常时计数器与降级条目不一致」经回读源码确认为
真实功能缺陷，却完整穿过了实现阶段全部既有闸门。

本 SPEC 把这次实验固化为可选能力：开关打开时，实现者在收尾阶段自行执行代码
审查、评估并修正真实问题，框架只做机械对账。

### 关键外部约束（本设计的前提，均已实测）

`ocr` 的 LLM 端点解析优先级为：**`~/.opencodereview/config.json` 配置文件 >
`OCR_LLM_*` 环境变量 > `ANTHROPIC_*` 环境变量 > shell rc**。

实测（隔离 HOME 后逐项验证）：

1. `OCR_CONFIG_PATH` 环境变量**对 `ocr review` 无效**——`ocr config set` 与
   `review` 均走 `defaultConfigPath()`（硬编码 `$HOME/.opencodereview/config.json`），
   只有只读命令 `ocr llm test` 认 `OCR_CONFIG_PATH`。所以无法用环境变量把
   review 指向一份 run 专属配置。
2. `$HOME/.opencodereview/config.json` **存在时会静默压制** `OCR_LLM_URL/
   TOKEN/MODEL`。实测：全局配置有效 + `OCR_LLM_*` 指向不存在的模型名，审查
   仍以全局配置里的模型成功执行。因此「只注入 `OCR_LLM_*`」方案在本机（用户
   已有全局 ocr 配置）必然静默走错 provider。
3. `HOME` 指向 run 专属目录可完整驱动 `ocr review` 的 provider 选择——实测
   以 run 级 HOME 下的 `config.json` 驱动，报告的 `manifest.execution.provider`
   与 `model` 精确反映该配置。

### 环境事实

- `.fenix/` 被 `.gitignore` 忽略（`.gitignore:26` `.fenix/*`），但
  `.fenix/config.template.yaml`、`.fenix/todo.md`、`.fenix/verify.yaml` 三个文件
  **已被显式跟踪**（`git ls-files` 可证）。故模板改动是可交付的。
- `.fenix/verify-progress/<spec>/` 已存在 worktree → 主树的回拷机制
  （`_copyback_verify_progress`，带 mtime 守卫、fail-open），报告放此路径即
  自动获得归档与「陈旧产物不回灌」保护。
- implementer 与 fast-track 共用同一实现产物硬门 `_check_impl_result_artifact`
  （`fast_track.py:586` 直接调 `agent_runner._check_impl_result_artifact`），
  单一实现点已具备。

## Goals / Non-Goals

**Goals**
- 开关默认关闭，零行为变化；打开后实现阶段末尾出现一道可选的代码质量审查。
- 审查复用**分配给该 implementer run 的那一个 provider**，成本与 fenix 记账同源。
- 框架只做机械对账（报告存在 + 逐条发现都有处置登记），修与不修的裁量权归实现者。
- 环境缺失（未装 ocr / provider 不通）降级放行，不因环境类缺口重派烧预算。
- 多 run 并发时 provider 配置互不干扰。

**Non-Goals**
- 不做界面展示（报告只落盘归档）。
- 不把 `ocr` 变成入库依赖 / 不代装。
- 不做「强制修正全部发现」——架构上明确保留误报驳回权。
- 不改动 `ocr` 自身的配置或上游仓库。

## Decisions

### D1：配置键置于 `verify.impl_code_review`（而非新立配置节）

**决策**：布尔键 `verify.impl_code_review`，与 `static_scope` / `deps_mode`
同处 `verify` 节。

**理由**：设置页「验证」页签已经承载 `verify` 节读写全链（`config_admin.py`
的 `_MANAGED_KEYS` 已含 `verify`、`_SOURCE_KEYS` 已含 `verify.*` 键、前端
`VerifyPanel.tsx` 直接 patch `verify` 对象）。沿用该节意味着读/写/来源标注
三处只需各加一个键名，无需新开节、无需新面板。

**备选**：新立 `verify.impl_code_review` 独立的 `.fenix/code-review.yaml`
——被否，为单布尔键增加一个配置文件与一套加载链，成本与收益不成比例。

### D2：provider 注入走 run 级 HOME + 仓库内包装器

**决策**：runner 在选定本轮 provider 后：

1. 在 run 专属目录（沿用既有 `_ensure_agent_config_dir(provider_name)` 已建立的
   per-provider 隔离目录，其下属一个 `ocrcfg/` 子目录）写
   `.opencodereview/config.json`，内容为该 provider 的
   `url`（**原样取 `baseurl`，不追加/改写版本后缀**——实测 `ocr` 自行在 URL 后
   拼 `/v1/messages`：配 `https://host` → `https://host/v1/messages`，配
   `https://host/v1` → `https://host/v1/messages`，配 `https://host/anthropic`
   → `https://host/anthropic/v1/messages`；本项目 `aliyun` / `bigmodel.cn` /
   `deepseek` 三个真实 baseurl 本就不以 `/v1` 结尾，自行「归一化」会拼出
   `.../anthropic/v1/v1/messages` 这类坏 URL）/ `api_key` / `model`（取本轮
   实际生效的模型名，与 fenix 记账同源），`provider` 与 `custom_providers` 的
   键固定为 `fenix-impl`（避开 ocr 内置预设名，`ocr llm providers` 可列全部
   预设），`protocol` 取 `anthropic`——实测该网关的 `/v1/messages` 同时接受
   `x-api-key` 与 `authorization: Bearer`，anthropic 协议可通。
2. 向 agent 环境注入 `FENIX_OCR_HOME`（run 级 HOME）、`FENIX_OCR_BIN`（`ocr`
   可执行文件路径，缺省 `ocr`）与 `OCR_NO_UPDATE=1`（关掉 `ocr` node 启动器
   在每个 run 级 HOME 下 `detached` 拉起的新版本检查）。
3. 仓库内新增 `bin/ocr_review.py` 包装器：读 `FENIX_OCR_HOME`，设
   `HOME=<该目录>` 后以 **`os.execvp`**（带 PATH 搜索）替换为底层 `ocr`，
   透传全部 argv 与退出码——MUST NOT 用 `os.execv`：它不搜索 PATH，`FENIX_OCR_BIN`
   取缺省裸名 `"ocr"` 时必然 `FileNotFoundError`（本机实测），会把「ocr 已装」
   误判成环境不可用而静默降级放行。
4. 提示词要求实现者调 `bin/ocr_review.py`，而非直接调 `ocr`。

**理由**：由「关键外部约束」实测 2 得——只要 `$HOME/.opencodereview/config.json`
存在，`OCR_LLM_*` 就被静默压制。本机（以及任何装过 ocr 的机器）必然存在该文件，
故纯环境变量方案**在正确性上有洞**且洞是静默的（审查会成功返回，但用的是错的
provider，成本记到别处）。run 级 HOME 是唯一能确定性覆盖配置文件的手段，且天然
满足并发隔离（每 run 一个目录）与「不触碰用户全局配置」。

**注入的 HOME 是哪个目录（不变量）**：`FENIX_OCR_HOME` MUST 指向**直接包含
`.opencodereview/` 的那个目录**，即 `ocrcfg/` 本身，而非其父目录
`.fenix/agent-config/<provider>/`。理由与上面同源：ocr 只读
`$HOME/.opencodereview/config.json` 一个硬编码路径，HOME 指到父目录则该文件
永远读不到——审查会退化为按 `ANTHROPIC_*` 环境变量选端点，落在设计期望之外的
不确定性上（pass-through 行为实测可用，但不再是 run 级确定性注入）。
`_write_run_ocr_config` 的返回值与 `FENIX_OCR_HOME` 的取值 MUST 同一，且
`(FENIX_OCR_HOME / ".opencodereview" / "config.json")` MUST 存在（测试钉住）。

**备选**：
- 纯 `OCR_LLM_*` 环境变量 —— 被否（实测被配置文件压制）。
- 覆写全局 `$HOME/.opencodereview/config.json` —— 被否（破坏用户配置 +
  `max_concurrent=3` 并发下互相覆盖）。
- `OCR_CONFIG_PATH` 指向 run 配置 —— 被否（实测对 review 无效，只有 `llm test`
  认这个变量；若上游后续给 review 接上该变量，本方案可退化为更简形式，属未来
  可选优化）。

### D3：注入点为 prompt_builder 新增段，两条实现车道共用

**决策**：`core/agent_runner/prompt_builder.py` 新增
`_impl_code_review_section(spec_name)`，在 `_build_prompt` 的**统一收尾处**
（`_noninteractive_contract_section()` 与 `_project_extra_section()` 两行之间）
按 `agent_type in ("implementer", "fast-track")` 条件追加一次。

**理由**：既有实现车道动态段的注入模式一致（`_prev_error_section`、
`_result_gate_section` 等均在两分支各调一次同一函数）。fast-track 是「实现+
验证同一 run 内完成」，其「写代码之后、验证之前」的时点与 implementer 的
「写完所有任务之后」语义对齐，故一并覆盖。

**注入点为何在统一收尾处而非两个分支内**：`_noninteractive_contract_section()`
是在两分支的 `elif` 链**之外**无条件调用一次的（`prompt_builder.py:394`），
分支内追加的段必然排在它**之前**，与 spec「收尾审查段 MUST 位于非交互契约段
之后」的段序要求冲突。统一收尾处注入是该文件既有约定（非交互契约段与新 agent
类型白名单同在此处），天然满足「非交互契约段之后、项目级附加段之前」，且两条
车道由同一 agent_type 白名单覆盖，不必维护两份调用。

**位置约束**：`_noninteractive_contract_section()` 之后可保证实现者先看到
非交互契约；`_project_extra_section()` 之前可保护既有「项目级附加段位于
prompt 末尾」的约定（该约定在 prompt_builder 内已有显式注释）。

### D4：报告落盘 `.fenix/verify-progress/<spec>/code-review.json`

**决策**：报告写该路径；`code_review` 摘要段写 `.fenix-run-result.json` 顶层。

**理由**：该目录已有 worktree → 主树回拷机制，且带 mtime 守卫（防 worktree
复用继承的陈旧报告回灌覆盖主树较新版本）与 fail-open 语义。复用既有归档链，
无需新写一套拷贝逻辑。results 摘要写 `.fenix-run-result.json` 顶层则利用既有
结果文件硬门通道——该文件本就承载 `status` / `completed_tasks` / `unattainable`
等机械对账字段。

**已知边界（可接受）**：`_copyback_verify_progress` 的 mtime 守卫按**文件**比较
（worktree 版本 mtime 较新才拷回），同一 spec 的后续实现 run 若因环境不可用只写
`status: "unavailable"`，其报告 mtime 更新、会覆盖主树上前一轮较完整的审查报告。
本能力定位是「给实现者一个自查机会 + 留下可审计痕迹」，非合规证据链，且覆盖
不涉及代码合并（`verify-progress/` 在仓库外、不参与 merge-back），影响可审计性
而非正确性；不为此增加「保留历史报告」的额外机制。

### D5：硬门复用 `_check_impl_result_artifact` 单一实现点

**决策**：在该函数 `status` 判定之后、任务完成度判据之前（或之后，见任务书）
插一段 code-review 校验；开关关闭时早退，零校验。

**末轮语义边界（降级放行按设计，非漏洞）**：审查段要求「全部任务完成并提交**之后**、
写结果文件**之前**」执行审查，故此硬门只在实现者**自报成功**的那一轮生效。
最后一轮仍失败（`status: "partial"` / `"error"` 收口）时，**未附审查报告不属于
违规**——这类轮次按既有任务完成度判据处置，框架 MUST NOT 要求其补审查产物。
硬门实现时必须在任务完成度判据**之前**早退于「本轮最终未成功」的形态，避免把
「诚实申报 partial 的轮次」误判为交付物缺口重派（与 7.3 的「关闭时零校验」同等
重要的零误拦边界）。

**理由**：该函数已被 implementer 与 fast-track 两车道共用（fast_track.py:586
直接调），在此加分支即两条车道同时生效，无需在两处维护同款逻辑——历史多次
事故（如 `_sync_task_progress` 双写点漂移）都源于同款逻辑两处实现。

**降级放行的判定归位**：`status == "unavailable"` 且 `reason` 非空 → 放行。
`reason` 为空 → 判失败（防「一律写 unavailable 绕过审查」）。

### D6：审查范围为「本次改动」，用 merge-base 模式

**决策**：注入段指导实现者用 `bin/ocr_review.py review --from <base> --to HEAD
--format json --output <报告路径>`（merge-base 模式）。

**理由**：实测该模式在 worktree 内可正确工作（在真实的
`impl-add-declaration-relocation-protocol` worktree 内 preview 到 9 个变更文件）。
实现者若不确定 base，可用 `--commit` 逐提交审或 `ocr review` 工作区模式兜底
——具体命令形态由实现者在注入段指导下自行选择，框架不硬编码。

**成本控制**：注入段 MUST 提示实现者传 `--max-tokens-budget` 或 `--effort`，
避免一次审查吃掉大额预算。默认值由实现者按改动规模选择（裁量权语义）。

### D7：环境缺失降级为 fail-open 放行

**决策**：`ocr` 不存在、provider 不可达、非 git 仓库、审查异常终止 → 实现者写
`status: "unavailable"` + 非空 `reason`，run 照常 `success`，硬门放行。

**理由**：与项目既有多处一致约定——环境类缺口不得被当交付物缺口重派（历史
事故：`main-tree-prepare-no-deps-provision` 类因环境缺依赖打回烧预算）。
`reason` 非空是防绕过的唯一机械约束。

## Risks / Trade-offs

- **[实现者可能「写个空报告」敷衍]** → 硬门要求 `findings` 条数与 `code_review`
  处置条数一致；`status: "unavailable"` 要求非空 `reason`。但确实无法机械判定
  「审查是否真的覆盖了改动」。**接受的取舍**：本能力定位是「给实现者一个自查
  机会 + 留下可审计痕迹」，不是「保证审查质量」。若要更强约束，需引入独立的
  审查 agent 车道（明确列为非目标）。
- **[注入段增加 prompt 长度与 token]** → 开关默认 false，仅开启的项目付费；
  段文本控制在 ~40 行内。
- **[ocr 审查本身烧 token（实测 92 万/次）]** → 注入段要求实现者控制范围
  （merge-base 而非全仓 scan）并显式传预算上限。
- **[包装器引入新的可执行入口]** → 包装器逻辑极薄（重定向 HOME + execv），
  且 MUST 位于仓库内（`bin/`），可被测试覆盖。
- **[provider 目录复用可能串扰]** → run 级目录路径含 `provider_name`，
  同名 provider 的并发 run 会写同一份 ocr 配置——但内容由同一 provider 配置
  派生，逐字节相同，写入幂等，故无实际串扰。**这是有意的**：避免为每 run 单独
  建目录带来无界堆积。
- **[`home` 重定向影响 ocr 其它行为]** → 实测 `ocr review` 在隔离 HOME 下完整
  可用（含 provider 解析、审查执行、JSON 输出）。审查会话记录也落在 run 级
  HOME 下，run 结束后由既有 worktree 清理机制一并回收。

## Migration Plan

1. 合并后**无需迁移**——开关缺省 false，存量项目行为逐字节不变。
2. 增量启用：在设置页「验证」页签打开开关 → 下一轮实现 run 起生效（配置为
   30s 热重载，无需重启 daemon；但**已有在飞 run 不继承新配置**，属预期）。
3. 回滚：关掉开关即恢复原行为；或移除 `verify.impl_code_review` 键（缺省 false）。
4. 环境准备（可选，人工步骤，不进 tasks.md 门禁）：目标机器需可执行
   `ocr`（`npm install -g @alibaba-group/open-code-review`）。

## Open Questions

无——关键决策（作用域、判定口径、降级策略、provider 注入方式、fast-track
覆盖范围、是否做 UI）均已在立项对话中与用户确认。
