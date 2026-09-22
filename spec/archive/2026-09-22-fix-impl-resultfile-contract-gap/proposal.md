# Proposal: fix-impl-resultfile-contract-gap

## Why

**`implementer` / `fast-track` 两条主车道的提示词里从来没有「结果文件硬门」契约段**——这是全链最贵的单一缺口，2026-09-17 取证确证。

结果文件硬门（`agent_runner` 的 `_check_impl_result_artifact`，fail-closed）自 `add-judge-artifact-gate`（2026-09-14）起就要求 implementer 成功收工必须落盘 `.fenix-run-result.json`，但**反馈闭环只做了一半**：门在 runner 侧拦，提示词侧从未告知「不写=判失败」。`_result_gate_section()`（`core/agent_runner/prompt_builder.py:1548`）只注入三条车道——`planner-plan`（`:283`）、`planner-judge`（`:314`）、`spec-review`（`:345`，2026-09-15 事故后补）。`implementer` 分支（`:258`）与 `fast-track` 分支（`:314` 之后的 `elif`）均**不注入**；`agents/implementer.md` 第 7 步只有纯祈使句「全部任务完成后，写文件 .fenix-run-result.json」，没有任何「收工不写=判失败」「先落盘再深入」的措辞（`grep` 命中 0）。`git log -S "_result_gate_section"` 全仓只见两次引入（`948197d7` planner / `153fea1f` spec-review）——**不是回归，是原始缺口**。

同一死法在 spec-review 车道 2026-09-15 已被同一处方修复（`prompt_builder.py:343-345` 注释原文：「此前评审车道缺本段，模型把结果 JSON 当正文输出、结果文件从未落盘 → 整轮白烧重试」），但该处方未施加到实现者车道。

**代价（全量转录统计，21 条实现者车道 run）**：自然退出却未写结果文件 **7 次，成本合计 $97.86**：

| run | turns | 成本 | 收尾形态 |
|---|---|---|---|
| impl-fix-observability-gaps-1789617176-a1 | 284 | $39.12 | 正文写 `<tool_use name="ScheduleWakeup" ...>` 假工具调用等全量套件 |
| impl-fix-observability-gaps-1789605764-a1 | 256 | $30.34 | `stop_reason=tool_use`，文本停在收尾叙述 |
| impl-fix-orphan-ready-recovery-liveness-a1-r1 | 205 | $22.25 | 假工具调用 `<function_use>` |
| impl-fix-observability-gaps-1789617176-a1-r1 | 45 | $2.87 | 文本停在「Let me determine the full scope of test files affected.」 |
| impl-fix-dashboard-read-path-performance-a1-r1 | 38 | $2.03 | thinking 明说「`.fenix-run-result.json` 已存在且内容正确…我不需要修改」 |
| impl-fix-orphan-ready-recovery-liveness-a1 | 12 | $0.71 | 假工具调用 `<Read>` |
| impl-fix-robustness-edge-cases-a1 | 15 | $0.53 | 自然退出，无落盘 |

**机制**：模型读到的唯一收工指令是「全部任务完成后写结果文件」——纯祈使句，无反馈闭环。于是模型把结果文件当成最后一件家务，优先去做自认为更重要的收尾验证（跑全量套件、核实交付物），验证中一旦自然 `end_turn`，文件就从未落盘，而 fail-closed 门随即判整轮失败重派。放大因子：`ScheduleWakeup` 在 `-p` 模式不产生后台节拍、`Explore` 子代理在本项目 100% 不可用（`model: sonnet` 被网关 404），模型在「等长套件」场景没有可靠等待原语，更倾向「先跑完再说」。

**次要同源缺口**（本次一并闭合）：

1. **重试轮死因透传待核实（初判已修正，见 design D3）**：初稿曾判「`_prev_error_section` 读 `STATE.error`、失败路径写 `_impl_diagnosis`，两处口径不通」。2026-09-17 复核实测推翻该判断——`_impl_diagnosis_section`（`prompt_builder.py:574`）**已**在 implementer/fast-track 两分支注入（`:263` / `:336`），其 `attribution` 即 `dispatch.py:867/1538-1603` 写入的 `final_error[:500]`；产物硬门失败文本经 `[provider-transient]` 前缀（`runner.py:2033-2034`）后由 `dispatch.py:1319-1333` 写入 `STATE.error`。故本条降级为**核实 + 防重复**：确认死因确经两段到达重派轮、保证不重复渲染（design D3 / task 2.1-2.3）。
2. **实现者车道无捞回**：`_salvage_spec_review_result`（fenced-JSON 捞回，把「整轮白烧」降为「零成本回收」）只接线在 spec-review 车道（`core/pm_engine/spec_review.py:191/220`），实现者车道没有。
3. **假工具调用特征只用于归因文案**：`_classify_terminal_no_commit` 已能机械识别 `<function_calls>` / `<tool_use` / `<parameter`，但只服务于零提交门文案，对「结果文件缺失」场景未利用。

## What Changes

- **实现者双车道注入结果文件硬门契约段（根因修复）**：`_build_prompt` 的 `implementer` 与 `fast-track` 两分支各注入 `_result_gate_section`；`_result_gate_section` 扩展为按 `agent_type` 计算路径（实现者车道 = `<worktree>/.fenix-run-result.json`，现函数只算 planner/spec-review 路径）。文案对齐 spec-review 版并补齐实现者特有要素：**「先落盘再深入」**（先写最小可判结果文件，再做全量套件/核实）、「正文里的 JSON 不算交付」、「收工未写=判失败并原地重派、烧整轮 token」、显式声明无后台节拍（长任务用前台有界入口 `run_full_suite.py`，不要用后台 + 轮询）。
- **重试轮死因可达性核实与防重复**：核实 `STATE.error`（`_prev_error_section`）与 `_impl_diagnosis`（`_impl_diagnosis_section`）两条来源在实现者重派轮均可见（2026-09-17 实测**均已可见**），并约束二者 MUST NOT 重复渲染同一诊断字段；「原地退避 attempt 2+ 无上轮死因」属 dispatch 写点时序的控制流问题，本 SPEC 只登记不修复（design D3）。
- **实现者车道结果捞回**：`_salvage_spec_review_result` 的 fenced-JSON 捞回泛化为按 agent_type 取目标路径，覆盖 `<worktree>/.fenix-run-result.json`；实现者 run 自然退出但正文含合法结果 JSON 时，框架代写落盘而非整轮重派。
- **假工具调用特征复用**：实现者车道的结果文件缺失归因复用既有 `_classify_terminal_no_commit` 的机械特征（`<function_calls>` / `<tool_use` / `<parameter`），把「格式回退截断」与「未收工即停」在日志与告警中区分开（仅语义区分，不改变处置路径）。

## Capabilities

### New Capabilities

- `impl-resultfile-contract`: 实现者车道（`implementer` / `fast-track`）的结果文件收工契约——硬门约束的提示词可见性（含「先落盘再深入」纪律与无后台节拍声明）、重试轮的失败死因透传、以及实现者车道的 fenced-JSON 结果捞回语义。

### Modified Capabilities

- `agent-runner`: 结果文件缺失归因新增「假工具调用 / 未收工即停」机械区分（映射层，不改既有 `_classify_terminal_no_commit` 返回值）；重试上下文由「`STATE.error`（`_prev_error_section`）与上轮 `_impl_diagnosis`（`_impl_diagnosis_section`）两段」承载，本变更核实其可达性并约束单次 prompt 内诊断字段不重复渲染（原判「两处口径不通」经 2026-09-17 复核实测推翻）。
- `judge-artifact-gate`: 产物硬门契约段的注入车道由「planner-plan / planner-judge（+ spec-review）」扩展为「planner-plan / planner-judge / spec-review / implementer / fast-track」，路径计算按 agent_type 分派（行为不变，覆盖面扩展）。

## Impact

- **代码**：
  - `core/agent_runner/prompt_builder.py`：`_result_gate_section` 路径按 agent_type 分派 + `implementer`（`:257`）/`fast-track`（`:319`）两分支注入点；承载新 helper `impl_result_path`（与既有 `planner_result_path` / `spec_review_result_path` 同处，供 `result_gate` 导入——依赖方向 `result_gate` → `prompt_builder` 不可反）。
  - `core/agent_runner/result_gate.py`：`_check_impl_result_artifact` 改用 `impl_result_path`；捞回泛化与归因入口/拼接（优先落此以压制 `runner.py` 行数增量）。
  - `core/agent_runner/runner.py`：`_salvage_spec_review_result` 泛化（或新增同族 `_salvage_impl_result`，调用点在拷回块之前）；结果文件缺失归因接入假工具调用特征（拼接实现尽量下沉 `result_gate.py`）。
  - `agents/implementer.md`：收工契约补「未落盘=判失败」与「先落盘再深入」硬约束（与动态契约段同源、不重复计数）。
  - `agents/fast-track.md`：PHASE 4 收工契约同步补同款硬约束措辞（与 tasks 1.7 一致；`## Deliverables` 已列本文件，原 Impact 清单漏列）。
- **API**：无外部 API 变更；提示词内容扩展、日志归因文案新增类别（向后兼容）。
- **测试**：新增 `tests/test_impl_resultfile_contract.py`（双车道注入断言、路径分派、重试死因透传、捞回四态）；既有 `tests/test_agent_prompt_files.py`、`tests/test_agent_runner_gate.py`、`tests/test_review_artifact_first.py`、`tests/test_spec_review_artifact_gate.py`（`_salvage_spec_review_result` 直测，捞回泛化的直接护栏）为护栏。
- **风险面**：捞回须严格 `status` 白名单 + 不覆盖既有产物（复用 spec-review 版既有守卫）；契约段注入不得挤占既有段位置语义（`_task_progress_contract_section` 之类测试有顺序断言）。
