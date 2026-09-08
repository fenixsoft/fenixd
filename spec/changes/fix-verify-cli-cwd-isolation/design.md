# Design: fix-verify-cli-cwd-isolation

## Context

- daemon 内 PMEngine 以主树根为 `project_root`；`verification.py` 阶段2实例化 `VerifyEngine(spec_name, self._pm.project_root, ...)`。
- serving worktree 由 `_ensure_serving_worktree` 创建于 `.fenix/verify-serving/<spec>-<ts>/`，路径登记在 `_contract_static_servers` 缓存（`CommandVerifyServer` 携带 worktree 路径），serve.cmd 以其为 cwd；但该路径从未传给 `VerifyEngine`。
- `CliRunner._resolve_cwd`：无显式 cwd → `Path(self.project_root)`＝主树根，与 docstring「cwd 相对验证树根」相悖。
- 事故（2026-09-08 两次）：`cli-seed-drafted-spec` 以 `Path('.')` 写主树 STATE/spec/changes，夹具 spec 复活并被 daemon 收编烧钱；断言读写同错一致，场景 pass 不可发现。

## Goals / Non-Goals

**Goals:**

- worktree 轮：cli 缺省 cwd = serving worktree 根，seed 型写入物理隔离在验证树
- 引擎簿记路径（verify-progress）零变化
- 无 worktree 轮行为零回归

**Non-Goals:**

- 不改 serve 启动机制（`_serve_command_in_worktree` 现状正确）
- 不改场景/契约协议格式（不新增必填字段）
- 不做「主树写拦截」类守卫（治本靠 cwd 正确；守卫留待后续按需立项）
- 不处理 web/api runner 的 cwd（它们按 base_url 访问实例，无文件系统写路径依赖）

## Decisions

1. **`VerifyEngine` 增可选参 `scenario_root: Path | None = None`**：None 时内部回退 `project_root`（无 worktree 轮与存量调用零变化）；`verification.py` 在 serving worktree 建立后取其根传入（`_contract_static_servers[spec_name]` 缓存中已有 worktree 路径，实现时从该缓存/`_ensure_serving_worktree` 返回值接线，注意实例复用路径同样带出 wt）。
2. **Runner 分发透传**：`engine._runner_for` 构造 Runner 时把 `scenario_root` 与 `project_root` 一并传入；`VerifyRunner` 基类加同名字段（默认 None→回退 project_root），仅 `CliRunner._resolve_cwd` 消费。
3. **簿记与执行根分离**：`engine.py` 中 `project_root / ".fenix" / "verify-progress"` 等簿记路径保持用 `project_root`，不换成 scenario_root——验收时逐点核对（433/452 行等）。
4. **测试策略**：`tests/test_verify_cli_runner.py` 增用例（tmp 目录双根：project_root 与 scenario_root，seed 式相对写落 scenario_root；无 scenario_root 时落 project_root）；`tests/test_verify_multi_kind.py` 补 engine 构造透传断言。不依赖真实 worktree/serve。

## Risks / Trade-offs

- **隐式依赖主树 cwd 的存量 cli 场景**：worktree 轮下改读 worktree——worktree 为同 HEAD 检出，仓库内文件一致；gitignored/仓库外路径本就不该被场景依赖（`.fenix` 写入正是本次要隔离的）。若个别场景确实要读主树运行时状态，应显式声明绝对路径或 `cwd`——实现时全库 grep 现有 `test_scenarios.json` 的无 cwd cli 步骤做一次影响清点，登记到实现报告。
- **实例复用路径漏传**：HEAD 未变复用已启动实例时 worktree 从缓存带出，需保证两条路径（新建/复用）都拿到 wt 根；用测试 2 钉住。
- **静态 main 轮的 seed 场景**：无 worktree 轮 seed 仍会写主树——现状此类契约（纯静态无实例）不含 seed 型场景；风险登记，若未来出现由守卫 SPEC 接管（见 Non-Goals）。
