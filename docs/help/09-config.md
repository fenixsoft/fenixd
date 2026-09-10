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
| max_turns | 400 | ≥1 | 重启 |
| daily_run_limit | **代码缺省 50**（模板 300） | ≥0（0=无限） | 热更新 |
| run_timeout_seconds | 9000 | ≥1 | 热更新 |
| use_new_verifier | true | bool | 重启 |

### agents.（瞬断治理）——provider 网关瞬时故障的退避与熔断

| 键 | 默认值 | 范围 | 生效方式 |
|----|--------|------|---------|
| transient_backoff_schedule | `30,60,120` | 逗号分隔正整数秒序列；空串关闭原地退避 | 热更新 |
| transient_redispatch_delay_seconds | 600 | ≥0 | 热更新 |
| transient_break_threshold | 3 | ≥0（0=关闭熔断） | 热更新 |
| transient_break_window_seconds | 600 | ≥0 | 热更新 |
| transient_break_cooldown_seconds | 600 | ≥0 | 热更新 |

`agents.transient_*` 五键治理 provider 网关瞬时故障（model 拒绝 / 5xx / 断连），语义与
`fix-provider-transient-backoff` SPEC 的 design D6 一致；非法值自动回退缺省。设置页
「系统」页签「瞬断治理」分组可编辑五键。

- `transient_backoff_schedule`：瞬断首败后同 provider 原地退避的秒序列，长度=单
  attempt 内原地重试上限。缺省 `30,60,120` 表示首败等 30s、再败等 60s、第三次等 120s
  后仍失败才走换链逻辑；留空 `""` 关闭原地退避（回退到既有换链 + switch 冷却行为）。
  原地重试不递增 attempt 计数、不触发 switch 冷却、不改链指针。
- `transient_redispatch_delay_seconds`：dispatch 层遇到 `[provider-transient]` 终态
  失败后延迟重派的等待秒数（仿秒挂冷却定时器模式），等待期内不写 retries exhausted、
  不消耗死亡豁免预算。缺省 600（历史死亡 run 重派 16 分钟后成功）。
- `transient_break_threshold` / `transient_break_window_seconds` / 
  `transient_break_cooldown_seconds`：全局同错误指纹熔断。窗口（window）内同一错误
  指纹（错误文本归一化：剥离 model 名/时间戳）出现次数达阈值（threshold）→ 冻结全部
  新 run 派发冷却（cooldown）秒并发 major 告警（15 分钟节流）；冷却到期自动恢复且
  窗口计数清零。阈值 0 关闭熔断。熔断状态进程内存、daemon 重启清零。

### agents.timeout_supervision

| 键 | 默认值 | 生效方式 |
|----|--------|---------|
| enabled | true | 热更新 |
| extension_seconds | 1800 | 热更新 |
| max_extensions | 2 | 热更新 |
| absolute_max_seconds | 7200 | 热更新 |
| judge_window | 600 | 热更新 |

### llm

Agent 可用的模型通道（Provider）注册表。未配置 = 空注册表，所有角色走默认网关（用户 `~/.claude/settings.json` 决定的通道）。

| 键 | 默认值 | 范围 | 生效方式 |
|----|--------|------|---------|
| llm.providers | `[]` | 列表，条目 schema 见下 | 热更新 |

每个 Provider 条目：

| 字段 | 必填 | 说明 |
|------|------|------|
| name | 是 | 唯一标识，被 `agents.models` 引用；同时用作隔离目录名（`.fenix/agent-config/<name>/`） |
| baseurl | 是 | Anthropic 兼容网关地址（注入 `ANTHROPIC_BASE_URL`） |
| apikey | 是 | API Key——只注入子进程环境变量，不写入任何磁盘文件（`.fenix/config.yaml` 已 gitignore） |
| model | 否 | 该 Provider 的默认模型名，分配元素未带 model 时的兜底 |
| env | 否 | 附加环境变量 dict（如 `CLAUDE_CODE_MAX_CONTEXT_TOKENS`），随 Provider 注入 |
| billing | 否 | 计价配置：`enabled`（bool）+ `prices`（按 model 行级单价 `input/output/cache_read/cache_creation_per_million`），供成本展示 |

### agents.models

按 Agent 角色声明模型通道，键取七角色：`implementer` / `fast-track` / `planner-plan` / `planner-judge` / `verifier` / `administrator` / `self-review`。未知角色键降级跳过并 ERROR 告警（新角色键需重启 daemon 使白名单生效）；未分配的角色走默认网关。

```yaml
agents:
  models:
    implementer:                    # 单 Provider：最简形态
      provider: "volc-engine"
      model: "deepseek-v4-flash"    # 角色级默认模型
    planner-plan:
      provider:                     # 候选链：按序 failover
        - "aliyun"                  #   字符串元素
        - provider: "bigmodel.cn"   #   对象元素，可带元素级 model
          model: "glm-5"
      model: "deepseek-v4-pro"      # 链元素未带 model 时的角色级兜底
```

**候选链与 failover**：`provider` 支持字符串 / 字符串数组 / 对象数组（`{provider, model?}`）及混合。attempt 级派发角色（implementer / verifier / planner / fast-track）按链序选择首个未熔断、未处于切换冷却的候选；切换类错误（模型拒绝 / 5xx / 瞬断原地退避耗尽，见[瞬断治理](#agents瞬断治理provider-网关瞬时故障的退避与熔断)）失败后该 Provider 进入短冷却，同 run 下一次 attempt 自动前进到下一候选。administrator / self-review / dispute-judge 只取链首选，不接 attempt 级 failover。

**模型名解析顺序**：链元素自带 model > 角色级 model > Provider 条目的 `model`；三者皆空的候选运行期跳过。模型名经 `--model` 直接发给网关，须填该网关支持的名字——`unrecognized_model` 报错先核对网关支持列表，多为网关瞬时故障，勿盲目改配置。

**生效链路**：配置了分配的角色，其 baseurl/apikey/model 经进程环境注入 + `CLAUDE_CONFIG_DIR` 隔离目录保证绝对生效，机制与共享/隔离边界详见[核心概念 · LLM Provider 隔离](02-concepts.md#llm-provider-隔离)。

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
| promote_mode | `auto` | auto/manual | 热更新 |

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

| 键 | 默认值 | 范围 | 生效方式 |
|----|--------|------|---------|
| enabled | true | bool | 热更新 |
| interval_minutes | 5 | 正数（分钟） | 热更新 |
| escalation_cooldown_minutes | 60 | 非负数（分钟） | 热更新 |
| merge_breaker_threshold | 2（复用 `agents.merge_breaker_threshold`） | 正整数 | 热更新 |
| agent_model | 复用默认模型 | 模型名 | 热更新 |
| shutdown_drain_seconds | **模板 0**（代码缺省 1800） | 非负整数（0=快速停机） | 重启 |

`admin.shutdown_drain_seconds` 双侧行为：计划性重启（supervisor 检测到 `.fenix/restart_request`）时，daemon 收到 SIGTERM 后先等——上限为本值（秒），等到期才走 terminate 收口；supervisor 的 SIGKILL 强杀等待 = 本值 + 120s。值为 0 时不排水、秒级退出——在飞任务标记 interrupted、重启后继续做（快速停机 + resume 兜底路径）；配置大值（如 1800）则每次计划性重启等待满排水窗口，1-2 小时级 implementer/planner 在飞场景会明显拖慢重启。设置页「系统」页签可编辑 enabled/interval_minutes/escalation_cooldown_minutes/merge_breaker_threshold/shutdown_drain_seconds 五项；`admin.agent_model` 为 legacy 兜底键（解析链：agents.models.self-review > agents.models.administrator > admin.agent_model > 默认网关，其中 self-review 为每日自省专属分配、未配置时继承 Administrator），设置页不提供编辑，避免与「模型分配」页签的 Administrator / Self-Review 条目双入口。`admin.self_review.*` 见「自省」页签。

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
| stuck_threshold_minutes | 由 `agents.run_timeout_seconds` 单源派生 | stuck 判定阈值（run_timeout + 600s 宽限）；旧 `admin.stuck_threshold_minutes` 键已弃用 |

### commands / logging / dashboard

| 键 | 默认值 | 生效方式 |
|----|--------|---------|
| commands.test/build/start | `echo ...` | 重启 |
| logging.dir | `.fenix/logs` | 重启 |
| logging.level | INFO | 重启 |
| dashboard.port | 8787 | 重启 |

### hooks

SPEC 状态变化事件 hook 的订阅配置。SPEC 每次状态转换都会发布一条事件（事件类型 = 目标状态，取十状态枚举值：drafted/ready/implementing/implemented/testing/verified/bug-found/blocked/done/pushed），你可以订阅这些事件，在 SPEC 进入指定状态时自动执行动作。

订阅分两级：`hooks.global`（对所有 SPEC 生效，设置页「Hook」面板配置）与 `hooks.specs.<spec 名>`（仅对该 SPEC 生效，SPEC 详情页「Hook」页签配置）。一次状态变化可同时命中多条 hook，各自独立并发执行、互不阻塞。无 `hooks` 段 = 零行为。

```yaml
hooks:
  global:                        # 对所有 SPEC 生效
    - id: h-3f9a2b               # 必填且须唯一（见下方注意事项）
      enabled: true
      events: [done]             # 订阅的事件 = 目标状态
      action: restart-daemon     # SPEC 完成 → 优雅重启 daemon 让新代码生效
    - id: h-7c1d9e
      enabled: true
      events: [blocked]
      action: shell              # 任意 SPEC 阻塞 → 自定义命令通知
      command: 'curl -s -X POST "https://notify.example.com/$FENIX_HOOK_SPEC" -d "$FENIX_HOOK_ERROR"'
      timeout_seconds: 30
  specs:                         # 仅对指定 SPEC 生效
    add-xxx:
      - id: h-9b2e4f
        enabled: true
        events: [verified, done]
        action: webhook
        url: https://example.com/hook
```

#### hook 条目键

| 键 | 默认值 | 约束 | 说明 |
|----|--------|------|------|
| id | — | 必填，全段唯一 | Dashboard 保存时自动生成；手工编辑必须自带（缺失的条目不会执行，见注意事项） |
| enabled | true | bool | false 时跳过执行，审计记 skipped、不告警 |
| events | — | 必填，非空列表 | 订阅的事件类型，取值须在十状态枚举内 |
| action | — | 必填，七枚举 | restart-daemon / restart-dashboard / commit / push / commit-push / webhook / shell |
| url | — | webhook 必填 | 通知地址 |
| command | — | shell 必填 | 以 `bash -c` 在项目根执行的命令 |
| message | `[fenix] hook: {spec} {event}` | commit/commit-push 可选 | 提交信息模板，变量 `{spec}`/`{event}`，未知变量原样保留 |
| timeout_seconds | webhook 10 / shell 60 | 正数 | webhook 请求超时 / shell 执行超时（超时强制终止） |
| target | `fenix-dashboard` | restart-dashboard 可选 | 要重启的 dashboard tmux 会话名 |

#### 七种动作

| 动作 | 行为 |
|------|------|
| restart-daemon | 写 `.fenix/restart_request`，由 supervisor 按既有协议优雅重启 daemon（合并新代码后让其生效的常规手段） |
| restart-dashboard | `tmux respawn-window -k` 重启 dashboard 会话（重启命令固定含 `env -u CLAUDE_PID`、保持端口与工作目录），以端口恢复 HTTP 可服务为成功判据 |
| commit | 项目根 `git add -A` 后按模板提交；工作区无变更记 noop 成功、不告警 |
| push | `git push` 推送当前分支到其 upstream |
| commit-push | 先 commit 后 push；commit 无变更仍 push；push 失败不回滚已产生的本地提交 |
| webhook | 向 `url` POST 一次 JSON（字段：event/spec/from_status/to_status/ts/error/frozen/hook_id/action/project），2xx 成功 |
| shell | `bash -c <command>`，工作目录为项目根，注入事件环境变量（下表），退出码 0 成功 |

shell 动作注入的环境变量：

| 变量 | 内容 |
|------|------|
| FENIX_HOOK_EVENT | 触发的事件类型（= 目标状态） |
| FENIX_HOOK_SPEC | SPEC 名 |
| FENIX_HOOK_FROM_STATUS | 前一状态（可能为空） |
| FENIX_HOOK_TO_STATUS | 目标状态（与 EVENT 相同） |
| FENIX_HOOK_ERROR | 状态携带的错误信息（无则为空） |
| FENIX_HOOK_PROJECT_ROOT | 项目根绝对路径 |

#### 执行语义与审计

hook 分发与动作执行在 daemon 后台线程进行，不阻塞状态机写入路径。动作失败（git 失败、webhook 不可达、shell 非零退出/超时等）时：写 status=failure 审计 + 运维记录页产生一条 `hook_failure` 站内告警（severity major），**不自动重试**、不做去重降噪。每次触发（含 skipped）都追加写入 `.fenix/hook_audit.jsonl`，字段与查询见[文件与数据地图](10-artifacts.md)；SPEC 详情页「Hook」页签与设置页「Hook」面板均可看「最近执行」。

经 Dashboard 保存时校验配置（events 非空且合法、action 合法、webhook 必填 url、shell 必填 command），违规直接拒绝写入；手工编辑则在触发时校验，非法记 failure 审计（不告警）。

**注意事项**：

- **id 必填且唯一**：手工编辑 config.yaml 新增 hook 时必须自带唯一 id——缺失 id 的条目匹配后不会执行，也不写审计、不告警（完全无痕）。
- **不要在 hook 动作中修改 SPEC 状态**（如 shell 里直写 STATE.md）：状态变化会再次发布事件，形成自激循环；框架不对 hook 做熔断，循环只能靠审计与告警事后暴露。
- **push / commit-push 是显式授权的自动推送**：Fenix 默认由 `/fenix-approve` 人工门禁把守推送，配置 push 类动作即表示你接受订阅范围内的自动推送，属有意为之的例外。
- 配置修改 ≤30 秒热更新生效，无需重启。

## 模板值与代码缺省不一致

`.fenix/config.template.yaml`（随仓库入库的配置模板）与代码缺省存在若干差异，**实际生效值以项目 config.yaml 为准**（未配置该键时以代码缺省为准）。易混淆点集中列出：

| 键 | .fenix/config.template.yaml 值 | 代码缺省 | 差异说明 |
|----|------------------------|---------|---------|
| agents.impl_run_budget | 4 | **6** | 模板注释也称「缺省 4」，实际代码缺省 6（`DEFAULT_IMPL_RUN_BUDGET = 6`） |
| agents.daily_run_limit | 300 | **50** | 模板默认 300，代码缺省 50（`agents.daily_run_limit` 未配置时） |
| agents.token_budget_millions | 50 | **50** | 一致 |
| admin.shutdown_drain_seconds | 0 | **1800** | 模板（fenix-init 新项目）开箱即得快速停机；存量项目未配置该键时仍按代码缺省 1800 排水 |
| 顶层 timeout_supervision | enabled: false | 以 `agents.timeout_supervision` 为准 | 顶层键仅是回退开关，`agents.timeout_supervision` 是 canonical 位置 |

**结论**：不要凭模板注释理解缺省值。判断某个键的实际生效值，应查看项目 `.fenix/config.yaml` 是否配置了该键——配置了以配置值为准，未配置则按代码缺省。

## Dashboard 设置页与配置键映射

| 设置页面板 | 对应配置键 |
|-----------|-----------|
| 配置管理 | llm.providers / agents.models / gates.approve_mode / gates.promote_mode |
| Token 预算面板 | agents.token_budget_millions |
| 验证 | verify.static_scope / verify.deps_mode（存于 config.yaml；`.fenix/verify.yaml` 契约手工编辑，不经设置页改写） |
| 提示词管理 | agents/ 通用层 + .fenix/agents/ 项目级 |
| 系统 | admin.enabled / admin.interval_minutes / admin.escalation_cooldown_minutes / admin.merge_breaker_threshold / admin.shutdown_drain_seconds |
| 系统·瞬断治理 | agents.transient_backoff_schedule / agents.transient_redispatch_delay_seconds / agents.transient_break_threshold / agents.transient_break_window_seconds / agents.transient_break_cooldown_seconds |
| Hook | hooks.global / hooks.specs.<spec 名>（两级订阅，见 [hooks](#hooks)） |

## 相关文档

- [调度与治理规则](06-governance.md) — 各预算键的运行时行为
- [Dashboard 使用指南](08-dashboard.md) — 设置页操作
- [FAQ 与故障排查](11-faq.md) — 配置改不动/不生效排查
