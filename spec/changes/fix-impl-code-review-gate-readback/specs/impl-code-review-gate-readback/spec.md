## MODIFIED Requirements

### Requirement: 收尾审查报告产物硬门

`verify.impl_code_review` 为 `true` 时，收尾审查产物硬门 MUST 按「worktree 优先、主树回退」
两处候选路径探测 `code-review.json`，而非只认 worktree 一处。

- worktree 内 `<wt_path>/.fenix/verify-progress/<spec>/code-review.json` 存在 → MUST 以其为
  判定对象（现状行为，零变化）。
- worktree 缺失时，MUST 回退探测 `<project_root>/.fenix/verify-progress/<spec>/code-review.json`。
- 两处候选路径经过同一套校验（`status` 白名单 / `findings` 与 `code_review.dispositions`
  逐条对账 / `rejected`/`deferred` 须附非空 `reason`），MUST NOT 双实现漂移。
- **两处均缺失**时才判失败，且失败文案 MUST 同时给出两个已探测位置。
- 开关为 `false` 时 MUST 仍为「零校验放行」（返回 None）。

#### Scenario: worktree 有报告 → 以其为准

- **WHEN** 开关开启，worktree 内存在合法报告（status=completed, findings=[]）
- **THEN** 门 MUST 返回 None（放行），且 MUST NOT 因主树同名文件缺失/陈旧而判失败

#### Scenario: worktree 缺失、主树有本轮新鲜报告 → 放行

- **WHEN** 开关开启，worktree 内无报告，主树 `<project_root>/.fenix/verify-progress/<spec>/code-review.json`
  存在、可解析、合法，且 mtime 晚于本轮启动（或本轮为 resume 复用 worktree）
- **THEN** 门 MUST 返回 None（放行）

#### Scenario: 主树报告陈旧 → 仍判失败

- **WHEN** 开关开启，worktree 与主树均无本轮报告；主树同名文件存在但 mtime 早于本轮启动
  且本轮非 resume 复用
- **THEN** 门 MUST 返回非 None（判失败），且文案 MUST 指明陈旧

#### Scenario: 两处皆缺 → 报缺失并给出两处路径

- **WHEN** 开关开启，worktree 与主树均无报告
- **THEN** 门 MUST 返回非 None，文案 MUST 含「报告缺失」与 `code-review.json`，且 MUST
  列出两个已探测位置

#### Scenario: 开关关闭零校验

- **WHEN** `verify.impl_code_review` 为 `false`（或 `verify` 节缺失）
- **THEN** 门 MUST 返回 None，且 MUST NOT 探测任何路径

#### Scenario: 无 worktree 载体时不误判

- **WHEN** `wt_path` 为 None 且 `runner.project_root` 不可得
- **THEN** 门 MUST 返回 None（缺载体时不校验，与现状 `wt_path is None → return None` 同语义）

## ADDED Requirements

### Requirement: 门对主树回退候选施加新鲜度守卫

主树回退候选 MUST 经与其它产物门同源的 `_check_artifact_json_file` 校验（存在 / 非空 /
mtime 新鲜 / 可解析 JSON），且 `is_resumed_worktree=True` 时 MUST 跳过硬拦 mtime。

`_check_impl_result_artifact` MUST 把 `run_started_at` 与 `is_resumed_worktree` 透传给
收尾审查产物门。

#### Scenario: resume 复用 worktree 时跳过新鲜度硬拦

- **WHEN** `is_resumed_worktree=True`，主树回退候选的 mtime 早于本轮启动
- **THEN** 门 MUST NOT 因 mtime 判失败，仍按内容判据校验

#### Scenario: 复用的 worktree 候选不做 mtime 硬拦

- **WHEN** worktree 内存在报告（任意 mtime）
- **THEN** 门 MUST 以其为判定对象（worktree 侧维持现状「不做 mtime 硬拦」的语义）
