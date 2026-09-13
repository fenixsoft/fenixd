# verify-runner-engine Delta: cli 场景执行根隔离

## ADDED Requirements

### Requirement: cli 场景步骤缺省 cwd 为本轮验证树根

当验证轮存在 serving worktree（`serve.kind=command` + `static_scope=worktree` 等经 `_ensure_serving_worktree` 创建的验证树）时，`VerifyEngine` 必须将该 worktree 根作为场景执行根下发给各 Runner；`CliRunner` 对未显式声明 `cwd` 的步骤以此执行根为缺省 cwd。引擎簿记（`.fenix/verify-progress/` 下的场景加载、报告、进度、截图）仍固定主树 `.fenix`，不随执行根改变。无 serving worktree 的验证轮，cli 缺省 cwd 维持主树项目根（既有行为零回归）。

#### Scenario: worktree 轮 seed 写入落验证树
- **WHEN** command-worktree 验证轮执行无显式 cwd 的 cli 步骤，步骤内以相对路径写 `.fenix/STATE.md` 与 `spec/changes/<name>/tasks.md`（seed 型场景）
- **THEN** 写入落在本轮 serving worktree 内，主树 `.fenix/STATE.md` 与 `spec/changes/` 无任何新增；步骤 exit_code 断言照常判定

#### Scenario: 引擎簿记路径不受执行根影响
- **WHEN** worktree 轮验证执行并产出报告
- **THEN** 场景加载、`report.json`、进度与截图仍读写主树 `.fenix/verify-progress/<spec>/`，路径与既有完全一致

#### Scenario: 无 serving worktree 轮回退主树 cwd
- **WHEN** 验证契约无 command 型 serve（static main / 纯 API 无实例），本轮无 serving worktree
- **THEN** cli 步骤缺省 cwd 为主树项目根，与修复前行为一致，存量 cli 场景全部照常通过
