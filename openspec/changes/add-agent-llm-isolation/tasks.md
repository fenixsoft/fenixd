# Tasks: add-agent-llm-isolation

## 1. 隔离配置目录生成

- [ ] 1.1 在 `core/agent_runner.py` 新增隔离目录生成方法：`_ensure_agent_config_dir(provider_name) -> Path`，返回 `.fenix/agent-config/<provider_name>/`，不存在则创建
- [ ] 1.2 生成隔离 `settings.json`：`enabledPlugins` 从 `~/.claude/settings.json` 复制（缺省 `superpowers@claude-plugins-official`）；`hooks` 从 `.fenix/agent-settings.json` 复制（若存在）；`env` 仅复制 `~/.claude/settings.json` 中模型映射类键（`ANTHROPIC_DEFAULT_*`、`CLAUDE_CODE_SUBAGENT_MODEL`、`CLAUDE_CODE_MAX_CONTEXT_TOKENS` 等），**不得**包含 baseurl/apikey（spec: Provider 凭据不落盘）
- [ ] 1.3 在隔离目录建立 `skills` → `~/.claude/skills`、`plugins` → `~/.claude/plugins` 的 symlink，源不存在则跳过（spec: 源目录缺失时优雅降级）
- [ ] 1.4 生成逻辑幂等且线程安全：目录已存在则跳过重建，多 agent 并发首次创建无副作用（spec: 隔离目录按需生成且幂等）

## 2. agent 子进程隔离集成

- [ ] 2.1 修改 `_execute_agent`：当 `assignment`（Provider）非 None 时，把 `CLAUDE_CONFIG_DIR=<隔离目录>` 并入 `env_overrides`；`assignment is None` 时不设置（spec: 未配置 Provider 时透传当前 settings.json）
- [ ] 2.2 保持 Provider 的 baseurl/apikey/model 经 `env_overrides` 注入的现有逻辑不变（spec: Provider 配置时 agent 完全隔离并优先使用该 Provider）
- [ ] 2.3 保持 `--model` 覆盖逻辑不变：Provider 生效时用 `provider.sdk_model or subagent_model`，未配置时用 `subagent_model`（spec: 未配置 Provider 时保持现状）
- [ ] 2.4 确认 `_run_claude` 的 `env = os.environ.copy()` + `env_overrides` 路径下 `CLAUDE_CONFIG_DIR` 正常传递，且不影响未配置 Provider 的既有行为

## 3. 单元测试

- [ ] 3.1 新增/扩展 `tests/` 中对 `_execute_agent`/`_run_claude` 的测试：配置 Provider 时构造的 env 含 `CLAUDE_CONFIG_DIR` 且指向隔离目录；未配置时不含（spec: 未配置 Provider 时保持现状 / Provider 配置时完全隔离）
- [ ] 3.2 测试隔离 `settings.json` 内容：含 `enabledPlugins`/hooks/模型映射 env，不含 Provider apikey/baseurl 明文（spec: Provider 凭据不落盘）
- [ ] 3.3 测试隔离目录幂等性：连续两次调用不报错、symlink 与 settings.json 内容正确（spec: 隔离目录按需生成且幂等）
- [ ] 3.4 运行全量 pytest（`python3 -m pytest tests/ -q`）确认无回归

## 4. 集成验证与打包

- [ ] 4.1 在 `.fenix/config.yaml` 临时为 implementer 配置一个指向 Ark 的 Provider（`llm.providers` + `agents.models`）
- [ ] 4.2 触发一次 agent 运行，核对运行产物：`claude` 子进程带 `CLAUDE_CONFIG_DIR`、请求打到 Provider 且返回成功，init 事件含 `playwright-cli` 与 superpowers（spec: 隔离后技能与插件完整 / Provider 配置时请求打到 Provider）
- [ ] 4.3 恢复 `.fenix/config.yaml`（移除临时 Provider）或确认其保持有效，验证未配置 Provider 时行为与现状一致
- [ ] 4.4 运行 `bash scripts/package.sh` 生成最新扩展包
