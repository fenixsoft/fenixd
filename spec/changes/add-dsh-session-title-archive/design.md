# Design: add-dsh-session-title-archive

## Context

fenixd 以 dsh harness 驱动 agent 时，headless 会话落在共享 DSH_HOME（`/root/.dsh/sessions/`），在用户 dsh web（127.0.0.1:3080）显示为「未分组 + 未命名 + 永不归档」。侦察已核实的机制面：

- **标题**：dsh `dsh-session-title` 服务三来源 newest-wins（首条 human message 兜底 / provider / `rename()`）；fenix profile（`dsh-bundle/cordis.patch.yml`）未挂载 → 无标题。标题写入会话 header，属会话所属进程自有写路径，无跨进程问题。
- **归档**：workspace registry `/root/.dsh/storages/workspace.json` 的 `archivedSessionIds`；web 默认视图（Hide archived）隐藏归档会话。写路径经 domain write chain；`dsh-storage-json` README 明示 **No cross-process write locking — last-completion wins** → headless 进程直接写 registry 与 web 进程内存缓存互相覆盖（丢更新、UI 不刷新），**不可采用**。
- **web API**：`dsh-api-workspace-controller` 提供 `archiveSession/unarchive`（经 API Gateway `/api/remote.mux` WebSocket，Typert RPC）；无 `stopActivity` 时对有活动会话报 `workspace/session-active`。客户端协议由 `@deepseek-ai/dsh-api-gateway/client` SDK 承载（dsh-bundle/node_modules 已含）。
- **鉴权**：`/root/.dsh/.credentials.yaml` 存在 `records.client-connection/browser-session` grant（43 字符 secret）；browser 客户端即以此接入，daemon 进程同主机可读。握手的精确 header/cookie 名以 client SDK 源码为准（实现期核实，风险段）。
- **session_id 捕获**：`core/agent_runner/harness/dsh_adapter.py` 从 `session` 事件留存 `session_id`（`entry.get("sessionId")`，session→init 投影 L409-415），run 终态时已知。
- **spawn env**：adapter 已注入 `FENIX_RUN_PROJECT_ROOT` / `FENIX_RUN_WORKTREE`（守卫同源）；worktree basename 自带 `角色-spec-时间戳` 结构，足以构造可读标题。
- **知识域**：`spec/knowledge/domains/harness-integration/_domain.md`（3.2）——进程边界为唯一接缝（SpawnSpec 进、归一化事件出）；本设计的归档投递挂在 run 终态收尾，不触碰进程边界协议。

## Goals / Non-Goals

**Goals**

1. dsh web 不再显示「未命名」：每个 fenixd 派发的 dsh 会话有确定性标题。
2. dsh web 默认视图不再堆积 agent 会话：run 终态自动归档，web 离线由持久化重试兜底。
3. 全链路失败安全：归档/标题任一环节故障不阻塞 agent run 主链路。

**Non-Goals**

- **不做「会话归入工程工作区分组」**：dsh-workspace 归属判据为 cwd realpath 精确匹配 + 无 move API，worktree 会话无法归组（上游限制）。降级方案 = 归档隐藏 + 标题内嵌工程名；用户在「Archived only / All」视图按标题辨认归属。若上游未来提供 move/别名能力，另立 SPEC。
- 不改动 dsh 上游（版本白名单 0.2.0-rc.2 钉扎不动）；不做会话内容检索/聚合等增强。
- 不处理非 fenixd 产生的 dsh 会话（用户交互会话不受影响）。

## Decisions

### D1 标题：bundle 内 rename（而非 provider / 而非 daemon 侧 API rename）

- fenix profile 增加服务条目：`@deepseek-ai/dsh-session` + `@deepseek-ai/dsh-session-title`（limits：`fallbackMaxWords: 8` / `fallbackMaxBytes: 96` / `maxTitleBytes: 120`，README 全必填无缺省）+ 一个小插件在激活期以 env 派生标题调用 `ctx.sessionTitle` 的命名入口（优先 `rename()` 语义——立即落 header 且 pin 住；若安装版 SDK 的 provider 接口对确定性标题更贴合则以 provider 实现之，二选一以实测为准）。
- **为什么不用 provider 的 LLM 生成**：run 元数据已足够构造确定性标题，无需额外 LLM 调用与延迟；LLM 生成对 boilerplate 首条消息（fenix 系统提示词开头）无意义。
- **为什么不在 daemon 侧经 API rename**：标题属会话 header（会话进程自有写路径），bundle 内做零依赖（web 离线也有标题）；经 API 反而引入与归档相同的在线依赖。
- env 派生规则：`<PROJECT_ROOT basename> · <WORKTREE basename>`；超 `maxTitleBytes` 截断；env 缺失逐级回退、全缺不命名不报错（对齐 spec Scenario）。
- **纪律对齐**：服务条目为 dsh 侧 config 面（`- id: ...` + config 段），MUST NOT 写进任何 entry 的 inject 列表（cordis disabled/inject 装配事故既有教训，见 cordis.patch.yml 头注）；title 服务依赖 session store，装配顺序在 dsh-base session 条目之后由 patch insert 追加，启动期以端到端冒烟验证。

### D2 归档投递：daemon 子进程调 Node helper（而非 Python 手搓 WS / 而非 headless 写 registry）

- 新增 Node helper（落 `dsh-bundle/` 源内，随 bundle 构建产出可执行入口；daemon 以 `node <helper> --url <web_url> --secret-file <dsh_home>/.credentials.yaml --session-id <id>` 调用）：使用 `@deepseek-ai/dsh-api-gateway/client` 开 `/api/remote.mux` 连接，调 `ctx.remote.workspace.archiveSession(sessionId)`，成功/已归档/可重试三类退出码 + 单行 JSON 结果到 stdout。
- **为什么不用 Python 直连**：/api/remote.mux 是 Typert RPC 帧协议（InvocationDescriptor 编解码），Python 手搓高风险；SDK 已在 node_modules，复用即零新依赖。
- **为什么不用 headless 进程写 registry**：跨进程无锁，web 内存缓存覆盖丢更新、UI 不实时刷新（dsh-storage-json README 明示），明确排除。
- daemon 侧新增 `core/dsh_session_tidy.py`（命名可调）：终态收尾（`_log_run_metrics` 邻域、仅 dsh harness 且开关开启时）→ 同步等待 ≤10s → 失败入**持久化重试队列**（JSONL，`<project_root>/.fenix/dsh_session_tidy/pending.jsonl`，与 `.fenix/runs`、`.fenix/maintenance_log.jsonl` 同惯例；daemon 重启恢复消费、backoff 重试、上限后标记放弃并 WARN）；幂等：helper 收到「已归档」类错误按成功退出。终态但未捕获 `session_id`（session 事件缺失）的 run 不投递、WARN 留痕即止——此类会话无归档目标，属接受噪音。

### D3 配置：两个新键走既有 agent 配置面

- `agent.dsh_web_url`（缺省 `http://127.0.0.1:3080`）+ `agent.dsh_session_tidy`（缺省 true）。校验（URL 形态）、分层覆盖、热重载语义与 `agent.harness` 同面（`core/config.py` `get_harness` 邻域）；开关为 false 时队列暂停消费不清空。

### D4 失败安全与可观测性

- 归档/标题全链路异常（凭据缺失、web 不可达、helper 崩溃、超时）MUST NOT 影响 run 主链路：投递包裹在 try/except，终态指标行照常落。
- 可观测性：投递尝试与结果（成功/已归档/入队/放弃）以 WARN/INFO 落 daemon 日志；重试队列长度变化在队列落盘时留痕。不做仪表盘新页（避免 UI 面）。

## Risks / Trade-offs

- **web API 鉴权握手形态未实测**（header/cookie 名、grant 换取会话票据的精确流程）：以 client SDK 源码 + 本机 web 实测核实（helper 开发第一步即打通最小连通性探针）；若 grant 形态与预期不符导致无法接入，降级路径 = helper 内走 SDK 的 credential seam 读取 `.credentials.yaml`（SDK 同面机制），再降级 = 仅保留标题、归档退化为文档化手动操作（tasks 相应收缩并申报）。
- **`/root/.dsh` 只读挂载部署**（本机 bash 实测 EROFS）：daemon 主进程实测可读（registry/credentials 由 web 进程写入成功，同目录）；若某部署不可读，凭据读取失败走入队+WARN，主链路不受影响。
- **归档风暴**：批量 backlog 恢复时队列重放对 web 的写压力——backoff 上限并发 1、helper 单次调用即退，风险可控。
- **web 长期不运行**：队列积压至上限后放弃并 WARN（放弃阈值可配，缺省 200 条或 30 天，先到为准）；用户以「Archived only」手动清理仍可行。

## Migration Plan

零迁移：存量未命名/未归档会话不做批量回填（历史会话用户已手动归档 18 条，剩余属可接受噪音）；新机制仅对新 run 生效。回滚 = 关 `agent.dsh_session_tidy` 开关 + bundle 构建回退（标题装配随 profile patch 回退）。

## Open Questions

- helper 与 daemon 的进程边界协议（stdout JSON schema、退出码表）在 tasks 1.x 由实现确定并落测试；不阻塞设计。
