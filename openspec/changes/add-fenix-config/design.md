# Design: LLM 模型分配与审批模式配置

## Context

Fenixd 当前架构（`fenixd.py` → `core/config.py` + `.fenix/config.yaml` → `PMEngine` / `AgentRunner` → `claude` CLI 子进程 → `WorktreeManager`）：

- **Agent 角色**：`implementer`（执行）、`planner-plan`（规划/生成场景）、`planner-judge`（判定）、`verifier`（旧版单体验证，`use_new_verifier=false` 时使用）。
- **模型选择现状**（`agent_runner._run_claude`）：所有 Agent 统一继承 daemon 启动时的环境变量（`ANTHROPIC_MODEL` / `ANTHROPIC_BASE_URL` / `ANTHROPIC_API_KEY`，当前指向火山代理的 `deepseek-v4-flash`）。`agents.subagent_model`（默认 `claude-sonnet-5`）仅作为 `--model` 传入，用于通过 claude-code SDK 的模型名校验（子代理派生路径对非官方模型名会报 `unrecognized_model` 致命错误）；真实请求仍走 `ANTHROPIC_BASE_URL` 代理。
- **审批门禁现状**：`gates.require_push_approval: true` 存在于模板但未在代码中使用。真实 push 由 `/fenix-approve` skill 在 Claude 会话内执行（`git push origin fenix/<spec>` + StateMachine 标记 `pushed`）。
- **配置持久化**：`.fenix/config.yaml` 由 `fenix-init` 从 `config.template.yaml` 渲染生成，已 gitignore；启动时一次性加载，无热加载。
- **Dashboard**：`core/dashboard/`（http.server，仅 GET，绑定 127.0.0.1，跨项目监控）。

用户诉求：① 多 LLM Provider + 按 Agent 分配模型（未分配 = 现状默认模型）；② 审批模式 manual / auto（auto = done 后自动 git push + pushed）。配置写入 `.fenix/config.yaml`，Dashboard 可视化编辑，重启 daemon 生效。

## Goals / Non-Goals

**Goals:**
- 提供可手工编辑 + Dashboard 可视化的 LLM Provider 注册表与 Agent 模型分配。
- 提供 manual / auto 两种审批模式，auto 模式在 SPEC 到达 done 后自动 push 并标记 pushed。
- 未分配模型的 Agent 完全维持现状行为（默认模型）。
- 配置持久化于 `.fenix/config.yaml`，向后兼容现有配置文件（新字段缺省 = 现状）。

**Non-Goals:**
- 不做配置热加载（用户确认：重启 daemon 生效）。
- 不引入 OpenAI 兼容协议适配（claude CLI 仅支持 Anthropic 协议，Provider 均为 Anthropic 兼容端点）。
- 不改造 `/fenix-approve` 的人工审查流程（manual 模式保持现状）。
- 不新增外部依赖（沿用标准库 + pyyaml）。

## Decisions

### D1: 配置 Schema —— 扩展现有 `.fenix/config.yaml`

```yaml
llm:
  providers:
    - name: "volc-engine"            # 唯一标识，被 agents.models 引用
      baseurl: "https://api.example.com"
      apikey: "sk-xxx"               # 敏感字段，.fenix/config.yaml 已 gitignore
      model: "deepseek-v4-flash"     # 该 Provider 的默认模型名（真实路由用）
      sdk_model: "claude-sonnet-5"   # 可选；用于通过 claude-code SDK 模型名校验

agents:
  models:                            # 未列出 = 该 Agent 使用默认模型（现状）
    implementer:
      provider: "volc-engine"
      model: "deepseek-v4-flash"
    planner-plan:
      provider: "volc-engine"
      model: "deepseek-v4-pro"

gates:
  approve_mode: "manual"             # "manual" | "auto"，默认 manual
```

- **替代方案**：新建独立配置文件 —— 被用户否决（确认扩展现有文件）。
- **理由**：复用 `ConfigLoader` 与加载管线；缺省时各能力不激活，与旧配置完全兼容。
- **Agent 角色键名**：使用 `agent_runner` 现有字符串 `implementer` / `planner-plan` / `planner-judge` / `verifier`，与派发逻辑一一对应。

### D2: 模型路由 —— 运行期为已分配 Agent 注入环境变量，`--model` 保持官方名校验

`agent_runner._run_claude` 增加按 agent_type 解析模型分配的逻辑：

- 该 Agent 在 `agents.models` 中有分配 → 解析出 `provider` 与 `model`：
  - `env["ANTHROPIC_BASE_URL"] = provider.baseurl`
  - `env["ANTHROPIC_API_KEY"] = provider.apikey`
  - `env["ANTHROPIC_MODEL"] = 分配的 model`
  - `--model` 取 `provider.sdk_model or agents.subagent_model`（官方名，延续现有 SDK 校验 workaround）。
- 未分配 → 完全维持现状（不注入任何覆盖，`--model` 仍为 `agents.subagent_model`）。

- **替代方案 A**：直接 `--model <分配的模型名>` —— 被否：子代理派生路径对非官方模型名报 `unrecognized_model` 致命错误（现有代码注释已明确）。
- **替代方案 B**：仅设 `--model`、不碰 env —— 被否：无法表达 Provider 的 baseurl/apikey，且模型名可能非官方。
- **理由**：沿用代码中已被验证可行的「env 承载真实路由 + `--model` 官方名过 SDK 校验」模式，最小改动、行为可预期。
- **注**：真实模型选择最终由 Provider 代理（如火山）根据 env/请求决定；运行期正确性由实现者按该模式落地，并在测试中验证 env 注入正确。

### D3: 自动审批 —— 下沉 git push 到 daemon

`pm_engine` 在 SPEC 到达 `done` 后判定审批模式：

- `_on_spec_done`（及已验证的 `_on_spec_verified` → done 路径）结束时，若 `gates.approve_mode == "auto"` 且该 SPEC 尚未 `pushed`，调用新增的 `_auto_approve(spec_name)`：
  1. 解析分支名：优先 `STATE.md` 的 `branch` 字段，否则 `{worktree.implement_branch_prefix}/{spec_name}`（默认 `fenix/<spec_name>`）。
  2. 在 `project_root` 执行 `git push origin <branch>`（subprocess，超时保护）。
  3. 成功 → `transition(spec_name, "pushed")` + PROJECT_LOG 记录；失败 → 保留 `done` 状态并记 error，人工 `/fenix-approve` 兜底。
- `approve_push` 保留原语义（真实 push 由调用方决定），新增 `_auto_approve` 内部复用同一 transition。
- **替代方案**：仅在 config 里切换而由 skill 判断 —— 被否：skill 是会话层，无法在「无人值守」时自动触发；自动模式必须由 daemon 驱动。
- **风险**：自动 `git push` 是显著外向行为 → 默认 `manual`，只有用户显式改 `auto` 才启用；失败不静默，保留 done 供人工介入。

### D4: Dashboard 配置页 —— 新增 REST 端点 + 前端视图

Dashboard 由只读（GET）扩展为可写配置：

- `GET /api/config?project=<name>` → 返回该项目的解析配置（含 `llm` / `agents.models` / `gates.approve_mode` 等；apikey 原样返回，UI 用 password 型输入框）。
- `POST /api/config?project=<name>`（`do_POST` 新增）→ 接收 JSON 配置体：
  1. 合并到现有配置（只更新受管键：`llm`、`agents.models`、`gates.approve_mode`，其余键原样保留）。
  2. 校验（复用 ConfigLoader 校验 + 新增字段校验）。
  3. 原子写回 `.fenix/config.yaml`（临时文件 + rename）。
- **文件头注释**：直接 `yaml.safe_dump` 会丢失注释与排版。`.fenix/config.yaml` 由模板生成、已 gitignore，注释丢失可接受；但需在文件头部保留/追加一段说明注释块（「Dashboard 或手工编辑生成，重启 daemon 生效」）。
- **前端**：新增「配置」Tab，包含 Provider 列表（增删改）、Agent 模型分配下拉（未分配 / 指定 provider+model）、审批模式单选；保存后提示「重启 daemon 生效」。
- **安全**：仅 127.0.0.1；`POST` 请求体限长（如 256KB）；写路径做路径校验（仅允许已注册项目）。

### D5: 配置校验 —— 向后兼容 + 新增字段校验

`ConfigLoader._validate` 保持 REQUIRED_KEYS 不变（旧配置不破坏）。新增字段存在时校验：

- `llm.providers`：须为 list，每项含 `name` / `baseurl` / `apikey`；`name` 唯一。
- `agents.models`：键须为已知 agent_type；每项的 `provider` 须引用已定义 Provider；`model` 非空字符串。
- `gates.approve_mode`：`"manual"` 或 `"auto"`。
- 校验失败 → 拒绝写入（Dashboard 返回 400 + 错误信息），避免坏配置导致 daemon 起不来。

### D6: 模板同步

`config.template.yaml` 同步新增 `llm.providers`（示例注释）、`agents.models`、`gates.approve_mode` 骨架，保证 `fenix-init` 新生成项目自带新字段说明。旧的已生成 `.fenix/config.yaml` 缺省即可（能力不激活）。

## Risks / Trade-offs

- [Provider 代理可能依据请求体 model 字段而非 env 决定实际模型] → 沿用现有已验证的「env 路由 + `--model` 官方名」模式；实现期用一次真实运行确认请求确实走了分配模型，若代理以请求体为准则调整 `--model` 为分配模型（在 auto 主 agent 路径，SDK 校验风险低于子代理路径）。
- [自动审批意外推送] → 默认 `manual`；auto 仅显式开启；推送失败保留 done 状态并记录 error。
- [yaml.safe_dump 丢失手写注释] → 配置页写回时统一保留头部说明注释；手工编辑者可通过模板注释了解字段含义。
- [跨项目 Dashboard 写配置越权] → 写端点仅接受已注册项目路径（registry 校验），且仅本机可达。
- [旧配置升级] → 新字段缺省即现状，`fenix-init` 模板同步新字段，无迁移负担。

## Migration Plan

1. 实现核心：config schema + ConfigLoader 校验 + agent_runner 路由 + pm_engine 自动审批 + dashboard 端点与前端。
2. 更新 `config.template.yaml`；现有 `.fenix/config.yaml` 可不改（缺省 = 现状）。
3. 单元测试覆盖解析/校验/路由判定/审批判定；手动回归 Dashboard 配置编辑。
4. 部署：重启 daemon 生效。

## Open Questions

- 是否需要按 Provider 级联的「默认模型」作为未分配 Agent 的兜底（当前设计：不设全局兜底，未分配即现状环境变量模型）—— 按用户「不分配就是当前状态」明确为否。
- verifier（legacy）是否纳入模型分配下拉 —— 纳入（与其它 Agent 一视同仁），但 `use_new_verifier=true` 时实际只用 planner-plan / planner-judge。
