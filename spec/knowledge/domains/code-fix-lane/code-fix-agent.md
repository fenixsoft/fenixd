# code-fix 修复 agent

<!-- knowledge: capability=code-fix-agent rev=1
     sources=spec/archive/2026-09-26-add-code-review-auto-fix -->

一等公民 agent 类型 `code-fix`：在隔离 worktree 内逐条修复审查台账条目并落盘处置结果。

## 规则

### 类型注册
- `code-fix` 在全部注册点保持一致，缺任一即实现不完整：`core/agent_runner/prompt_builder.py` 的 `AGENT_PROMPT_FILES` 含 `"code-fix": "code-fix.md"`；`core/agent_runner/run_files.py` 的 `RUN_ID_AGENT_PREFIXES` 含 `("code-fix-", "code-fix")`；`core/config.py` 的 `KNOWN_AGENT_TYPES` 含 `"code-fix"`；`.fenix/config.template.yaml` 的 `agents.models` 含 code-fix 模型分配示例；框架根 `agents/code-fix.md` 提示词文件存在。
- run_id 前缀归属无子串冲突：`code-review-100` 归属 `code-review`、`code-fix-100` 归属 `code-fix`，互不错配；Dashboard 时间线显示 `code-fix` agent 类型而非泛型。

### 模型链
- 模型分配解析链依次为：`agents.models.code-fix` → `agents.models.code-review` → `agents.models.self-review` → `agents.models.administrator` → 默认网关；链上首个命中项决定 provider（baseurl/apikey/env）与 model，按既有 `_get_agent_model_assignment` + `_ensure_agent_config_dir` 形态注入子进程环境。
- 未登记 `agents.models.code-fix` 时回退 `agents.models.code-review`（与 code-review 完全相同的 llm 配置），不得直接跳到默认网关而无回退。
- 显式配置 `agents.models.code-fix` 时独立生效，不被 code-review 的配置覆盖。

### 写权限与产物契约
- 派发经 `worktree_manager.create(spec_name="code-review-fix", agent_type="code-fix")` 创建独立 worktree，agent 工作目录为该 worktree，不得为主树；运行中主树工作区保持不变。
- 每处置完一条问题，向框架注入的 out 文件（绝对路径，`<worktree>/.fenix/code-review/fix-out-<run_id>.jsonl`）追加一行，字段至少含 `item_id`、`status`（`fixed` | `skipped`）、`file`；逐条增量落盘，不等全批处置完。
- 修复提交到当前 worktree 的分支；merge-back 由框架完成，agent 不得执行。
- 不得修改 `.fenix/` 下的框架运行时文件或台账 `items.jsonl`（条目状态由框架在合回成功后更新）。
- 仅处理注入清单中的条目，不得顺手重构清单外代码。
- 产物缺失判失败：退出码 0 但 out 文件不存在或零有效行时，该批判失败（不合回、不置条目 `resolved`），不得把空跑当成功。

## 溯源

- [2026-09-26 2026-09-26-add-code-review-auto-fix](spec/archive/2026-09-26-add-code-review-auto-fix/) — 新建本页：agent 类型四处注册点、模型链缺省回退 code-review、worktree 写权限与逐条 out 文件产物契约（产物缺失判失败）。
