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
候选路径会重复，MUST 去重（按 `Path.resolve()`），避免同一文件被判两次新鲜度。

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
- **风险**：`runner.project_root` 属性在替身测试里缺失。**缓解**：用 `getattr(runner, "project_root", None)`，
  为 None 时跳过主树候选（等价现状），不抛异常。
- **取舍**：门只读不写，主树有报告时**不会**把 worktree 补齐，故下次 run 仍可能重复触发同一场景。
  这是刻意的——写侧修正归姊妹 SPEC；门只负责「不在确定事实面前误判」。
