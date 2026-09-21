## Context

2026-09-21 实测（`add-freeze-stop-inflight-agents` 收尾卡死，7 次原地重试 ~$3.4/次全数失败）。

### 事实

- `runner._run_claude`（`core/agent_runner/runner.py:3499-3513`）**无条件**为每个 run 注入
  两个 `--add-dir`：`str(cwd)`（worktree 或主树）与 `str(self.project_root / ".fenix" /
  "verify-progress")`（**主树**）。
- `agents/implementer.md:33` 与 `agents/fast-track.md:81` 都写着「唯一例外：验证进度目录
  `.fenix/verify-progress/`（框架已显式授权），按框架指引写」。
- `prompt_builder._impl_code_review_section`（`core/agent_runner/prompt_builder.py:649-650`）
  给出的报告落盘路径是相对路径 `.fenix/verify-progress/<spec>/code-review.json`。
- 实现者实际写盘命令（run 转录 `.fenix/runs/archive/impl-add-freeze-stop-inflight-agents-1789944158-a1.jsonl`
  `2026-09-20T23:23:33Z` / `23:59:14Z`，a1-r3 `2026-09-21T00:58:15Z`）用的是**主树绝对路径**
  `/root/fenixd/.fenix/verify-progress/add-freeze-stop-inflight-agents/code-review.json`。
- worktree 内 `.fenix/` 从头到尾**没有** `verify-progress/` 子目录（2026-09-21 09:14 才由下一轮 run
  创建）。
- 门 `result_gate._check_impl_code_review_artifact`（`result_gate.py:531`）读的是
  `wt_path / ".fenix" / "verify-progress" / <spec> / "code-review.json"`，恒判「报告缺失」。

### 归因

「授权目录」的措辞 + `--add-dir` 主树路径把「verify-progress 是主树共享目录」这一（对 verifier /
planner 成立的）事实**外溢**到了 implementer 车道，而 implementer 的对应产物（`code-review.json`）
按门与提示词都应在 **worktree 内**。实现者据「授权 = 可以写这里」选择绝对路径写主树，两侧分叉。

## Goals / Non-Goals

**Goals**
- implementer 车道收尾审查报告稳定落 in-worktree，门一次通过。
- 消除「验证进度目录」措辞与 `--add-dir` 注入对 implementer 车道的误导。
- 开关关闭时零行为变化。

**Non-Goals**
- 不改门禁判据语义（读侧容错由姊妹 SPEC `fix-impl-code-review-gate-readback` 承担）。
- 不改 `block-main-tree-write.py`（该 hook 是 gitignored 自举物，worktree 内不可达、主树只读，
  无法作为本仓库交付物；见「约束」）。
- 不改 verifier / planner / fast-track 的主树 verify-progress 落点（它们**确实**写主树）。

## Decisions

### D1 提示词与 agent 契约显式锚定「worktree 内相对路径」

`_impl_code_review_section` 的报告路径表述改为：

> 把规整契约写入 `.fenix/verify-progress/<spec>/code-review.json`（**相对当前工作目录
> （worktree）的相对路径**）；MUST NOT 用主树绝对路径写此文件。

`agents/implementer.md` 与 `agents/fast-track.md` 的「工作目录」段第三条改为：

> - 唯一例外：**worktree 内**的 `.fenix/verify-progress/`（框架已显式授权，用相对路径写）。
>   注意：这是**当前工作目录（worktree）内**的 `.fenix/verify-progress/`，不是主树的同名目录；
>   写主树同名目录会被产物硬门判为「报告缺失」。

### D4 raw_copy 路径表述与 D2 同步收敛

`_impl_code_review_section` 内除 `report_path`（`:649`）外的**第二处**路径字样是 raw_copy 段
（`raw_copy_path`，`:650` 与后续分支）：该段会把**主树 verify-progress 的绝对路径**字符串
嵌进提示词。D2 去掉该车道的 `--add-dir <主树>/verify-progress` 后，若仍保留该绝对路径字样，
提示词里会留下一处「被显式引用、却已不在授权目录内」的主树路径——二义照旧存在，只是换了
位置。二者 MUST 同轮一起收敛，取以下任一写法（实现者择一，须与 §4.2 断言同步）：

- 改为 worktree 内相对路径表述，或
- 明确写成「该文件仅框架读取、无需你写」（不给出可执行落点）。

**不变量**：无论取哪种写法，报告路径（相对、worktree 内、供门读取）字样 MUST 仍可被识别
（见 spec「收紧后报告路径字样仍可达」Scenario）——不得因去掉绝对路径字样而连带删掉报告
落盘指示。

**理由**：本 SPEC 的全部价值在「消除诱导」，判据是提示词对实现者**只**指向 worktree 一处
落点；留下任何主树绝对路径字样都让该判据失效（测试只看若干字样，看不出二义）。

**理由**：根因是措辞歧义。事实层面 implementer 的 `code-review.json`（门读 worktree）、
fast-track 的 `{result_path}`/`{scenarios_path}`（主树，经 `--add-dir`）语义本就不同，
提示词必须逐车道说清，不能让「验证进度目录」一词同时指两棵树。

### D2 `--add-dir <主树>/verify-progress` 只授予真实需要的车道

`_run_claude` 的 `--add-dir progress_dir` 注入改为按 `agent_type` 判定：

| agent_type | 主树 verify-progress 落点 | 是否注入 |
|---|---|---|
| `verifier` | `<主树>/verify-progress/<spec>.json`、`<spec>/report.json`（`prompt_builder.py:181,187-190`） | **注入** |
| `planner-plan` | `<主树>/verify-progress/<spec>/test_scenarios.json` | **注入** |
| `planner-judge` | `<主树>/verify-progress/<spec>/.fenix-run-result.json`、`report.json` | **注入** |
| `fast-track` | `<主树>/verify-progress/<spec>/{result_path,scenarios_path,progress_path}`（`agents/fast-track.md:71`） | **注入** |
| `dispute-judge` | `<主树>/verify-progress/<spec>/dispute_judge_result.json` | **注入** |
| `administrator` | 修正 `<主树>/verify-progress/<spec>/test_scenarios.json`（`agents/administrator.md:19`） | **注入**（cwd 已是主树，`--add-dir` 冗余但无害；保留以维持现状） |
| `implementer` | 无（其 `code-review.json` 在 worktree 内） | **不注入** |
| `repair` | 无 | **不注入** |
| `spec-review` | 无（写 `.fenix/spec-review/`） | **不注入**（现状即 `cwd=主树`，`--add-dir` 冗余） |

**理由**：`--add-dir` 是「这个目录是你工作区的一部分」的显式信号；对 implementer 而言，
主树 verify-progress 恰恰**不是**它的工作区（它的产物在 worktree），注入本身就在制造机会。

**实现约束**：默认（`agent_type` 为 `None` 或未知）**保持注入**——`_run_claude` 的既有调用点
（maintenance / admin / dashboard 会话等）语义不变，只有显式列出的 `implementer`/`repair`/
`spec-review` 三个值不注入。这与「开关关闭零变化」无关（那是 `_impl_code_review_section` 的
关注点），是车道级注入精化。

### D3 不改 hook（约束而非选择）

`block-main-tree-write.py`（`.fenix/hooks/`）是 gitignored 自举部署物：
`git check-ignore .fenix/hooks/block-main-tree-write.py` 命中 `.gitignore:26`。本仓库
Deliverables 段声明 gitignored 路径会被晋升 lint 拒绝，且 worktree 内该文件不存在、主树只读
——**无法作为 SPEC 交付物**。故本 SPEC 只做「不再诱导 + 车道化注入」，读侧兜底由姊妹 SPEC 承担。

## Risks / Trade-offs

- **风险**：`--add-dir` 精化后，若某 lane 依赖了未列出的主树目录，会静默失效。**缓解**：
  只在 `agent_type in ("implementer", "repair", "spec-review")` 时跳过，且这三个 lane 的主树
  写入面已有明确清单（`grep --add-dir` 使用点），测试逐 lane 断言。
- **风险**：改 `agents/*.md` 影响所有车道（两文件被 implementer/fast-track 共享）。**缓解**：
  只改「工作目录」段的第三条，措辞收敛，`tests/test_agent_prompt_files.py` 增断言。
- **取舍**：不改 hook 意味着仍有「绝对路径写主树 + hook 放行」的残余通道。**缓解**：读侧
  回退（姊妹 SPEC）使该通道即使发生也不再卡死。
