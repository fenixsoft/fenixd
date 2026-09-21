# fix-impl-code-review-writepath — Tasks

## Deliverables

```yaml
- path: core/agent_runner/prompt_builder.py
  kind: modify
- path: core/agent_runner/runner.py
  kind: modify
- path: agents/implementer.md
  kind: modify
- path: agents/fast-track.md
  kind: modify
- path: tests/test_impl_code_review_gate.py
  kind: modify
- path: tests/test_agent_prompt_files.py
  kind: modify
- path: tests/test_runner_add_dir_injection.py
  kind: new
```

## 1. 提示词：收尾审查报告路径锚定 worktree

- [ ] 1.1 `core/agent_runner/prompt_builder.py` 的 `_impl_code_review_section`（`:611`）第 5 条「结果登记」：把报告落盘路径的表述由裸相对路径改为**显式强调「相对当前工作目录（worktree）」**，并增「MUST NOT 用主树绝对路径写此文件（主树同名目录不是本 run 的落点，硬门只读 worktree 内该路径）」一句；`report_path` / `raw_copy_path` 两个 f-string 取值本身不变（仍是相对路径 `.fenix/verify-progress/<spec>/code-review.json`），仅改周边文案
  - **定性**：本条是**防御性加固**而非既有缺陷修复——该段只被 implementer/fast-track 消费（`prompt_builder.py:425-426` 注入条件），而 `agents/implementer.md:31-33` 已明文要求相对路径，不存在「提示词诱导实现者拼绝对路径」的既有缺陷。加固本身合理，按此定性实现即可
  - **影响面（MUST 同步）**：改文案会使 §4.2 的「开关关闭零注入（逐字节不变）」断言与本文件 `## Deliverables` 中 `tests/test_impl_code_review_gate.py` 的范围说明、以及 proposal「Impact」段的测试清单**一并需要收紧**（断言对象由「段逐字节」细化为「报告路径字样仍为相对路径」）；proposal 非交付物、无需改，但实现者 MUST NOT 因「proposal 已列出该测试文件」而遗漏同一处的收紧
- [ ] 1.2 `_impl_code_review_section` docstring 补一段「路径语义」说明：implementer 的 `code-review.json` 是**唯一** in-worktree 的 verify-progress 产物（门 `result_gate._check_impl_code_review_artifact` 读 worktree、`_copyback_verify_progress` 单向 worktree→主树），与 verifier/planner/fast-track 的主树落点不同——防后续维护者复制造型
- [ ] 1.3 raw_copy 路径表述与 D4 同步（与任务 3.2 同轮，MUST NOT 只做其一）：`_impl_code_review_section` 的 raw_copy 分支（`:650` 及后续）现会嵌入**主树 verify-progress 的绝对路径**字样；去掉该车道主树 `--add-dir`（3.2）后，此处 MUST 一并收敛为 worktree 相对路径表述或「该文件仅框架读取、无需你写」，使提示词对实现者只指向 worktree 一处落点；收敛后报告路径（相对、worktree 内）字样 MUST 仍可识别（对应 spec 的「收紧后报告路径字样仍可达」Scenario，断言同步进 §4.2）

## 2. agent 契约：工作目录段消歧

- [ ] 2.1 `agents/implementer.md` 「工作目录（worktree 隔离，强制）」段第三条：改为「唯一例外：**worktree 内**的 `.fenix/verify-progress/`（框架已显式授权，用相对路径写）。这是当前工作目录内的 `.fenix/verify-progress/`，**不是主树的同名目录**；写主树同名目录会被收尾审查产物硬门判为『报告缺失』」
- [ ] 2.2 `agents/fast-track.md` 同段同条，做与 2.1 逐字一致的改写（两文件该条现状逐字相同，改写后仍应保持同款措辞，避免读侧分叉）

## 3. `--add-dir` 车道化注入

- [ ] 3.1 `core/agent_runner/runner.py` 的 `_run_claude`（`:3499-3513`）：抽出模块级常量 `_NO_MAIN_TREE_VERIFY_PROGRESS_LANES = ("implementer", "repair", "spec-review")`（紧邻 `_run_claude` 上方定义，附归因注释：这三条车道的 verify-progress 产物全在 worktree 内或别处，主树该目录不是其工作区）
- [ ] 3.2 `_run_claude` 构造 `cmd` 时按 `agent_type in _NO_MAIN_TREE_VERIFY_PROGRESS_LANES` 判定是否追加 `["--add-dir", str(progress_dir)]`；**缺省（`agent_type is None` 或表外值）MUST 保持追加**——maintenance/admin/dashboard 会话等既有调用点零行为变化；`progress_dir.mkdir(...)` 保持无条件执行（目录仍供 verifier/planner 与框架簿记使用，删除会造成无关副作用）
- [ ] 3.3 确认 `_run_claude` 的 `agent_type` 参数在 `_execute_agent_inner` 调用点（`:2053`）确实传入：现状 `_run_claude(..., spec_name=spec_name, agent_type=agent_type)` 已传；若发现任何**实现车道**的调用点未传 `agent_type`（导致精化失效），MUST 补传并登记于本任务说明——这是精化生效的前置条件

## 4. 测试

- [ ] 4.1 新增 `tests/test_runner_add_dir_injection.py`：直接构造 `AgentRunner`（或最小替身）调 `_run_claude` 前的参数组装路径，断言四条——① `agent_type="implementer"` 的 cmd 不含主树 `verify-progress` 的 `--add-dir`，且含 `--add-dir <worktree>`；② `agent_type="repair"` 同 ①；③ `agent_type ∈ {verifier, planner-plan, planner-judge, fast-track}` 的 cmd 含主树 `verify-progress` 的 `--add-dir`；④ `agent_type=None` 的 cmd 含主树 `verify-progress` 的 `--add-dir`（缺省零变化）。测试须用 `subprocess.Popen` 打桩捕获 `cmd`，不真起进程
- [ ] 4.2 `tests/test_impl_code_review_gate.py`：新增用例断言 `_impl_code_review_section` 输出含「相对当前工作目录（worktree）」与「MUST NOT 用主树绝对路径」两类字样，且报告路径字样仍为 `.fenix/verify-progress/<spec>/code-review.json`（1.3 收敛 raw_copy 表述后此断言 MUST 仍成立）；另增一条断言开关为 `false` 时该段零注入（逐字节不变）
- [ ] 4.3 `tests/test_agent_prompt_files.py`：新增用例读 `agents/implementer.md` 与 `agents/fast-track.md` 原文，断言工作目录段第三条含「worktree 内」限定与「不是主树的同名目录」提示，且 MUST NOT 再出现未限定的裸表述「验证进度目录 `.fenix/verify-progress/`（框架已显式授权）」

## 5. 收尾验证

- [ ] 5.1 跑受影响测试集（`tests/test_runner_add_dir_injection.py`、`tests/test_impl_code_review_gate.py`、`tests/test_agent_prompt_files.py`、`tests/test_agent_runner_gate.py`、`tests/test_characterization_agent_runner.py`）全绿
- [ ] 5.2 跑有界全量回归 `python3 bin/run_full_suite.py --timeout 3600`，确认零本次引入失败（允许既有环境性失败，须逐一列举并说明与本次改动无关）
