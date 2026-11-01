# stray-gitignore-deliverable-guard Spec

## ADDED Requirements

### Requirement: 散件首现 gitignore 草案的交付物豁免

框架 SHALL 在主树 untracked 散件首现提示的 gitignore 草案生成面（`core/worktree_manager/stray_wip.py` `_write_first_sight_alert`）对 `spec/` 交付物路径豁免：目录路径为 `spec` 或 `spec/` 前缀时，evidence MUST NOT 携带 `gitignore草案:` 字段，MUST 改携带交付物注记（spec/ 交付物目录不应 ignore，应提交入库）；description 与 recommended_action MUST 同步条件化，不得建议对该目录追加 .gitignore。非 spec 路径的草案生成行为 MUST 保持不变。首现提示本身对 spec/ 路径 MUST 保留（保留提醒人工提交的信号价值）。

#### Scenario: spec/changes 提案目录首现不携带 ignore 草案

- **WHEN** `spec/changes/<name>/`（如 arbiter 物化后滞留未提交的提案目录）作为目录型产物集合首次进入散件盘点
- **THEN** 首现提示照常发出，evidence 无 `gitignore草案:` 字段且含交付物注记，recommended_action 建议提交入库而非追加 .gitignore

#### Scenario: 非 spec 目录草案行为不变

- **WHEN** 普通运行时产物目录（非 `spec/` 前缀，如历史 build 产物目录形态）首次进入散件盘点
- **THEN** 首现提示的草案行、成因注释与 recommended_action 与改动前逐字一致

#### Scenario: 采纳面再无有害草案供给

- **WHEN** 同类首现提示（spec/ 路径）再次产生
- **THEN** 任何按 recommended_action 执行的处置都不可能把 spec/ 交付物目录写入 .gitignore（草案行已不存在）

### Requirement: spec-review 车道成文留痕收尾提交

spec-review run 的结果收尾路径（`core/agent_runner/result_gate.py` spec-review 分派点）SHALL 在评审结果文件成功落盘后，对本 run 触碰过的主树 `spec/changes/<spec>/` 目录执行 best-effort 单目录提交：`git status --porcelain` 有条目时 `git add` 该目录并 commit；porcelain 为空 MUST 跳过（不产空提交）；任何 git 失败 MUST 仅记 WARNING，MUST NOT 影响评审结果文件交付、退出码或评审终态判定。该收尾 MUST 与评审终态（approved/repaired/rejected）无关地执行。

#### Scenario: 评审修补 SPEC 文档后收尾提交

- **WHEN** spec-review run 在 `spec/changes/<spec>/` 内就地修补文档（repaired 形态）后收尾
- **THEN** 该目录被单目录提交，主树不再留有该目录的 untracked 散件，散件盘点下轮不再对其告警

#### Scenario: 无文档改动不产空提交

- **WHEN** spec-review run 收尾时 `spec/changes/<spec>/` 无任何变更或未跟踪条目（approved 形态、或 arbiter 物化时已提交）
- **THEN** 收尾跳过提交，不产生空提交

#### Scenario: 提交失败不阻断评审交付

- **WHEN** 收尾提交因 git 锁冲突、identity 缺失等原因失败
- **THEN** 框架记 WARNING 日志，评审结果文件照常落盘、进程退出码不变，评审终态判定不受影响
