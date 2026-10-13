# fenixd 多 Harness 支持架构设计（multi-harness adapter）

日期：2026-10-13
状态：设计已获用户批准（方案一：Adapter + 事件投影 + fenix-dsh Bundle）
定位：本文件是后续 4 个 SPEC 立项的母设计文档，各 SPEC 引用本文对应章节。

---

## 1. 背景与目标

fenixd 当前只支持 Claude Code 一种 code agent harness：所有 LLM 能力借道 `claude` CLI（ADR-055）。目标是以 DeepSeek Harness（`dsh`）为第一个新 harness 引入可插拔支持，终态 **dsh 为主 harness**，claude 退为平级 adapter；codex、pi 等日后按同一机制接入。

### 1.1 已锁定的四个决策（用户定调）

| 决策点 | 结论 |
|---|---|
| 选择粒度 | **全局切换**：实例级配置一个 harness（`agent.harness`），所有车道统一；车道级混用与运行时回退不在本期范围 |
| 能力契约 | **能力等价映射，只做 dsh**：Claude 侧依赖的机制（hooks、Task 工具族、审批策略等）在 dsh 侧用其插件体系（Cordis Bundle）原生映射；codex/pi 接入时再各自处理 |
| 终态定位 | **dsh 为主 harness**：验收标准为完整开发循环在 dsh 上跑通一条真实 SPEC；默认值是否由 claude 翻转为 dsh，验收后由用户决策 |
| 落地形式 | **拆 4 个 SPEC 立项**，daemon 自举实施；本文档为共同输入 |

### 1.2 明确不做（YAGNI）

- 车道级/角色级 harness 路由、跨 harness 故障回退（第二阶段候选）
- codex / pi 的 adapter 与能力映射（仅要求未来可按同机制接入，抽象层不为其预留特判）
- run jsonl schema 中性化重构（保留 claude stream-json 形状为 canon；dsh 跑通后可另立还债 SPEC）
- dashboard 自由会话（`session_manager`）与 `CLAUDE_PID` watchdog 的 harness 化——人机交互形态非派发车道，本期保持 claude 专用（ADR 记录豁免）
- 人侧操作台（`install.sh` 软链的 fenix-* skills、`.claude/agents`）——operator 使用面，与派发 agent 无关

## 2. 外部调研结论（2026-10-13）

### 2.1 三个候选 harness 的接口形态

| | DeepSeek Harness（dsh） | Codex CLI | Pi |
|---|---|---|---|
| 非交互形态 | `dsh headless "任务"` / stdin 喂任务；`--json` 出 JSONL 事件流 | `codex exec "任务"` + `--json`（JSONL） | `pi --print` / `--mode json`（JSONL） |
| 长驻控制 | Python SDK / web host | Codex App Server（JSON-RPC 2.0） | `--mode rpc`（stdin/stdout JSONL） |
| 会话 | 追记式事件流，`--session-id` 采纳/续跑，fail-loud | session + `exec resume` | `--session-id` / `--session-dir` / `--continue` |
| 扩展模型 | 一切皆插件（Cordis）；Profile/Bundle/cordis.patch.yml | config.toml + AGENTS.md + MCP | extensions/skills/packages（npm/git） |
| 成熟度 | v0.2 rc（2026-08-13 首发 v0.1 preview，官方警告破坏性变更） | 成熟 | 成熟 |

### 2.2 dsh headless 精确契约（fenixd 将 spawn 的接口，0.2.x 实测文档）

- `dsh headless "<task>"`：一次性运行，终答打印到 stdout 后退出；**exit 0=完成，1=中止/出错**；不开端口、不留后台。
- `--json`：stdout 变为 NDJSON 事件流——`session` 开头（携带 session id）→ `status/text/thinking/tool_call/tool_result` → `final` 结尾；turn 外失败写 `error` 事件且无 `final`；turn 内失败仍有 `final`（常为空）+ exit 1。**失败信号 = exit code 1 + `turn_end` reason**。
- `--session-id <id>`：采纳已持久化 Session；未知 id **fail-loud**（先于任务执行）；被其他 owner 持有的 id **refuse**；子代理/分叉 session 拒绝采纳；cwd 不匹配拒绝。
- 截断语义：字符串字段 8 KiB 上限、单行（含换行）32 KiB 上限，超限带 `truncated` 标记，最深 64 层。
- 任务输入：positional 参数原样使用（不读 stdin），或省略/`-` 时读 stdin（管道任务 verbatim）。
- cwd 即工作区（经 fs provider 解析）；新 Session 记录 cwd。
- 版本钉扎：Bundle 与 adapter 双侧钉 dsh release。

### 2.3 本机环境基线（2026-10-13 已由人工装好，SPEC 不重复做）

- `dsh` 0.2.0-rc.2（稳定通道，`/usr/bin/dsh`，npm 全局 `@deepseek-ai/dsh`；原生依赖 install 脚本已按 allowlist 放行：`@deepseek-ai/dsh-subprocess-local,koffi,node-pty,@google/genai,protobufjs`）
- `dsh-tui` 0.2.19（Claude Code 风格 TUI 客户端，连接 `dsh web` host，`DSH_URL` 默认 `http://127.0.0.1:3080`；SSH 人工验证面）
- `pnpm` 12.11.2（dsh 插件管理器的依赖）
- node v24.19.0；`dsh web` 冒烟通过（token 门 401 正常）；已停止，无残留进程
- **已否决路线**：`@dsh-cc/*`（CC-mode fork 发行版，自建构建仓库，与官方 core API 不兼容，`settings.register`/`tools.reserve` 均不存在于官方 0.2.x）——后续 SPEC 不要再尝试

## 3. 现状耦合地图（勘察结论）

**地基层（harness 无关，整体保留）**：STATE.md/状态机、run jsonl 文件本身、`.fenix-run-result.json` 产物硬门、`.fenix/verify-progress`、worktree（纯 git，`worktree_manager/lifecycle.py:214+`）、provider 链/failover/熔断配置模型（`config.py:1276-1336`）、验证引擎（零 LLM）、dashboard 文件签名管线（`watcher.py`）、在飞判定（自有 run jsonl + 进程表，`liveness.py`）。

**耦合点（本次重构对象）**：

| # | 耦合点 | 位置 |
|---|---|---|
| C1 | CLI 启动命令构造（主通道） | `core/agent_runner/runner.py:5607`（`_run_claude`，:5719-5746 参数构造；有意单体注记 :5659-5664 本次解除） |
| C2 | 7 个表亲 spawn 点（各自复制 CLI 形态） | 监督 judge `liveness.py:1053`；告警叙事 `adjudication_narrative.py:322-373`（已有 `set_channel` 注入点 ADR-242/243）；蒸馏 `knowledge.py:1241`；回填 `knowledge_backfill.py:883`；架构图 `dashboard/routes/architecture_routes.py:659`；项目简介 `dashboard/routes/project_routes.py:597`；自由会话 `dashboard/session_manager.py:96-107`（豁免，见 1.2） |
| C3 | stream-json 事件 schema 消费（8+ 读侧模块） | `liveness.py:133`（`RUN_TERMINAL_EVENT_TYPES`）、`run_task_track.py` 全模块、`session.py:52-140`（session_id/usage）、`runner.py:5877-5930`（读循环）、`dashboard/data/runs.py` |
| C4 | Task 工具族成对契约（写侧 prompt ↔ 读侧解析） | prompt 契约段 `prompt_builder.py:1562+`；解析 `run_task_track.py:432/567/659`；opt-in env `runner.py:5694-5703`；批内并行 ADR-198 |
| C5 | Claude 配置机制（隔离 settings/hooks/symlink） | `_build_isolated_settings` runner.py:2000-2059、`_ensure_agent_config_dir` :2067-2143、hooks 注入 :5740-5742、skills/plugins symlink :2110-2119、superpowers 缺省 :2028-2032 |
| C6 | stderr 文本归因 | `provider_circuit.py:228/388/437/490/519/558` |
| C7 | 进程识别 | `proc_utils.py:47`（basename `claude`）、`liveness.py:568-570`、`admin_monitor.py:868`、`event_bus.py:810` |
| C8 | session 续跑 | `session.py:31-79`（`--resume`、跨 provider 禁止）、`runner.py:3365/3650-3671` |
| C9 | prompt 内 harness 语义硬编码 | `_noninteractive_contract_section` prompt_builder.py:787（:810/:879/:901 写死 `claude -p`）；`agents/implementer.md` 长任务等待节 |
| C10 | env 路由与清理 | `ANTHROPIC_*` maintenance_runs.py:148-157、runner.py:5679-5692；`AGENT_RUN_BANNED_ENV_KEYS` agent_env_keys.py:24-28 |
| C11 | `~/.claude` 产物读取（散件归因，fail-open 只读旁路） | `mergeback.py:1061-1068/1214-1239` |
| C12 | 架构级 ADR-055「一切 LLM 借道 claude CLI」 | `spec/knowledge/adr/ADR-055`（须以新 ADR 取代） |

worktree 目录约定 `worktrees/{impl,verify,repair,planner}-<spec>-` 虽是 Claude 惯例路径，但已被 6+ 处在飞判定当判据（pm_engine/engine.py:87 等）——**保持不动**（改它与 harness 无关且破坏面大）。

## 4. 总体架构（方案一）

### 4.1 HarnessAdapter 协议（新包 `core/agent_runner/harness/`）

```
HarnessAdapter
├─ name: str                                  # "claude" | "dsh"
├─ build_spawn_spec(req: SpawnRequest) → SpawnSpec
│      # argv / env（含清理与注入）/ stdin_payload / cwd / 配置产物准备
├─ normalize_event(raw: dict) → list[dict] | None
│      # harness 原生事件 → run jsonl 事件（claude stream-json 形状）；None=忽略
├─ classify_stderr(line: str) → 归因 | None
│      # 映射到 provider_circuit 现有分类枚举（ratelimit/unrecognized_model/transient/…）
├─ extract_result(events) → RunResultInfo
│      # session_id / usage / num_turns / 终态文本
├─ process_patterns() → list[str]
│      # pgrep/进程归属识别 pattern（替换 proc_utils 等处硬编码 "claude"）
└─ capabilities() → HarnessCapabilities
       # task_tools / resume / 批内并行 / hooks 等价物 的声明与降级标记
```

- **`claude_adapter` = 现状平移**：C1/C5/C8/C10 的全部行为搬入，行为字节级不变。以快照测试护航（同一 SpawnRequest → 平移前后 argv/env/stdin 逐字节零差异）。
- **`dsh_adapter` = 新实现**：spawn + 事件投影 + stderr 分类 + session 绑定。
- **通用读循环**：`_run_claude` 改名 `_run_agent`，内部两段——`build_spawn_spec()` → 通用 Popen + 归一化事件写盘。max_turns 守护（daemon 侧数 `turn_end`）、五路监督、终态扫描全部跑在归一化事件上，对 harness 无感。
- **表亲收编**：告警叙事经既有 `set_channel` 接缝改走 adapter；judge/蒸馏/回填/架构图/简介五个一次性 spawn 收编进 `run_one_shot(adapter, …)`；自由会话豁免（见 1.2）。

### 4.2 run jsonl：claude stream-json 形状为唯一 canon

读侧 8+ 模块（C3 清单）**零改动**。schema 中性化留作 dsh 验收后的可选还债 SPEC。

### 4.3 事件投影表（dsh_adapter.normalize_event）

| dsh 事件 | 投影为（claude 形状） | 读侧消费者 |
|---|---|---|
| `session`（流开头） | `system`/init 事件（session_id + tools 数组 = Bundle 注册工具名） | session.py 提取、run_task_track 能力探测 `read_init_tools` |
| `text` | `assistant` content text block | dashboard 叙事 |
| `thinking` | 与 claude 现状对齐（遥测过滤语义一致，runner.py:5893-5896） | 一致 |
| `tool_call name∈{TaskCreate,TaskUpdate,TaskGet,TaskList}` | `assistant` content tool_use block | **run_task_track.py 成对契约接通** |
| `tool_call`（其他）/ `tool_result` | tool_use / `user` tool_result block | dashboard 工具展示 |
| `final`（流结尾） | `result` 事件（output/num_turns/session_id/usage 形状） | liveness 终态、usage 解析、收口 |
| `error`（无 final） | `error` 事件 | `RUN_TERMINAL_EVENT_TYPES` 已含 error |

投影细则：
- dsh `truncated` 标记**保留透传**为附加字段（读侧不认识则忽略，向前兼容）；progress 类消费可容忍截断；产物硬门走文件契约不受影响。
- `num_turns` 由 `turn_end` 计数投影；exit 1 + `turn_end` reason 组合须投影为读侧可正确终判的事件序列（`_file_tail_is_terminal` 判定正确是硬要求）。
- **usage 缺口**：dsh `final` 是否携带 token usage 待 SPEC-3 真机探针确认；MVP 若无，metrics 标 `usage_source: unavailable` 成本页降级，不阻塞主链；后续 Bundle 统计插件补齐。

## 5. fenix-dsh Bundle（独立交付物）

建议独立 repo、版本化、双侧钉 dsh 版本；fenixd 以版本引用。内容：

1. **Task 工具族插件**：注册 TaskCreate/TaskUpdate/TaskGet/TaskList（签名对齐 claude 语义：subject/status/metadata），实现为会话内状态表 + 事件发射；`run_task_track.py` 的 1 基创建序约定由插件保证。dsh 原生 `dsh-tool-todo` 存在但语义未核对，SPEC-2 先探明再决定复用或自研。
2. **三个守卫插件**（挂 dsh 工具执行管道，等价 PreToolUse hooks）：主树写守卫（消费 `FENIX_RUN_PROJECT_ROOT`/`FENIX_RUN_WORKTREE` 同两个 env，等价 `block-main-tree-write.py`）、读图拦截（等价 `block-image-read.py`）、场景批处理（等价 `planner-scenario-batching.py`）。
3. **非交互审批策略**：headless 全放行（等价 bypassPermissions），主树守卫先行拦截。
4. **模型适配器配置**：OpenAI 兼容端点；由 dsh_adapter 在准备阶段渲染 provider 链（name/baseurl/apikey/model）进 Bundle 配置。**铁律：模型必须显式配置，绝不依赖 dsh 默认档**（承袭 narrative 网关别名事故教训）。
5. **项目约定载体**：dsh 侧由 system-prompt 分区读 AGENTS.md（dsh 自身即 AGENTS.md 惯例）；fenixd 仓库建 CLAUDE.md↔AGENTS.md 同步机制（软链）；ADR-269 门禁载体裁定补 dsh 变体。
6. **批内并行（明确为已知差距）**：ADR-198 靠 claude Task 子代理。dsh 侧若第一版事件级对齐做不到（`dsh-tool-subagent`/`dsh-subagent` 原生机制待探明），capabilities 声明降级为串行，不阻塞主线。

## 6. 配置模型

```yaml
agent:
  harness: claude   # claude（缺省）| dsh；全局单选
```

- `config.py` 校验（非法值回退 claude 并告警）；**Dashboard 设置页同步提供**（新增配置必须带界面的既定规则）。
- 角色级 provider/model 配置体系原样保留：adapter 是其消费方。
- dispatch 前置健康检查：`dsh --version` 探测 + 版本白名单（Bundle/adapter 各自的钉扎版本），fail-fast。
- `AGENT_RUN_BANNED_ENV_KEYS` 扩充 dsh 通道需要清除的键（`ANTHROPIC_*` 等防串扰）。

## 7. 错误处理

| 场景 | 处理 |
|---|---|
| dsh stderr `dsh: <code>: <message>` | DshAdapter.classify_stderr 映射现有 provider_circuit 分类；错误码表靠真机探针建立（对照 claude stderr 模式表 provider_circuit.py:228 做法）；网关 429 归因规则对齐既有治理 |
| session 采纳失败（未知 id / 被持有 / cwd 不符） | fail-loud 直接落到新 session 重跑路径（等价 claude resume 失败回退），不静默 |
| 跨 provider resume | 与 claude 同禁令：session 绑定 provider 指纹 |
| 流中断/进程死亡 | 终态扫描兜底（`_stream_recent` 判据不变，归一化事件层）；孤儿探测五条件沿用 |
| max_turns 超限 | daemon 数 `turn_end` 超限 kill（与 claude 现状同构） |

## 8. 风险登记

| 风险 | 缓解 |
|---|---|
| dsh 破坏性变更（官方明告） | Bundle/adapter 双侧钉 release；升级=独立 SPEC |
| `--json` 截断（8KiB/32KiB） | progress 消费容忍 + truncated 透传；硬门走文件契约 |
| usage 不可得 | MVP 降级标记，Bundle 统计插件后补 |
| 批内并行不对齐 | capabilities 降级串行 |
| daemon 自举改 runner 核心 | SPEC-1 行为平移 + 快照测试 + 既有回归网（junit 定向重试、回归车道）护航 |
| @dsh-cc 等社区生态与官方 core API 漂移 | 已实测否决 @dsh-cc 路线（见 2.3）；Bundle 只依赖官方 `@deepseek-ai/*` 包 |

## 9. 测试策略

- **平移护航**：ClaudeAdapter 快照测试（argv/env/stdin 逐字节零差异）。
- **投影层**：真机采集 dsh headless `--json` 事件样本做 fixture → 投影 → run_task_track/liveness/result_gate 现有测试全绿（现有测试原样复用即投影正确性证据）。
- **Bundle**：插件单测 + headless 冒烟（`dsh headless --json "列出现有文件"`）。
- **端到端验收**：注册玩具项目，fenix-new → ready → implement → verify → judge → merge-back → archive 全链在 dsh 跑通一条真实 SPEC。
- **测试隔离**：fake spawn 按 `cmd[0]` 分发的既有模式扩展为按 adapter 分发；禁读构建产物、禁宿主级敏感配置依赖等既有约定继续生效。

## 10. SPEC 拆分与依赖

```
SPEC-1  harness 抽象层与 claude 平移（行为零变化）
        新 ADR 取代 ADR-055 + protocol.py + ClaudeAdapter 抽取
        + 5 个一次性 spawn 点收编 + 叙事通道接 set_channel
        + agent.harness 配置 + Dashboard 设置页 + 进程识别泛化
   ├─→ SPEC-2  fenix-dsh Bundle（可与 SPEC-1 并行，接口先冻结）
   │       Task 工具族 + 三守卫 + 审批策略 + 模型配置 + AGENTS.md 载体
   │       + 真机探针（事件形态/错误码表/usage 形态/subagent 机制）
   └─→ SPEC-3  DshAdapter 接入（依赖 1+2）
           投影层 + stderr 分类 + session 绑定 + 进程 pattern
           + 前置健康检查 + usage 探明 + prompt harness_notes 占位符
        └─→ SPEC-4  dsh 主 harness 验收与切换（依赖 3）
                玩具项目全链验收 + 回切 claude 运维路径 + 验收报告
                默认值是否翻转：验收后用户决策
```

每个 SPEC 走 fenix-new 立项，daemon 循环实施；SPEC-1 立项 Scenario 须写明「行为零变化」验收判据。

## 11. ADR 影响

- 新 ADR（随 SPEC-1 立项产出）：「LLM 能力经可插拔 agent harness 接入」**取代 ADR-055**；记录自由会话豁免、run jsonl canon 决策、worktree 目录约定冻结决策。
- ADR-002（--model 语义）历史层次仅在引用处加注，不重写。
