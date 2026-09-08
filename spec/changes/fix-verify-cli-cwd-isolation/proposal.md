# Proposal: fix-verify-cli-cwd-isolation

## Why

验证引擎的 cli 场景步骤在**主树**执行而非验证树，seed 型场景把测试夹具直接写进真实项目。事故实证（2026-09-08 两次）：add-draft-promotion-gate 验证轮的 `cli-seed-drafted-spec` 场景以 `Path('.')` 定位项目根写入 `.fenix/STATE.md` 与 `spec/changes/`，两次都落在主树——已删除的夹具 spec（verify-draft-bad / verify-draft-fixture）被 daemon 当真需求收编，自动晋升、派发实现/验证，反复烧钱且需人工反复摘除。

根因链（代码锚点）：
- `core/pm_engine/verification.py` 实例化 `VerifyEngine(spec_name, self._pm.project_root, ...)`——传入 daemon 主树根；serving worktree（`_ensure_serving_worktree` 创建，serve.cmd 以其为 cwd）路径**没有**传给引擎。
- `core/verify_engine/cli_runner.py` `_resolve_cwd`：无显式 cwd 的步骤缺省 `Path(self.project_root)`——docstring 写明「cwd 相对验证树根」，实现却是主树根。
- 断言无法发现污染：seed 步与 verify 步（grep `.fenix/STATE.md`）按同一错误 cwd 读写一致，场景照常 pass。

## What Changes

- `VerifyEngine` 增加验证场景执行根（scenario root）入参：command-worktree 轮传入本轮 serving worktree 根，无 serving worktree 轮回退主树根（行为不变）。
- 引擎把 scenario root 下发给各 Runner；`CliRunner._resolve_cwd` 缺省 cwd 改为 scenario root。
- 引擎簿记（`.fenix/verify-progress/` 场景/报告/进度文件）仍固定主树 `.fenix`，不受影响。
- 回归测试：worktree 轮 cli 步骤写 STATE/spec 落 worktree；无 worktree 轮回退不变。

## Capabilities

### New Capabilities

（无——修复既有验证引擎 cli 隔离缺陷）

### Modified Capabilities

- `verify-engine`（若能力目录名不同，以 spec/archive 中 add-verify-multi-kind-runner 的能力名为准）：cli 场景步骤缺省 cwd = 本轮验证树根（有 serving worktree 时），引擎簿记路径不变。

## Impact

- `core/pm_engine/verification.py`、`core/verify_engine/engine.py`、`core/verify_engine/cli_runner.py`（构造参数与 cwd 解析，无 API/协议变更）
- `tests/test_verify_cli_runner.py`（新增隔离用例）
- 风险面：既有 cli 场景若隐式依赖主树 cwd（读主树文件）在 worktree 轮会改读 worktree——worktree 是同 HEAD 检出，仓库内文件内容一致；仓库外/gitignored 路径（`.fenix/` 除外）不受影响。设计中评估并锁定。
