## Why

`add-freeze-stop-inflight-agents` 的收尾阶段（2026-09-21）连续 7 次原地重试全部失败于同一句门禁归因：

```
[artifact-structural] [provider-transient] exit 0 但收尾审查报告缺失（impl-code-review-gate）:
.fenix/verify-progress/add-freeze-stop-inflight-agents/code-review.json
```

但实现者实际上**确实生成了**这份报告（ocr 审查 9 文件 0 findings，`status: completed`），并且连续 4 个 attempt 的自检都打印「ALL GATES PASS」。根因是**写盘路径与门检路径不是同一棵树**：

- 实现者的 `cwd` 是 run 专属 worktree；提示词 `_impl_code_review_section` 给出的落盘路径
  `.fenix/verify-progress/<spec>/code-review.json` 是**相对 worktree** 的；
- 但同一份提示词里 `agents/implementer.md:33` 又写着「唯一例外：验证进度目录
  `.fenix/verify-progress/`（框架已显式授权），按框架指引写」，而 `runner._run_claude`
  无条件注入的 `--add-dir <主树>/.fenix/verify-progress` 把这个「授权目录」实体化为
  **主树**的绝对路径；
- 实现者于是按绝对路径写进了**主树** `/root/fenixd/.fenix/verify-progress/...`，worktree
  内从头到尾没有这个目录；
- 产物硬门 `_check_impl_code_review_artifact` 读的却是 `wt_path / ".fenix" /
  "verify-progress" / <spec> / "code-review.json"`（worktree），恒判缺失；
- `_copyback_verify_progress` 是 **worktree → 主树** 单向，worktree 侧为空即零动作，
  门永远看不到那份已经写好的报告。

读写两侧永远对不上，直到实现预算耗尽。这是「交付物声明读一侧、实现写另一侧」错层的又一实例
（同族：`fenixd-declaration-readsource-scope-mismatch`）。

## What Changes

- **提示词去误导（实现侧）**：`core/agent_runner/prompt_builder.py` 的
  `_impl_code_review_section` 把报告落盘路径的表述从裸相对路径改为**显式强调「worktree 内相对
  路径」**，并显式禁止用主树绝对路径落该文件。
- **agent 契约去误导**：`agents/implementer.md` 与 `agents/fast-track.md` 的「工作目录」段把
  「唯一例外：验证进度目录 `.fenix/verify-progress/`（框架已显式授权）」改写为**「worktree 内
  的 `.fenix/verify-progress/`，用相对路径写」**，消除「授权 = 可以写主树该目录」的误读。
- **`--add-dir` 精准化（实现侧）**：`core/agent_runner/runner.py` 的 `_run_claude` 不再对
  **没有主树 verify-progress 落点的车道**（implementer / repair）注入
  `--add-dir <主树>/verify-progress`——它们的唯一 verify-progress 写入是 worktree 内的
  `code-review.json`（相对路径，cwd 已在授权范围内）。verifier / planner-plan / planner-judge /
  fast-track 这些**确有**主树 verify-progress 绝对路径落点的车道保持不变。

## Capabilities

### New Capabilities

- `impl-code-review-writepath`: 实现车道收尾审查产物的写盘路径正确性——提示词与 agent 契约显式
  锚定「worktree 内相对路径」，`--add-dir` 只授予车道真实需要的目录。

## Impact

- 受影响代码：`core/agent_runner/prompt_builder.py`、`core/agent_runner/runner.py`、
  `agents/implementer.md`、`agents/fast-track.md`。
- 受影响测试：`tests/test_impl_code_review_gate.py`、`tests/test_agent_prompt_files.py`。
- 行为影响面：仅在 `verify.impl_code_review` 开关关闭时**零变化**（该段零注入）；开关打开时，
  implementer/repair 轮次不再获得主树 verify-progress 的 `--add-dir`，其余车道不变。
- 非目标：不改变门禁的判据语义（本 SPEC 只修正写侧；读侧回退由姊妹 SPEC
  `fix-impl-code-review-gate-readback` 承担）。
