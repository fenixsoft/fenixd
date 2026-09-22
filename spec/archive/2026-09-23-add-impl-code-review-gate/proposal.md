## Why

实现阶段目前只有「交付物存在性 / tasks.md 勾选一致 / 测试通过」这类**结构性与功能
性**闸门，没有任何**代码质量**闸门：实现 Agent 可以交出一份「能跑、能勾选、能过
测试」但存在重复代码、死代码、合并残留、事务性缺陷的改动，框架无从察觉。真实
案例（2026-09-18 对 `fix-dashboard-fault-isolation` 归档物跑行业代码审查工具
alibaba open-code-review 的实测）在同一份 581 行改动上稳定命中 2 条 high、3 条
medium —— 其中「降级路径非事务性导致 totals 重复记账」是实打实的功能缺陷，却
完整穿过了实现阶段全部既有闸门。

本 SPEC 在实现阶段末尾增加一道**由实现者自己执行**的代码质量审查：调用
`ocr`（alibaba open-code-review）审查本次改动，评估发现、修正其中的真实问题，
然后才进入下一阶段。裁量权留给实现者（哪些真问题该修、哪些是误报可驳回），框架
只做机械可判的收口对账。

## What Changes

- **新增配置键 `verify.impl_code_review`**（布尔，缺省 `false`）。置于设置页
  「验证」页签，与既有 `verify.static_scope` / `verify.deps_mode` 同处一节，
  遵循用户级默认 + 项目级覆盖的两级作用域。
- **配置全链接线**：`core/config.py` 增读取器（缺省 false 的 fail-open 语义）、
  `core/dashboard/data/config_admin.py` 的读/写/来源标注三处白名单登记、
  `.fenix/config.template.yaml` 增注释条目。
- **前端「验证」页签增开关**：`VerifyPanel.tsx` 增一个 Switch，保存时随既有
  `verify` patch 一并提交；`services/dashboard.ts` 的 `VerifyConfig` 接口增字段。
- **新增收尾审查任务注入**：开关打开时，向 implementer 与 fast-track 两条实现
  车道的 prompt 末尾注入「收尾代码质量审查」段（单一注入点在 prompt_builder
  的统一收尾处，位于非交互契约段之后、项目级附加段之前），要求实现者在全部
  tasks.md 任务完成、提交之后、写结果文件之前，调用 `ocr` 审查本次改动。
- **新增 run 级 ocr provider 注入**：runner 在选定本轮 provider 后，写一份
  run 专属 HOME 目录的 `.opencodereview/config.json`（含该 provider 的
  baseurl / apikey / model），并把仓库内新增的 `bin/ocr_review.py` 包装器路径
  与 run 级 HOME 一并注入 agent 环境。包装器把 `HOME` 指向 run 级目录后 exec
  `ocr`，使审查**复用分配给 implementer 的那一个 provider**，与 fenix 成本记账
  同源，且不触碰用户全局 ocr 配置、多 run 并发互不干扰。
- **新增审查报告产物硬门**：开关打开时，实现者 MUST 把 `ocr` 的 JSON 输出落盘
  到 `.fenix/verify-progress/<spec>/code-review.json`，并在
  `.fenix-run-result.json` 顶层增设 `code_review` 段（逐条发现与其处置）。硬门
  机械校验报告存在、结构合法、逐条发现都有处置登记。
- **环境缺失降级为放行**：`ocr` 未安装 / provider 不可达 / 非 git 仓库等环境下，
  实现者 MUST 记录 `code-review.json` 的 `status: "unavailable"` 与原因后照常
  收工；硬门不因此判失败（避免环境类缺口被当交付物缺口重派烧预算）。

## Capabilities

### New Capabilities

- `impl-code-review-gate`: 实现阶段末尾的代码质量审查闸门——收尾审查任务注入、
  run 级 ocr provider 注入、审查报告产物硬门、环境缺失降级放行、报告落盘路径
  与归档机制。
- `impl-code-review-setting`: `verify.impl_code_review` 开关的配置语义——
  缺省 false、用户级默认 + 项目级覆盖的两级作用域、设置页「验证」页签读写与
  来源标注、配置模板一致性。

### Modified Capabilities

<!-- 无：`spec/specs/` 当前为空（活跃能力均已归档），本次为新增能力，
     不修改任何既有活跃 Requirement。 -->

## Impact

**配置层**
- `core/config.py`：新增 `get_impl_code_review_enabled` 读取器（缺省 false）
- `core/dashboard/data/config_admin.py`：`_MANAGED_KEYS` 已含 `verify`；需在
  读路径回显、写路径 merge、来源标注三处登记 `verify.impl_code_review`
- `.fenix/config.template.yaml`：`verify` 节增注释键

**前端**
- `core/dashboard/static/src/pages/settings/components/VerifyPanel.tsx`
- `core/dashboard/static/src/services/dashboard.ts`

**执行链**
- `core/agent_runner/prompt_builder.py`：新增 `_impl_code_review_section`
  （开关关闭时零注入，与既有「缺席零注入」约定一致）
- `core/agent_runner/runner.py`：provider 选定后写 run 级 ocr 配置 + 注入环境
- `core/agent_runner/result_gate.py`：`_check_impl_result_artifact` 内增
  code-review 产物校验分支
- `bin/ocr_review.py`（新建）：HOME 重定向包装器

**测试**
- `tests/test_impl_code_review_gate.py`（新建）
- `tests/test_dashboard_data.py` / `tests/test_system_settings_config.py`（扩展）
- `tests/test_agent_prompt_files.py`（扩展）

**依赖**
- 运行时依赖 `ocr` 命令（alibaba open-code-review），但**不入库依赖**：未安装
  时按降级路径放行，不影响既有实现流程。

**非目标**
- 不做界面展示（审查报告只落盘归档，不改 dashboard / SPEC 详情页）
- 不引入代码审查之外的其它质量门
