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

> 注 1：`core/agent_runner/runner.py` 当前 **3803 行**，已超 `tests/test_agent_runner_modules_contract.py`
> 的 ≤3800 契约（存量红，非本次引入）。实现者 **MUST NOT** 为腾行数做无关重构；若本 SPEC 新增行数使
> 差距扩大，须在实现记录中如实登记差距（该契约的处置归属 `refactor-agent-runner-module` 承接方）。
> 优先把捞回泛化与归因包装落在 `result_gate.py`，把 runner.py 增量压到最小。
>
> 注 2：`_salvage_spec_review_result` 的既有签名与语义是 `core/pm_engine/spec_review.py:191/220`
> 反射调用点与 `tests/test_review_circuit_breaker.py` 打桩对象的契约，**MUST 保留可用**。

## 1. 路径分派与契约段（根因修复）

- [ ] 1.1 在 `core/agent_runner/result_gate.py` 提取模块级 helper `impl_result_path(wt_path) -> Path`（返回 `wt_path / ".fenix-run-result.json"`），并让 `_check_impl_result_artifact` 内部改用该 helper（硬门判定语义逐字不变）；导出 `_IMPL_RESULT_STATUSES` 供注入侧同源引用
- [ ] 1.2 `core/agent_runner/prompt_builder.py`：把 `_result_gate_section` 签名扩展为 `(self, spec_name, agent_type="planner-judge", wt_path=None)`，内部按 agent_type 三分支计算路径——`spec-review`（既有早返回，行为与文案逐字不变）、`implementer`/`fast-track`（经 `impl_result_path` 取 worktree 根，`wt_path is None` 时降级为相对路径表述）、planner 族（既有 `planner_result_path` 路径）
- [ ] 1.3 新增实现者车道契约段文案（`_result_gate_section` 的实现者分支），要素齐全且每条以 MUST 句式写出：① 成功判定 = 进程正常退出 **且** 结果文件落盘且可解析非空 JSON；② **收工前未写 / 为空 / 非法 JSON → 本次 run 判失败并原地重派（整轮 token 重烧）**；③ **正文里的 JSON 不算交付**（框架只读文件）；④ **先落盘再深入**——在全量套件回归/交付物核实**之前**先写最小可判结果文件；⑤ 本车道**无后台节拍**——`ScheduleWakeup` 在派发模式下不产生唤醒，长任务 MUST 用前台有界入口 `python3 bin/run_full_suite.py --timeout 3600`（自身在超时内返回），MUST NOT 用「后台运行 + 轮询等待」编排
- [ ] 1.4 `_build_prompt` 的 `implementer` 分支（`agent_type == "implementer"` 块内）注入 `self._result_gate_section(spec_name, "implementer", wt_path)`
- [ ] 1.5 `_build_prompt` 的 `fast-track` 分支注入 `self._result_gate_section(spec_name, "fast-track", wt_path)`
- [ ] 1.6 `agents/implementer.md` 步骤 7/8 收工契约补硬约束措辞（未落盘=判失败、先落盘再深入），与动态契约段同源互补、不重复罗列全部要素
- [ ] 1.7 `agents/fast-track.md` PHASE 4 收工契约同步补同款硬约束措辞

## 2. 重试轮死因透传

- [ ] 2.1 `_prev_error_section` 扩展为「`STATE.error` ∪ 上轮 `_impl_diagnosis`」合并渲染：两者都有时 error 段在前、诊断摘要在后；仅诊断有时渲染诊断段（含 `attribution` / `conclusion` / `progress`）；都没有时**零注入**（首次派发提示词与现状逐字一致）
- [ ] 2.2 诊断是 JSON 文本（STATE `_impl_diagnosis` 以 JSON 字符串存），渲染前 MUST 容错解析——解析失败降级为原文截断呈现，MUST NOT 抛错；`attribution` 与 `conclusion` 渲染 MUST 各自截断（建议 500 / 800 字）避免提示词膨胀
- [ ] 2.3 确认「结果文件缺失」类 error 文本（形如 `[provider-transient] exit 0 但结果文件缺失（implementer 产物硬门）: <path>`）能被该段完整透传到重试轮；若 `STATE.error` 在该路径上被其它写点覆盖，定位写点并保证死因不丢（实现记录写明实际取值来源）

## 3. 实现者车道结果捞回

- [ ] 3.1 在 `core/agent_runner/result_gate.py` 实现车道无关的捞回 `salvage_result_from_transcript(project_root, spec_name, run_id, agent_type, wt_path=None) -> bool`：从 `.fenix/runs/<run_id>.jsonl` 的末轮 assistant 文本抽最后一个 fenced JSON（`status` 在白名单内即采用），落盘到按 agent_type 分派的目标路径（spec-review → `.fenix/spec-review/<spec>/.fenix-run-result.json`；implementer/fast-track → `impl_result_path(wt_path)`）
- [ ] 3.2 捞回守卫（MUST 全部满足）：目标文件已存在 → 不覆盖直接返回 False；抽不出合法 JSON 或 `status` 不在白名单 → 不落盘返回 False；转录缺失/不可读 → 不落盘不抛异常返回 False；落盘 payload MUST 注入 `spec` 戳、与 agent 自写产物同构；成功时 MUST 写一条含 spec/run_id/status 的 WARNING 日志（MUST NOT 静默）
- [ ] 3.3 `AgentRunner._salvage_spec_review_result(spec_name, run_id)` 保留为薄包装，委派到 3.1 的泛化实现（spec-review 路径与白名单行为逐字不变，`core/pm_engine/spec_review.py:191/220` 反射调用点与 `tests/test_review_circuit_breaker.py` 打桩对象继续可用）
- [ ] 3.4 `runner.py` 新增 `_salvage_impl_result(spec_name, run_id, wt_path)` 薄包装（委派 3.1，agent_type 取 implementer/fast-track 判据由调用点传参），并在 `_run_claude` 返回后、拷回前置块与 `_check_agent_result_artifact` 硬门判定**之间**调用（仅当 `agent_type in ("implementer","fast-track")` 且 worktree 内结果文件不存在时）——捞回成功则硬门自然放行

## 4. 结果文件缺失归因区分

- [ ] 4.1 在 `result_gate.py` 新增 `classify_terminal_stall(run_file) -> str` 薄包装，委派既有 `AgentRunner._classify_terminal_no_commit` 的机械特征（`<function_calls>` / `<tool_use` / `<parameter` / markdown fenced 工具名），返回「格式回退截断」或「未收工即停」（把既有私有方法泛化为可复用入口，旧名保留，MUST NOT 直接改名破坏既有测试）
- [ ] 4.2 在 `AgentArtifactGateError` 捕获分支（`runner.py:2019` 附近）内：当 `agent_type in ("implementer","fast-track")` 且 error 文案含「结果文件缺失」时，把 4.1 的归因拼进 error 前缀（形如 `结果文件缺失（未收工即停）`）
- [ ] 4.3 断言归因**只改文案不改控制流**：归因类别不同时重试次数、退避序列、resume 决策完全一致（用例覆盖两类别走同一路径）

## 5. 测试

- [ ] 5.1 新增 `tests/test_impl_resultfile_contract.py`：实现者双车道契约段注入（两分支均含「先落盘再深入」「正文里的 JSON 不算交付」「判失败」「无后台节拍」要素）
- [ ] 5.2 同文件：契约段路径按车道分派（implementer/fast-track 给出 worktree 根路径；planner-judge 仍给 `verify-progress` 路径；spec-review 仍给 `.fenix/spec-review/<spec>/` 路径）
- [ ] 5.3 同文件：三车道（planner-plan / planner-judge / spec-review）契约段不回归——仍含契约段且路径逐字与变更前一致
- [ ] 5.4 同文件：死因透传三态——`error` 有值含「结果文件缺失」/ 仅诊断有值（注入 attribution+conclusion）/ 两者皆无（零注入、无空标题段）
- [ ] 5.5 同文件：捞回四态——末轮含合法实现者 JSON → 代写落盘并放行；目标文件已存在 → 不覆盖；`status` 非法 → 不落盘；转录缺失 → 不落盘不抛错
- [ ] 5.6 同文件：归因两类别（含/不含假工具调用特征）文案区分且处置路径一致；转录缺失降级为「未收工即停」不抛错
- [ ] 5.7 定向回归：`tests/test_agent_prompt_files.py`、`tests/test_review_artifact_first.py`、`tests/test_agent_runner_gate.py`、`tests/test_scenario_static_check.py`（段序断言）、`tests/test_planready_artifact_gate.py`、`tests/test_agent_runner_modules_contract.py`
- [ ] 5.8 全量回归走有界入口 `python3 bin/run_full_suite.py --timeout 3600 --baseline <main-ref>`，失败逐项归类存量/引入并写入实现记录（`runner.py` 行数契约若仍红，登记为存量并注明归属）
- [ ] 5.9 独立 commit（实现与测试分开提交，提交信息 `[fenix] fix-impl-resultfile-contract-gap: <描述>`），并在实现记录中登记 1.1 的路径 helper 实际落位（`result_gate.py` 导出 / `prompt_builder.py` 持有）与 2.3 的死因实际取值来源

## 6. 收尾

- [ ] 6.1 逐项核对 `## Deliverables` 声明与实现分支实际文件一致（new 文件存在、modify 文件有改动），并在实现记录中登记 `_classify_terminal_no_commit` 的最终处置选择（薄包装 vs 改名）与 `fast-track` 捞回的实际覆盖结论
- [ ] 6.2 落位 `restart_request` 交付物（仓库根路径，JSON：`reason` / `origin` / `date`）并冒烟预演（全新进程 `import core.agent_runner.prompt_builder` + 断言实现者契约段在位），实际重启由 supervisor 消费该信号完成
