# 配置参考

Fenix 配置分两级合并，大部分键支持 30 秒热更新，少数需重启 daemon 生效。本章给出全键参考、合并规则与已知的模板漂移点。

## 分级合并与热更新

配置分两级：用户级 `~/.fenix/config.yaml` 是所有项目共享的基础配置；项目级 `<项目根>/.fenix/config.yaml`（由 `fenix-init` 生成）覆盖用户级的同名键。合并是键级的 deep merge——项目级只覆盖自己声明的键，而不是整块替换用户级配置。

热更新方面，大部分调度/预算键约 30 秒后自动生效（daemon 热加载配置）；需重启生效的键在下表中逐键标注。

## config.yaml 全键分组表

### project

| 键 | 默认值 | 范围 | 生效方式 |
|----|--------|------|---------|
| name | — | 字符串 | 重启 |
| type | — | web/cli/library/api | 重启 |
| root | `.` | 项目根相对 .fenix/ | 重启 |
| description | 空 | 文本 | 热更新 |

### schedule

| 键 | 默认值 | 范围 | 生效方式 |
|----|--------|------|---------|
| poll_interval_minutes | 30 | 分钟 | 热更新 |
| daily_report_time | `"09:00"` | HH:MM | 热更新 |

### agents

| 键 | 默认值 | 范围 | 生效方式 |
|----|--------|------|---------|
| max_concurrent | 2 | ≥1 | 热更新 |
| max_retries | 3 | ≥0 | 热更新 |
| impl_run_budget | **代码缺省 6**（模板 4） | 1-10 | 热更新 |
| token_budget_millions | **代码缺省 50**（模板 50） | 0-1000（0=关闭） | 热更新 |
| max_turns | 300 | ≥1 | 重启 |
| daily_run_limit | **代码缺省 50**（模板 300） | ≥0（0=无限） | 热更新 |
| run_timeout_seconds | 3600 | ≥1 | 热更新 |
| use_new_verifier | true | bool | 重启 |

### agents.timeout_supervision

| 键 | 默认值 | 生效方式 |
|----|--------|---------|
| enabled | true | 热更新 |
| extension_seconds | 1800 | 热更新 |
| max_extensions | 2 | 热更新 |
| absolute_max_seconds | 7200 | 热更新 |
| judge_window | 600 | 热更新 |

### worktree

| 键 | 默认值 | 生效方式 |
|----|--------|---------|
| base_dir | `.claude/worktrees` | 重启 |
| implement_branch_prefix | `fenix` | 重启 |
| verify_branch_prefix | `fenix/verify` | 重启 |

### gates

| 键 | 默认值 | 范围 | 生效方式 |
|----|--------|------|---------|
| require_push_approval | true | bool | 热更新 |
| approve_mode | `manual` | manual/auto | 热更新 |

### verify

| 键 | 默认值 | 范围 | 生效方式 |
|----|--------|------|---------|
| static_scope | `main` | main/worktree | 热更新（下一轮验证生效） |
| deps_mode | `prefer-offline` | prefer-offline/hardlink | 热更新（下一个 worktree 创建生效） |

`verify.*` 与 `.fenix/verify.yaml` 的分工需要特别说明。`verify.*` 是 config.yaml 的命名空间，存放机器本地的运行时开关——不入库，随 config.yaml 热更新；而 `.fenix/verify.yaml` 是项目验证契约（prepare/serve/ready），随仓库提交、手工编辑，Dashboard 不会改写这个文件。deps_mode 也可以在 verify.yaml 顶层按项目声明 `deps_mode:`，优先于 config。

契约的 serve/ready 形态按场景集 kind 自动反推（多形态验证，见 `05-verification.md`）：**纯 cli 场景集**跳过 serve/ready（不回退 `commands.start`，prepare 失败仍是唯一环境门）；**含 web/api 场景**则 serve 段（或 `commands.start` 兜底）必须有效，缺失时验收报错打回 plan；**混合场景集**照常起实例，cli 场景额外获得 `FENIX_VERIFY_BASE_URL` / `FENIX_VERIFY_PORT` 注入（框架值优先）。纯 CLI 交付的项目只需 `prepare`（构建/命令可用性），无需 serve 段。

deps_mode 仅对 nodejs 项目生效——供给入口是 package.json/node_modules，其他项目自动跳过、零副作用。C/C++/Java 等其他语言的依赖安装与构建经 verify.yaml 的 prepare 声明（语言无关，如 `mvn package`、`cmake --build`），依赖缓存多为用户级天然共享。

### pm.push

| 键 | 默认值 | 生效方式 |
|----|--------|---------|
| retry_backoff_seconds | `[300, 900]` | 热更新 |
| max_retries | 3 | 热更新 |

### admin

| 键 | 默认值 | 生效方式 |
|----|--------|---------|
| enabled | true | 热更新 |
| interval_minutes | 5 | 热更新 |
| escalation_cooldown_minutes | 15 | 热更新 |
| agent_model | 复用默认模型 | 热更新 |

### pm.dispatch.aging / pm.family

| 键 | 默认值 | 生效方式 |
|----|--------|---------|
| dispatch.aging.enabled | false | 热更新 |
| dispatch.aging.initial_wait_minutes | 30 | 热更新 |
| dispatch.aging.step_down_minutes | 15 | 热更新 |
| dispatch.aging.floor_levels | 4 | 热更新 |
| family.max_depth | 3 | 热更新 |
| family.max_width | 2 | 热更新 |

### 派生键

| 键 | 默认值 | 说明 |
|----|--------|------|
| merge_breaker_threshold | 2（复用 `agents.merge_breaker_threshold`） | merge 熔断阈值 |

### commands / logging / dashboard

| 键 | 默认值 | 生效方式 |
|----|--------|---------|
| commands.test/build/start | `echo ...` | 重启 |
| logging.dir | `.fenix/logs` | 重启 |
| logging.level | INFO | 重启 |
| dashboard.port | 8787 | 重启 |

## 模板值与代码缺省不一致

`.fenix/config.template.yaml`（随仓库入库的配置模板）与代码缺省存在若干差异，**实际生效值以项目 config.yaml 为准**（未配置该键时以代码缺省为准）。易混淆点集中列出：

| 键 | .fenix/config.template.yaml 值 | 代码缺省 | 差异说明 |
|----|------------------------|---------|---------|
| agents.impl_run_budget | 4 | **6** | 模板注释也称「缺省 4」，实际代码缺省 6（`DEFAULT_IMPL_RUN_BUDGET = 6`） |
| agents.daily_run_limit | 300 | **50** | 模板默认 300，代码缺省 50（`agents.daily_run_limit` 未配置时） |
| agents.token_budget_millions | 50 | **50** | 一致 |
| 顶层 timeout_supervision | enabled: false | 以 `agents.timeout_supervision` 为准 | 顶层键仅是回退开关，`agents.timeout_supervision` 是 canonical 位置 |

**结论**：不要凭模板注释理解缺省值。判断某个键的实际生效值，应查看项目 `.fenix/config.yaml` 是否配置了该键——配置了以配置值为准，未配置则按代码缺省。

## Dashboard 设置页与配置键映射

| 设置页面板 | 对应配置键 |
|-----------|-----------|
| 配置管理 | llm.providers / agents.models / gates.approve_mode |
| Token 预算面板 | agents.token_budget_millions |
| 验证 | verify.static_scope / verify.deps_mode（存于 config.yaml；`.fenix/verify.yaml` 契约手工编辑，不经设置页改写） |
| 提示词管理 | agents/ 通用层 + .fenix/agents/ 项目级 |

## 相关文档

- [调度与治理规则](06-governance.md) — 各预算键的运行时行为
- [Dashboard 使用指南](07-dashboard.md) — 设置页操作
- [FAQ 与故障排查](10-faq.md) — 配置改不动/不生效排查
