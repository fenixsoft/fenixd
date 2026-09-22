# Tasks: fix-impl-resultfile-contract-gap

## Deliverables

```yaml
- path: core/agent_runner/result_gate.py
  kind: modify
- path: core/agent_runner/prompt_builder.py
  kind: modify
- path: core/agent_runner/runner.py
  kind: modify
- path: agents/implementer.md
  kind: modify
- path: agents/fast-track.md
  kind: modify
- path: tests/test_impl_resultfile_contract.py
  kind: new
```

> 注 1（行数契约口径，2026-09-17 已核对）：`core/agent_runner/runner.py` 当前 **3803 行**，实测
> `tests/test_agent_runner_modules_contract.py:170-173` 断言 `runner.py < 4000`——当前为绿。本 SPEC 的
> 硬约束即此 `< 4000`（余量约 197 行，增量 MUST NOT 使其逼近上限）；实现者 **MUST NOT** 为腾行数做
> 无关重构。优先把捞回泛化与归因包装落在 `result_gate.py`，把 runner.py 增量压到最小。
> （另注：`≤3800` 是另一在飞 SPEC 的收敛阈值，见 `spec/changes/refactor-agent-runner-module/specs/
> agent-runner-modules/spec.md`，处置归属 `refactor-long-functions`，不是本测试的断言。）
>
> 注 2：`_salvage_spec_review_result` 的既有签名与语义是 `core/pm_engine/spec_review.py:191/220`
> 反射调用点与 `tests/test_review_circuit_breaker.py` 打桩对象的契约，**MUST 保留可用**。

## 1. 路径分派与契约段（根因修复）

- [x] 1.1 在 `core/agent_runner/prompt_builder.py`（与既有 `planner_result_path` / `spec_review_result_path` 同处，`prompt_builder.py:55/93`）提取模块级 helper `impl_result_path(wt_path) -> Path`（返回 `wt_path / ".fenix-run-result.json"`）；`core/agent_runner/result_gate.py` 导入该 helper 并让 `_check_impl_result_artifact` 内部改用（硬门判定语义逐字不变，`result_gate.py:437` 原式等价）。**落位方向 MUST NOT 反**：实测依赖方向是 `result_gate` → `prompt_builder`（`result_gate.py:23-28` 从 prompt_builder 导入三个路径/白名单符号），反向（helper 落 `result_gate.py`、由 prompt_builder 导入）必成循环 import，并使 `tests/test_agent_runner_modules_contract.py:71`「单独 import 三模块不触发循环 import」红。`_IMPL_RESULT_STATUSES` **MUST NOT** 由 `result_gate` 导出为模块常量——它是 `AgentRunner` 类属性（`runner.py:3430`），`result_gate.py:11-14` 的 D2b 契约要求经实例访问（实例属性打桩不被绕过）；契约段文案不得依赖该常量（如需列举白名单，写字面量或经调用点传参）
- [x] 1.2 `core/agent_runner/prompt_builder.py`：把 `_result_gate_section` 签名扩展为 `(self, spec_name, agent_type="planner-judge", wt_path=None)`，内部按 agent_type 三分支计算路径——`spec-review`（既有早返回，行为与文案逐字不变）、`implementer`/`fast-track`（经 `impl_result_path` 取 worktree 根，`wt_path is None` 时降级为相对路径表述）、planner 族（既有 `planner_result_path` 路径）
- [x] 1.3 新增实现者车道契约段文案（`_result_gate_section` 的实现者分支），要素齐全且每条以 MUST 句式写出：① 成功判定 = 进程正常退出 **且** 结果文件落盘且可解析非空 JSON；② **收工前未写 / 为空 / 非法 JSON → 本次 run 判失败并原地重派（整轮 token 重烧）**；③ **正文里的 JSON 不算交付**（框架只读文件）；④ **先落盘再深入**——在全量套件回归/交付物核实**之前**先写最小可判结果文件；⑤ 本车道**无后台节拍**——`ScheduleWakeup` 在派发模式下不产生唤醒，长任务 MUST 用前台有界入口 `python3 bin/run_full_suite.py --timeout 3600`（自身在超时内返回），MUST NOT 用「后台运行 + 轮询等待」编排
- [x] 1.4 `_build_prompt` 的 `implementer` 分支（`agent_type == "implementer"` 块内）注入 `self._result_gate_section(spec_name, "implementer", wt_path)`
- [x] 1.5 `_build_prompt` 的 `fast-track` 分支注入 `self._result_gate_section(spec_name, "fast-track", wt_path)`
- [x] 1.6 `agents/implementer.md` 步骤 7/8 收工契约补硬约束措辞（未落盘=判失败、先落盘再深入），与动态契约段同源互补、不重复罗列全部要素
- [x] 1.7 `agents/fast-track.md` PHASE 4 收工契约同步补同款硬约束措辞

## 2. 重试轮死因透传

- [x] 2.1 **先核实既有覆盖，再做最小补齐（MUST NOT 重复渲染诊断）**：重派轮死因已由两段携带——`_prev_error_section`（`prompt_builder.py:609`，读 `STATE.error`；注入点 `:260` / `:334`）与 `_impl_diagnosis_section`（`prompt_builder.py:574`，读 `_impl_diagnosis`；注入点 `:263` / `:336`；其 `attribution` 即 `dispatch.py:867/1538-1603` 写入的 `final_error[:500]`）。故本任务 MUST NOT 新增与 `_impl_diagnosis_section` 重复的诊断渲染：若为覆盖「仅 `error` 非空、诊断为空」的边角仍要扩展 `_prev_error_section`，同一诊断字段（`attribution` / `conclusion` / `progress`）在单次 prompt 中 MUST 只出现一次——`_impl_diagnosis_section` 已渲染诊断时该段 MUST 只渲染 `error` 原文；两者皆无时**零注入**（首次派发提示词与现状逐字一致）。**去重判据是字段级、不是子串级**：`attribution` 的定义即 `final_error[:500]`、与 `STATE.error` 同源（`dispatch.py:1319-1333` / `1538-1603`），故 `error` 原文内含 `attribution` 子串属预期，MUST NOT 计为重复渲染，MUST NOT 为凑去重而裁剪 `error` 原文
- [x] 2.2 诊断是 JSON 文本（STATE `_impl_diagnosis` 以 JSON 字符串存），任何渲染点（含既有 `_impl_diagnosis_section`）MUST 容错解析——解析失败降级为原文截断呈现，MUST NOT 抛错；`attribution` 与 `conclusion` 渲染 MUST 各自截断（建议 500 / 800 字）避免提示词膨胀
- [x] 2.3 确认「结果文件缺失」类 error 文本（形如 `[provider-transient] exit 0 但结果文件缺失（implementer 产物硬门）: <path>`，前缀由 `runner.py:2033-2034` 加）能被 `_prev_error_section` **或** `_impl_diagnosis_section` 完整透传到重派轮；若 `STATE.error` 在该路径上被其它写点覆盖（`dispatch.py` 有多处 `{"error": ...}` 写点），定位写点并保证死因不丢（实现记录写明实际取值来源）。**同时登记**：同一 dispatch 内的原地退避重试 attempt（`runner.py:1884` 子循环）重建 prompt 时 `STATE.error` / `_impl_diagnosis` 尚未更新（只在 dispatch 终结 `dispatch.py:867` 写入），故 attempt 2+ 无上轮死因——本 SPEC 不修复该控制流问题，只如实登记

## 3. 实现者车道结果捞回

- [x] 3.1 在 `core/agent_runner/result_gate.py` 实现车道无关的捞回 `salvage_result_from_transcript(project_root, spec_name, run_id, agent_type, wt_path=None, statuses=None) -> bool`：从 `.fenix/runs/<run_id>.jsonl` 的末轮 assistant 文本抽最后一个 fenced JSON（`status` 在白名单内即采用），落盘到按 agent_type 分派的目标路径（spec-review → `.fenix/spec-review/<spec>/.fenix-run-result.json`；implementer/fast-track → `impl_result_path(wt_path)`）。白名单按车道分派：spec-review 用 `spec_review_result_status_whitelist`（prompt_builder 导出，`result_gate.py:26` 已在导入）；implementer/fast-track 的白名单 MUST 经 `statuses` 参数由调用点传入（`_IMPL_RESULT_STATUSES` 是 `AgentRunner` 类属性，不得导出为模块常量，见 1.1）。本模块 MUST NOT `import runner`（D2b），既有 `_FENCED_JSON_RE` 需在 `result_gate.py` 另立模块级常量或由调用点传入
- [x] 3.2 捞回守卫（MUST 全部满足）：目标文件已存在 → 不覆盖直接返回 False；抽不出合法 JSON 或 `status` 不在白名单 → 不落盘返回 False；转录缺失/不可读 → 不落盘不抛异常返回 False；落盘 payload MUST 注入 `spec` 戳、与 agent 自写产物同构；成功时 MUST 写一条含 spec/run_id/status 的 WARNING 日志（MUST NOT 静默）
- [x] 3.3 `AgentRunner._salvage_spec_review_result(spec_name, run_id)` 保留为薄包装，委派到 3.1 的泛化实现（spec-review 路径与白名单行为逐字不变，`core/pm_engine/spec_review.py:191/220` 反射调用点与 `tests/test_review_circuit_breaker.py` 打桩对象继续可用）
- [x] 3.4 `runner.py` 新增 `_salvage_impl_result(spec_name, run_id, wt_path)` 薄包装（委派 3.1，agent_type 取 implementer/fast-track 判据由调用点传参），并在 `_run_claude` 返回后、**拷贝回主树块（`runner.py:1963` `wt_result = wt_path / ".fenix-run-result.json"` 处）之前**、`_check_agent_result_artifact` 硬门判定（`runner.py:1993`）之前调用——仅当本轮 run **自然收工**（`_run_claude` 正常返回、非取消/非异常路径，与 spec.md Scenario「自然退出（有 result 事件）」一致）、`agent_type in ("implementer","fast-track")`、`wt_path` 非 None 且 worktree 内结果文件不存在时；捞回成功则硬门自然放行。**插入点 MUST 在拷回块之前**：既有拷回块按 agent_type 注入 `role` / `spec` 戳并写主树副本 `<root>/.fenix/.fenix-run-result.json`，捞回若在其后执行，代写文件将不带 `role` 且主树无副本，与「落盘视图与 agent 自写产物同构」要求相悖；`wt_path is None`（测试/异常场景）MUST no-op 返回 False，MUST NOT 抛错

## 4. 结果文件缺失归因区分

- [x] 4.1 新增实现者车道归因入口（机械特征复用既有 `_classify_terminal_no_commit`：`<function_calls>` / fenced `<invoke` / fenced Edit|Write|Bash|NotebookEdit，正则常量 `runner.py:1157`），返回「格式回退截断」或「未收工即停」。**落位与签名 MUST 遵守 `result_gate.py` 模块契约**（文件头注释 + D2b：「本模块 MUST NOT `import runner`；门族函数首参为 `runner` 实例」）：落 `result_gate.py` 时签名 MUST 为 `classify_terminal_stall(runner, sub_run_id)`，MUST NOT 写成 `classify_terminal_stall(run_file)` 再 `import runner`；最保守形态是保留 `AgentRunner._classify_terminal_no_commit` 为唯一实现（旧名保留，MUST NOT 直接改名破坏既有测试），仅新增一层文案映射。**文案映射 MUST 显式**：既有方法无特征时返回「未提交即收工」（`runner.py:1193/1198`），本 SPEC 要求「未收工即停」——MUST NOT 改既有返回值（`tests/test_terminal_nocommit_gate.py:196/203` 断言该文案），MUST 由映射层产出新文案
- [x] 4.2 在 `AgentArtifactGateError` 捕获分支（`runner.py:2019` 附近）内：当 `agent_type in ("implementer","fast-track")` 且 error 文案含「结果文件缺失」时，把 4.1 的归因拼进 error 前缀（形如 `结果文件缺失（未收工即停）`）。**行数约束**：拼接实现 SHOULD 落在 `result_gate.py`（经 `runner` 参数注入），`runner.py` 侧只保留一行调用——`runner.py` 实测 3803 行，唯一硬约束是 `tests/test_agent_runner_modules_contract.py:170-173` 的 `< 4000`（现为**绿**，见注 1 更正；该测试不在本次 Deliverables 内，MUST NOT 改动），本 SPEC 增量 MUST NOT 使行数逼近上限。**归因文本 MUST 只拼进局部变量 `error`，MUST NOT 改动传给 `record_transient_break` 的 `str(e)`**——全局瞬断指纹记账读的是 `str(e)`（`runner.py:2040-2051`），把归因文案带进 `str(e)` 会污染 dispatch 闸门对瞬断风暴的可见性
- [x] 4.3 断言归因**只改文案不改控制流**：归因类别不同时重试次数、退避序列、resume 决策完全一致（用例覆盖两类别走同一路径）

## 5. 测试

- [x] 5.1 新增 `tests/test_impl_resultfile_contract.py`：实现者双车道契约段注入（两分支均含「先落盘再深入」「正文里的 JSON 不算交付」「判失败」「无后台节拍」要素）
- [x] 5.2 同文件：契约段路径按车道分派（implementer/fast-track 给出 worktree 根路径；planner-judge 仍给 `verify-progress` 路径；spec-review 仍给 `.fenix/spec-review/<spec>/` 路径）
- [x] 5.3 同文件：三车道（planner-plan / planner-judge / spec-review）契约段不回归——仍含契约段且路径逐字与变更前一致
- [x] 5.4 同文件：死因透传三态——`error` 有值含「结果文件缺失」/ 仅诊断有值（注入 attribution+conclusion）/ 两者皆无（零注入、无空标题段）；**并断言两者同时非空时字段级去重成立**——`_prev_error_section` 的输出除 `error` 原文外不含 `attribution` / `conclusion` / `progress` 条目（判据为字段级：`attribution := final_error[:500]` 与 `STATE.error` 同源，天然被 `error` 原文包含，MUST NOT 以子串计数作判据）
- [x] 5.5 同文件：捞回四态——末轮含合法实现者 JSON → 代写落盘并放行；目标文件已存在 → 不覆盖；`status` 非法 → 不落盘；转录缺失 → 不落盘不抛错
- [x] 5.6 同文件：归因两类别（含/不含假工具调用特征）文案区分且处置路径一致；转录缺失降级为「未收工即停」不抛错；既有 `_classify_terminal_no_commit` 返回文案不回归（「未提交即收工」仍被 `tests/test_terminal_nocommit_gate.py` 断言）
- [x] 5.7 定向回归：`tests/test_agent_prompt_files.py`、`tests/test_review_artifact_first.py`、`tests/test_agent_runner_gate.py`、`tests/test_scenario_static_check.py`（段序断言）、`tests/test_planready_artifact_gate.py`、`tests/test_agent_runner_modules_contract.py`、`tests/test_spec_review_artifact_gate.py`（`_salvage_spec_review_result` 四态直测，L152-193——捞回泛化 3.1/3.3 的**直接护栏**，本清单原缺）、`tests/test_terminal_nocommit_gate.py`（L196/203 断言「未提交即收工」文案不回归）、`tests/test_run_budget_continuity.py`（L110-144 `_impl_diagnosis_section` 断言）
- [x] 5.8 全量回归走有界入口 `python3 bin/run_full_suite.py --timeout 3600 --baseline <main-ref>`，失败逐项归类存量/引入并写入实现记录（`runner.py` 行数：硬约束 `< 4000`（`tests/test_agent_runner_modules_contract.py:170-173`）现为绿，本变更 MUST 保持其为绿；「≤3800」属 `refactor-agent-runner-module` 的收敛阈值，若被触及只登记不处置）
- [x] 5.9 独立 commit（实现与测试分开提交，提交信息 `[fenix] fix-impl-resultfile-contract-gap: <描述>`），并在实现记录中登记：helper `impl_result_path` 落位 `prompt_builder.py`（由 `result_gate` 导入，方向不可反）、2.3 的死因实际取值来源、原地退避 attempt 2+ 无上轮死因的登记结论

## 6. 收尾

- [x] 6.1 逐项核对 `## Deliverables` 声明与实现分支实际文件一致（new 文件存在、modify 文件有改动），并在实现记录中登记 `_classify_terminal_no_commit` 的最终处置选择（薄包装 vs 改名）与 `fast-track` 捞回的实际覆盖结论
- [x] 6.2 落位 `restart_request` 交付物（仓库根路径，JSON：`reason` / `origin` / `date`）并冒烟预演（全新进程 `import core.agent_runner.prompt_builder` + 断言实现者契约段在位），实际重启由 supervisor 消费该信号完成


## 实现记录（2026-09-17，实现者登记）

- **helper 落位**：`impl_result_path` 落在 `core/agent_runner/prompt_builder.py`
  （与 `planner_result_path` / `spec_review_result_path` 同处），由 `result_gate.py`
  导入使用——依赖方向 result_gate → prompt_builder 不可反（反向必成循环 import，
  `tests/test_agent_runner_modules_contract.py:71`「单独 import 三模块不触发循环
  import」契约红）。硬门 `_check_impl_result_artifact` 内部改用该 helper
  （`result_gate.py` 原式 `wt_path / ".fenix-run-result.json"` 等价替换，判定语义
  逐字不变）。
- **2.3 死因实际取值来源**：核实结论——「结果文件缺失」类 error 文本（形如
  `[provider-transient] exit 0 但结果文件缺失（implementer 产物硬门）: <path>`，
  `[provider-transient]` 前缀由 `runner.py` 加）经 `AgentRunResult.error` 到达
  dispatch 终结，写入 `STATE.error`（`dispatch.py:1319-1333` 的 `update_spec`
  `{"error": final_error}` 写点）→ 重派轮 `_prev_error_section`（`prompt_builder.py`
  `_prev_error_section` 读 `STATE.error`）注入；同时 `dispatch.py:867` 调用
  `_record_impl_diagnosis`（`dispatch.py:1538-1603`），其 `attribution :=
  final_error[:500]` 写入 `_impl_diagnosis` → 重派轮 `_impl_diagnosis_section`
  注入。两条来源在重派轮均可达（2026-09-17 复核实测）。实现者双车道
  （implementer `:268-285` / fast-track `:336-355`）均注入两段。
- **原地退避 attempt 2+ 无上轮死因（登记不修复）**：同一 dispatch 内的原地退避
  重试（`runner.py` `while True` 子循环）重建 prompt 时，`STATE.error` /
  `_impl_diagnosis` 只在 dispatch 终结（`dispatch.py:867`）写入——故 attempt 2+
  的 prompt 不携带 attempt 1 的失败原因（该次失败仍以 `[provider-transient]` +
  归因的 error 文本进入本次 run 的 `AgentRunResult.error`，但 `_build_prompt`
  读的是 STATE，不是本轮 error 局部变量）。修复需在 runner 内把上次 attempt 的
  error 传进 `_build_prompt`（控制流改动），本 SPEC 不主张修复（design D3）。
- **`_classify_terminal_no_commit` 最终处置选择**：**保留旧名 + 新增薄包装**
  （design D5 保守方案）。`result_gate.py` 新增 `classify_terminal_stall(runner,
  sub_run_id)` 薄包装委托 `AgentRunner._classify_terminal_no_commit`（唯一实现），
  文案映射层产出「未收工即停」；既有方法返回「未提交即收工」不变
  （`tests/test_terminal_nocommit_gate.py:196/203` 断言该文案，未破）。
  `_TERMINAL_NO_COMMIT_TOOL_PATTERN`（`runner.py` 类属性）未被修改。
- **fast-track 捞回实际覆盖结论**：**覆盖**（design Open Question 2 采纳）。
  `_salvage_impl_result` 薄包装同时服务 implementer / fast-track（agent_type 由
  调用点传参），走 `impl_result_path(wt_path)` + `_IMPL_RESULT_STATUSES` 白名单
  （经 `statuses` 参数传入，未导出为模块常量）；fast-track 结果文件的
  `verification` 段随 payload 原样落盘、白名单相同，不需额外分支。
- **捞回日志通道**：泛化 `salvage_result_from_transcript` 内部以标准 logging
  （`fenixd.agent_runner.result_gate`）写 WARNING（含 spec/run_id/status）——
  签名无 logger 参数（3.1 显式签名），不引入 `runner.logger` 依赖。
- **`_result_gate_section` 注入顺序**：implementer 分支注入在
  `_task_progress_contract_section` 之后、`_declared_reality_section` 之前；
  fast-track 分支注入在 `_task_progress_contract_section` 之后、
  `_scenario_freeze_section` 之前。`tests/test_scenario_static_check.py` 段序
  断言（「场景静态缺陷情报」先于「结果文件硬门」，planner-judge 车道）实测通过。
- **runner.py 行数**：改动后 `runner.py` 3787 行（基线 3803）——净减少 16 行
  （既有 `_salvage_spec_review_result` 64 行实现在 result_gate.py 泛化后降为
  薄包装）。`tests/test_agent_runner_modules_contract.py:170-173` 行数契约
  （本分支为 `test_runner_below_3800` `<= 3800`，主树为 `< 4000`）实测为绿。
