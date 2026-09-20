# 配置参考

Fenix 配置分两级合并，大部分键支持 30 秒热更新，少数需重启 daemon 生效。本章给出全键参考、合并规则与已知的模板漂移点。

## 分级合并与热更新

配置分两级：用户级 `~/.fenix/config.yaml` 是所有项目共享的基础配置；项目级 `<项目根>/.fenix/config.yaml`（由 `fenix-init` 生成）覆盖用户级的同名键。合并是键级的 deep merge，项目级只覆盖自己声明的键，而不是整块替换用户级配置。

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

`poll_interval_minutes` 是**兜底**全量扫描的间隔（正常唤醒靠 2 秒的文件监听器），它的取值理由与「盲区」见[调度节拍](06-governance.md#调度节拍spec-何时被唤醒)——调小它主要影响恢复动作的副作用放大半径，而非扫描成本（实测中位 26.7 ms）。

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

### agents.（瞬断治理）：provider 网关瞬时故障的退避与熔断

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
| apikey | 是 | API Key，只注入子进程环境变量，不写入任何磁盘文件（`.fenix/config.yaml` 已 gitignore） |
| model | 否 | 该 Provider 的默认模型名，分配元素未带 model 时的兜底 |
| env | 否 | 附加环境变量 dict（如 `CLAUDE_CODE_MAX_CONTEXT_TOKENS`），随 Provider 注入 |
| billing | 否 | 计价配置：`enabled`（bool）+ `prices`（按 model 行级单价 `input/output/cache_read/cache_creation_per_million`），供成本展示 |

### agents.models

按 Agent 角色声明模型通道，键取十个角色：`implementer` / `fast-track` / `planner-plan` / `planner-judge` / `verifier` / `administrator` / `self-review` / `spec-review` / `dispute-judge` / `code-review`。未知角色键降级跳过并 ERROR 告警（新角色键需重启 daemon 使白名单生效）；未分配的角色走默认网关。

> **code-review（周期性代码审查，add-code-review-agent-and-quality-tab）**：`agents.models.code-review` 可为其独立分配模型；未配置时模型链依次回退 `agents.models.self-review` → `agents.models.administrator` → `admin.agent_model` → 默认网关（与 evolution 同型链）。

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

**候选链与 failover**：`provider` 支持字符串 / 字符串数组 / 对象数组（`{provider, model?}`）及混合。attempt 级派发角色（implementer / verifier / planner / fast-track）按链序选择首个未熔断、未处于切换冷却的候选；切换类错误（模型拒绝 / 5xx / 瞬断原地退避耗尽，见[瞬断治理](#agents瞬断治理provider-网关瞬时故障的退避与熔断)）失败后该 Provider 进入短冷却，同 run 下一次 attempt 自动前进到下一候选。administrator / self-review / dispute-judge / spec-review 只取链首选，不接 attempt 级 failover。

**模型名解析顺序**：链元素自带 model > 角色级 model > Provider 条目的 `model`；三者皆空的候选运行期跳过。模型名经 `--model` 直接发给网关，须填该网关支持的名字。`unrecognized_model` 报错先核对网关支持列表，多为网关瞬时故障，勿盲目改配置。

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
| spec_review_mode | `auto` | auto/never | 热更新 |

`gates.spec_review_mode`（方案评审门禁，add-spec-review-gate D2/D11）：
- `auto`（默认）：草稿晋升时全部 SPEC 进入方案评审；仅当 `mode == fast-track` 且能力目录数 ≤ 1 且交付物声明条目 ≤ 3 且非 `evo-` 前缀时跳过评审直通 `ready`。`evo-` 前缀为硬否决项（永不跳过）。
- `never`：跳过方案评审门禁，drafted 晋升直接进入 ready 并调度（整体逃生门，行为回到无评审时代）。

设置页「审批」页签可调（与草稿晋升模式相邻）。评审流程与人工恢复路径见[治理规则](06-governance.md#spec-方案评审门禁)。

### verify

| 键 | 默认值 | 范围 | 生效方式 |
|----|--------|------|---------|
| static_scope | `main` | main/worktree | 热更新（下一轮验证生效） |
| deps_mode | `prefer-offline` | prefer-offline/hardlink | 热更新（下一个 worktree 创建生效） |
| impl_code_review | `false` | bool | 热更新（下一轮实现收尾阶段生效） |
| impl_code_review_timeout_sec | `600` | 正整数 | 热更新（写入 run 级 ocr 配置，确定性生效） |
| impl_code_review_concurrency | `2` | 正整数 | 热更新（经提示词命令示例承载） |
| impl_code_review_effort | `low` | low/medium/high | 热更新（经提示词命令示例承载） |

`verify.*` 与 `.fenix/verify.yaml` 的分工需要特别说明。`verify.*` 是 config.yaml 的命名空间，存放机器本地的运行时开关，不入库，随 config.yaml 热更新；而 `.fenix/verify.yaml` 是项目验证契约（prepare/serve/ready），随仓库提交、手工编辑，Dashboard 不会改写这个文件。deps_mode 也可以在 verify.yaml 顶层按项目声明 `deps_mode:`，优先于 config。

`impl_code_review_timeout_sec` / `_concurrency` / `_effort`（add-impl-code-review-tuning）：
- **`impl_code_review_timeout_sec`**：ocr LLM 单请求超时（秒，含等待响应头），写入 run 级 `ocrcfg/.opencodereview/config.json` 的 `custom_providers.fenix-impl.timeout_sec`，**确定性生效**。不配置时 ocr 走其内置 300s 默认——实测 8 路并发 + 300s 单请求超时会撞穿首字节等待导致大面积文件级 timeout（`duration_to_headers_ms` 恰 300000）。缺省 600 秒。
- **`impl_code_review_concurrency`**：ocr 并发子任务上限（`--concurrency`），经提示词命令示例承载。实测 8 路并发同时打同一 provider 网关会把首字节延迟放大到撞穿超时线；降到 2 以吞吐换稳定。缺省 2。该参数无持久化配置键，实现者须照抄提示词中的命令串才生效（软约束）。
- **`impl_code_review_effort`**：ocr 审查力度预设（`--effort`），经提示词命令示例承载。`low` 更快更省但 recall 偏低（ocr precision 优先的刻意取舍）；`medium` 为 ocr 官方默认；`high` 深度审查。缺省 `low`，与 ocr 内置 `medium` 不同。实现者须照抄命令串才生效（软约束）。

三键的缺省取值（600/2/low）均比 ocr 官方默认值（300s/8/medium）更保守——宁慢勿废：超时更长避免大面积 timeout；并发更低避免网关排队；力度更轻以速度换覆盖，用户可随时上调。

### verify_engine（视觉校验）

web 场景视觉对比（`VisualDiffer.compare`）的稳健性配置（fix-visual-baseline-settle D6）。**Dashboard 设置页暂不纳入（YAML-only）**——两键经 config.yaml 的 `verify_engine` 段声明，后续按需补设置页 UI；未配置时取代码缺省，零迁移。

| 键 | 默认值 | 语义 |
|----|--------|------|
| verify_engine.visual_settle_timeout_ms | 3000 | 视觉截图前动画静置（settle）等待上限（毫秒）；0=禁用（行为与现状一致，逃生门）。截图前等待 `document.getAnimations()` 全部 finished，覆盖 CLS 检测不到的 opacity/transform 渐变动画（antd Modal ~300ms fade 污染基线事故链根因）；达上限仍有未完成动画（如 SSE 驱动的循环动画）按超时退化继续截图，不放大失败 |
| verify_engine.visual_retake_max | 2 | SSIM 低分（pass=False，含 warning 档）自动重拍次数上限；每次重拍前重新 settle，取最高 SSIM 分作最终结果；重拍耗尽仍低则维持原判定（不放宽阈值、不掩盖真回归）。首拍即通过零重拍零附加开销 |

```yaml
# 示例：放宽 settle 上限、关闭重拍
verify_engine:
  visual_settle_timeout_ms: 5000
  visual_retake_max: 0
```

契约的 serve/ready 形态按场景集 kind 自动反推（多形态验证，见 `05-verification.md`）：**纯 cli 场景集**跳过 serve/ready（不回退 `commands.start`，prepare 失败仍是唯一环境门）；**含 web/api 场景**则 serve 段（或 `commands.start` 兜底）必须有效，缺失时验收报错打回 plan；**混合场景集**照常起实例，cli 场景额外获得 `FENIX_VERIFY_BASE_URL` / `FENIX_VERIFY_PORT` 注入（框架值优先）。纯 CLI 交付的项目只需 `prepare`（构建/命令可用性），无需 serve 段。

deps_mode 仅对 nodejs 项目生效，供给入口是 package.json/node_modules，其他项目自动跳过、零副作用。C/C++/Java 等其他语言的依赖安装与构建经 verify.yaml 的 prepare 声明（语言无关，如 `mvn package`、`cmake --build`），依赖缓存多为用户级天然共享。

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

`admin.shutdown_drain_seconds` 双侧行为：计划性重启（supervisor 检测到 `.fenix/restart_request`）时，daemon 收到 SIGTERM 后先等，上限为本值（秒），等到期才走 terminate 收口；supervisor 的 SIGKILL 强杀等待 = 本值 + 120s。值为 0 时不排水、秒级退出，在飞任务标记 interrupted、重启后继续做（快速停机 + resume 兜底路径）；配置大值（如 1800）则每次计划性重启等待满排水窗口，1-2 小时级 implementer/planner 在飞场景会明显拖慢重启。设置页「系统」页签可编辑 enabled/interval_minutes/escalation_cooldown_minutes/merge_breaker_threshold/shutdown_drain_seconds 五项；`admin.agent_model` 为 legacy 兜底键（解析链：agents.models.self-review > agents.models.administrator > admin.agent_model > 默认网关，其中 self-review 为每日自省与框架自进化（evolution）共用的分配、未配置时继承 Administrator），设置页不提供编辑，避免与「模型分配」页签的 Administrator / Self-Review 条目双入口。`admin.self_review.*` 见「自省」页签。

### .fenix/supervisor_runtime.json 运行时自报

supervisor 每次启动时原子覆写 `.fenix/supervisor_runtime.json`，供 daemon 启动自检读取：

| 键 | 类型 | 用途 |
|----|------|------|
| `sigkill_wait` | int | SIGKILL 等待窗口（秒）= admin.shutdown_drain_seconds + 120s（drain=0 时默认 60s）；daemon 启动时比对本值 ≥ drain+120，不满足则打 WARNING 提示重启 supervisor |
| `started_at` | str | supervisor 本次启动时间戳（ISO8601 UTC）；daemon 据此判定文件是否残留自此前 supervisor 进程 |
| `pid` | int | supervisor 进程自身 pid |
| `script_hash` | str | `bin/fenixd_supervisor.py` 文件内容 sha256；与磁盘版本不一致说明 supervisor 持旧代码，需重启升级 |
| `project_root` | str | 解析出的绝对项目根（`--project-root` 参数 > `FENIX_PROJECT_ROOT` 环境变量 > `Path.cwd()`）；文件缺失或不一致均提示重启 supervisor |

文件读取失败（缺字段/非 JSON）按「旧版 supervisor 进程」处理——打 WARNING，不中断 daemon 主流程。

### stale_code_selfheal（代码陈旧自愈）

本项目是自我开发的，daemon 进程持有的是启动时刻的代码副本——代码落地后进程内逻辑不自动更新，「代码陈旧」是常态而非异常。本配置节控制陈旧状态下的空闲感知自动重启：

| 键 | 默认值 | 范围 | 生效方式 |
|----|--------|------|---------|
| enabled | `true` | bool | 热更新（下一检测周期生效） |
| idle_confirm_seconds | `120` | 正整数秒（建议 ≤ 86400，过大仅警告不拒绝） | 热更新（下一检测周期生效） |

```yaml
stale_code_selfheal:
  enabled: true        # 关闭后不再自动触发重启，但陈旧状态与告警仍产生
  idle_confirm_seconds: 120
```

语义：daemon 每 30s 检测点比对 `fenixd.py` + `core/**/*.py` 的 mtime 与进程启动 baseline，命中即置「陈旧」持续状态，除日志 WARNING 外写一条 `signal_type: stale_code`、`severity: warning` 的 escalation 告警（写入即自动标记已处理，不进人工告警横幅/待处理队列，仅运维记录页可见；状态边沿触发，单周期内不重复堆积）。当 陈旧为真 + `enabled: true` + 项目受 supervisor 托管 + 连续空闲达到 `idle_confirm_seconds`（空闲 = 无活跃 agent run 且无 admin 处置在途任务）时，daemon touch `.fenix/restart_request`，supervisor 执行优雅重启使新代码生效；重启后新 baseline 刷新，陈旧状态自然解除。任一活跃信号出现立即清零空闲计时。未受托管的项目（`unmanaged`）不自愈——`restart_request` 无人消费，写它只会制造死信，此时仅维持陈旧告警，等待经 Dashboard「安装托管」或 `/fenix-setup` 恢复托管。自动重启引入的新代码若无法启动，supervisor 会在连续 3 次启动后 60 秒内崩溃时熔断停止拉起并落 critical 告警，不会无限重启（见[保障机制](07-safeguards.md#代码陈旧自愈与启动失败熔断)）。

### self_evolution（框架自进化）

框架自身的自进化链路（`add-framework-self-evolution`）：跨项目扫描每日自省产物 `.fenix/todo.md`，对新增条目逐条独立回源复核 → 生成 SPEC 草稿 → 人工「同意」或开关打开后自动立项并开发至 push。本配置节控制该链路的全局行为：

| 键 | 默认值 | 范围 | 生效方式 |
|----|--------|------|---------|
| auto_accept | `false` | bool | 热更新（下一检查点生效） |
| max_items_per_run | `20` | 整数 1..200 | 热更新（下一检查点生效） |

```yaml
self_evolution:
  auto_accept: false      # 打开后自动接受全部判定值得立项的条目（decided_by=auto）
  max_items_per_run: 20   # 每轮分析条目上限，超出部分留待下轮（id 未入库自然再选中）
```

两键均为**全局（用户级）键**：Dashboard 配置写入 API 对项目级作用域提交 `self_evolution` 返回 400（引导到用户级作用域修改），项目级配置文件不会被写入该键；读取侧的有效值取用户级 + 项目级合并后配置。节、键缺失或值非法（`auto_accept` 非布尔、`max_items_per_run` 非 1..200 整数/布尔混入）时回退缺省值，不使 daemon 启动失败，30s 热更新路径不受该节中断。

语义：仅当 daemon 为自托管（`PROJECT_ROOT == FRAMEWORK_ROOT`）时启用自进化检查点（节拍复用 `admin.interval_minutes`，缺省 5 分钟）。检查点按 Dashboard registry 逐项目判定就绪（`.fenix/self_review_state.json` 的 `last_run_at` 晚于 `.fenix/evolution/state.json` 水位，且 `.fenix/todo.md` 非空），就绪即入队；无 `evo-` 分析 run 在途时立刻以队列中全部就绪项目启动一次分析 run。分析结论与草稿落在 gitignored 的 `.fenix/evolution/`（见[文件与数据地图](10-artifacts.md)）；接受后 SPEC 名统一使用 `evo-` 前缀并进入既有流水线（见[生命周期](03-lifecycle.md)）。`auto_accept` 为真时，分析落地完成后对本轮全部 `pending` 条目自动走接受路径（单条失败不影响其余），无需人工点击。

### admin.code_review（周期性代码审查）

设置页「质量」页签的开关（`add-code-review-agent-and-quality-tab`；2026-09-19 从项目页「代码审查」分面迁来——分面只保留结果展示与手动触发）：开启后与每日自省**同周期**触发 `code-review` agent，审查窗口内开发 SPEC 的**产品代码**质量（框架侧 manifest 已排除测试/manifest 外文档/构建产物），问题沉淀到独立台账 `.fenix/code-review/items.jsonl`，并在项目页「代码审查」分面以可复选表格呈现（支持一键生成修复 SPEC `fix-cr-<slug>`）。审查窗口与自省**同源**：`window_start` 取 `.fenix/self_review_state.json` 的 `last_run_at`（首跑/旧格式回退 `now - 24h`），即周期口径 = `admin.self_review.run_at` 时点，二者永远同窗口、不引入漂移。审查路径为两步：先 `ocr scan`（**全文件扫描**，非 diff-based 的 `ocr review`）批量扫描，再由 agent 逐文件落 `out-<run_id>.jsonl`；产物缺失或零有效行时整轮判失败（`repo-code-review-gate`）。

| 键 | 默认值 | 范围 | 生效方式 |
|----|--------|------|---------|
| enabled | `false` | bool | 热更新（下一检查点生效） |
| max_files | `500` | 正整数 | 热更新（下一检查点生效） |

```yaml
admin:
  code_review:
    enabled: false      # 是否启用周期性代码审查（缺省 false）
    max_files: 500      # 审查 manifest 上限（正整数）：大仓全量审查超限截断，避免耗时过长/烧钱
```

- `enabled` 只管**周期调度**（与 `admin.self_review.enabled` 同语义）：关闭时到达自省时点不派发 code-review run、不写任何产物；项目页「代码审查」分面的**手动触发**按钮（全仓库审查 / 当期提交审查）**不受此开关约束**——用户显式点击即执行（写 `.fenix/code_review_request.json` 文件信号，daemon 未受 supervisor 托管时拒绝并以明确文案返回）。
- 手动触发无运行中审查时返回受理；已有审查在跑时返回 409「已有审查在进行中」。
- 模型链：`agents.models.code-review` → `agents.models.self-review` → `agents.models.administrator` → `admin.agent_model` → 默认网关。
- token 归账到 `.fenix/cost/code_review_tokens.json`（与每日自省同结构，不写 STATE）。

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

- **id 必填且唯一**：手工编辑 config.yaml 新增 hook 时必须自带唯一 id，缺失 id 的条目匹配后不会执行，也不写审计、不告警（完全无痕）。
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

**结论**：不要凭模板注释理解缺省值。判断某个键的实际生效值，应查看项目 `.fenix/config.yaml` 是否配置了该键：配置了以配置值为准，未配置则按代码缺省。

## Dashboard 设置页与配置键映射

| 设置页面板 | 对应配置键 |
|-----------|-----------|
| 配置管理 | llm.providers / agents.models / gates.approve_mode / gates.promote_mode / gates.spec_review_mode |
| Token 预算面板 | agents.token_budget_millions |
| 验证 | verify.static_scope / verify.deps_mode（存于 config.yaml；`.fenix/verify.yaml` 契约手工编辑，不经设置页改写） |
| 质量 | verify.impl_code_review（实现阶段收尾代码质量审查开关，自「验证」页迁出；页签顶部的 ocr 环境探测/一键安装不写配置键）；verify.impl_code_review_timeout_sec / verify.impl_code_review_concurrency / verify.impl_code_review_effort（收尾审查三运行参数：超时秒/并发/力度，缺省 600/2/low）；admin.code_review.enabled（周期性代码审查开关，2026-09-19 自项目页「代码审查」分面迁来） |
| 提示词管理 | agents/ 通用层 + .fenix/agents/ 项目级 |
| 系统 | admin.enabled / admin.interval_minutes / admin.escalation_cooldown_minutes / admin.merge_breaker_threshold / admin.shutdown_drain_seconds |
| 系统·瞬断治理 | agents.transient_backoff_schedule / agents.transient_redispatch_delay_seconds / agents.transient_break_threshold / agents.transient_break_window_seconds / agents.transient_break_cooldown_seconds |
| 自进化 | stale_code_selfheal.enabled / stale_code_selfheal.idle_confirm_seconds（第一张卡片「代码陈旧自愈」）；self_evolution.auto_accept / self_evolution.max_items_per_run（第二张卡片「建议改进项」，全局用户级键） |
| Hook | hooks.global / hooks.specs.<spec 名>（两级订阅，见 [hooks](#hooks)） |

## 相关文档

- [调度与治理规则](06-governance.md) — 各预算键的运行时行为
- [Dashboard 使用指南](08-dashboard.md) — 设置页操作
- [FAQ 与故障排查](11-faq.md) — 配置改不动/不生效排查
