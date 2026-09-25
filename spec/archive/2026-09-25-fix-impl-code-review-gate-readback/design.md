## Context

### 事实（2026-09-21 实测）

- 门函数 `_check_impl_code_review_artifact(runner, spec_name, wt_path, data)` 现状（`core/agent_runner/result_gate.py:502-625`）：
  ```python
  report_path = wt_path / ".fenix" / "verify-progress" / spec_name / "code-review.json"
  report_rel = f".fenix/verify-progress/{spec_name}/code-review.json"
  if not report_path.is_file():
      return f"exit 0 但收尾审查报告缺失（impl-code-review-gate）: {report_rel}"
  ```
  **单一候选路径、缺失即 return**，无任何回退。
- 调用点 `_check_impl_result_artifact`（`result_gate.py:746-752`）持 `run_started_at` 与
  `is_resumed_worktree`，但现状**未**把它们透传给本门。
- 主树 `<project_root>/.fenix/verify-progress/<spec>/code-review.json` 是框架 `--add-dir` 明确
  授权过的落点，也是 `_copyback_verify_progress` 的**目标**（worktree→主树单向）。即：主树有
  合规报告是「设计上可能且合法」的状态，门却完全无视它。

### 归因

读侧把「worktree 内没有」等同于「产物不存在」，而没有考虑「同一逻辑产物合法地存在于另一棵被授权
的树」。这与「读侧 fail-closed」的正当性边界有关：fail-closed 应针对**确实缺失**，而非**在另一
合法位置存在**。

## Goals / Non-Goals

**Goals**
- worktree 有合规报告 → 行为完全不变（worktree 优先）。
- worktree 缺失、主树有**本轮新鲜**的合规报告 → 放行。
- 两处都缺 → 报缺失，文案含两个已探测路径。
- 陈留主树报告（早于本轮启动且非 resume）→ 仍判失败。

**Non-Goals**
- 不做主树→worktree 回拷（门是只读判定，不产生写副作用）。
- 不改 status/findings/dispositions 的校验语义（复用同一套校验体）。
- 不改开关语义（关闭时仍零校验）。

## Decisions

### D1 抽出「校验体」，两处候选路径共用

把现状 `report_path.is_file()` 之后的全部校验逻辑抽成内层函数
`_validate_code_review_report(cr_data, data, report_rel) -> str | None`（模块级私有），
使 worktree / 主树两条路径读到数据后走**逐字相同**的校验，杜绝双实现漂移。

### D2 候选路径顺序：worktree 优先，主树回退

```python
candidates = []
if wt_path is not None:
    candidates.append(wt_path / ".fenix" / "verify-progress" / spec_name / "code-review.json")
candidates.append(runner.project_root / ".fenix" / "verify-progress" / spec_name / "code-review.json")
```

- worktree 存在 → 用它（现状行为，零变化）。
- worktree 缺失 → 用主树（且过新鲜度守卫）。
- 两处皆缺 → 返回缺失归因，文案列出两个路径。

**去重**：`wt_path` 与 `project_root` 相同时（无 worktree 的车道，或测试用 `tmp_path` 为 root）
候选路径会重复，MUST 去重（按 `Path.resolve()`），避免同一文件被判两次新鲜度。去重后保留的
候选 MUST 沿用**先出现者**的校验模式：`wt_path == project_root` 时按 worktree 语义（不做 mtime
硬拦）判定，以保现状零变化（既有测试 `tests/test_impl_code_review_gate.py` 的 `_gate` 即以
`tmp_path` 同时充当两者）。

**空候选集**：`wt_path` 为 None 且 `runner.project_root` 不可得（非 Path 载体）时候选集为空，
门 MUST 直接返回 None（缺载体不校验，与现状 `wt_path is None → return None` 同语义），
MUST NOT 落到 D4 的「两处皆缺」缺失归因——否则 spec「无 worktree 载体时不误判」场景
（要求返回 None）与 D4 相互矛盾。

**Path 载体校验**：主树候选 MUST 仅在 `isinstance(root, (str, Path))` 成立时才加入。
仅用 `getattr(runner, "project_root", None)` 不足以防替身：`MagicMock` 的任意属性都返回
可 truthy 的 mock，`mock / ".fenix"` 与 `mock.is_file()` 亦为 truthy，随后
`json.loads(mock.read_text())` 抛 `TypeError` 逸出 `_check_impl_code_review_artifact` 的
`except (OSError, json.JSONDecodeError)` 捕获面（实测见评审笔记），会使原有 mock 用例崩溃。

### D3 新鲜度守卫透传

`_check_impl_result_artifact` 把 `run_started_at` 与 `is_resumed_worktree` 透传给
`_check_impl_code_review_artifact`；后者对**主树回退**候选调用
`_check_artifact_json_file(path, "implementer", run_started_at, is_resumed_worktree=...)`
做存在/非空/新鲜/可解析校验（worktree 候选保持现状「只查 is_file + json.loads」，避免改变
现状对 worktree 的判定——现状 worktree 侧**不做** mtime 硬拦，这是有意的：本轮 run 写出的
文件本就晚于 run_started_at，加拦无收益且可能在时钟/挂载边界引入伪失败）。

**理由**：主树是**跨 run 共享**的树，陈留风险真实存在（本轮 `planner-judge` 就刚因主树陈留
`.fenix-run-result.json` 被判「结果文件早于本轮启动」）。worktree 是 run 专属，无此风险。

### D4 归因文案

两处皆缺时：

```
exit 0 但收尾审查报告缺失（impl-code-review-gate）:
.fenix/verify-progress/<spec>/code-review.json
（已探测 worktree 与主树两个位置）
```

保留原相对路径字样（既有测试 `test_enabled_report_missing` 断言 `"报告缺失" in err` 与
`"code-review.json" in err`，须继续成立），追加探测说明。

## Risks / Trade-offs

- **风险**：主树回退会否让「上一轮陈留报告」误过门？**缓解**：D3 新鲜度守卫 + 复用
  `_check_artifact_json_file`（其 `is_resumed_worktree` 语义已被 `add-worktree-verify-progress-copyback`
  家族验证）。
- **风险**：`runner.project_root` 在替身测试里缺失或非 Path（`MagicMock` 自动属性恒 truthy）。
  **缓解**：`getattr(runner, "project_root", None)` **且** `isinstance(root, (str, Path))` 双重判定，
  不满足即跳过主树候选（等价现状）、不抛异常。测试侧 MUST 把 `runner._check_artifact_json_file`
  接到模块级真实实现（`tests/test_impl_code_review_gate.py:273-278` 的 `_mock_runner` 是裸
  `MagicMock`，不接线则其 `_check_artifact_json_file` 恒回非 None mock 值，主树候选永远判失败）。
- **风险**：`is_resumed_worktree=True` 时新鲜度硬拦被跳过（D3 沿用语义）——resume 轮的主树
  陈留报告只剩内容判据（findings 与结果文件 `code_review.dispositions` 逐条对账）。**缓解/接受**：
  resume 轮本就以「上一轮产物可复用」为前提，且对账仍要求报告与**本轮**结果文件自洽；若日后
  出现 resume 轮误放行实测，再引入「主树候选须晚于本 spec 上一轮启动」的更细判据（本 SPEC 不做）。
- **取舍**：门只读不写，主树有报告时**不会**把 worktree 补齐，故下次 run 仍可能重复触发同一场景。
  这是刻意的——写侧修正归姊妹 SPEC；门只负责「不在确定事实面前误判」。
