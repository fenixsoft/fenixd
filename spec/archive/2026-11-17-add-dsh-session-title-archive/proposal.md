# Proposal: add-dsh-session-title-archive

## Why

当 fenixd daemon 以 dsh harness 驱动 agent（`agent.harness: dsh`，如 /root/cloud-phone/.fenix/config.yaml L121-124）时，每次 agent run 会在共享 DSH_HOME（如 `/root/.dsh/sessions/--root-cloud-phone-.claude-worktrees-impl-*--/`）留下一个 headless 会话。这些会话全部涌入用户 dsh web（127.0.0.1:3080）的「未分组」区域、标题显示「未命名」且永不归档——大量一次性 run 会话把用户自己的交互会话淹没，列表完全不可用。

三项根因（均已核实）：

1. **无标题**：fenix profile（`dsh-bundle/cordis.patch.yml`）未挂载 `dsh-session-title` 服务，headless 会话无标题来源，web 显示「未命名」（`dsh-client-ui-workspace` client.js `session.untitled`）。
2. **不归档**：归档状态存在 workspace registry（`/root/.dsh/storages/workspace.json` 的 `archivedSessionIds`），只有用户手动归档或 web 进程写路径才会进入；fenixd 不做任何收尾标记。
3. **不分组（dsh 上游限制，本 SPEC 不解决分组）**：会话归属工程的唯一判据是会话记录 cwd 的 realpath **精确等于** workspace 注册路径（`dsh-workspace` README："a session from another directory cannot be moved in"，无 move API）。agent 会话 cwd 是隔离 worktree，永远落「未分组」。fenixd 侧无解，以「归档隐藏 + 标题内嵌工程名」降级补偿。

## What Changes

- **dsh-bundle 新增标题装配**：fenix profile 挂载 `dsh-session` + `dsh-session-title` 服务（含必需 limits 配置 `fallbackMaxWords` / `fallbackMaxBytes` / `maxTitleBytes`），并以确定性标题（由 spawn env `FENIX_RUN_PROJECT_ROOT` / `FENIX_RUN_WORKTREE` 派生，形如 `cloud-phone · impl-code-review-fix-1794159697`）在会话启动期完成命名，使 dsh web 不再显示「未命名」。标题写入会话自身 header（会话所属进程自有写路径），无跨进程写风险。
- **fenixd daemon 新增 dsh 会话收尾归档**：dsh harness run 到终态且捕获 `session_id`（DshAdapter 已从 `session` 事件留存，见 `core/agent_runner/harness/dsh_adapter.py` session→init 投影）后，经 dsh web HTTP API（API Gateway `/api/remote.mux` WebSocket、`dsh-api-workspace-controller` 的 `workspace.archiveSession`）将该会话标记归档；web 默认视图随即隐藏该会话。
  - 归档调用以 **Node helper 脚本**（复用 `dsh-bundle/node_modules/@deepseek-ai/` 既有 client SDK，官方协议帧）实现，daemon 以子进程方式调用，不手搓 WS 帧协议。
  - 鉴权凭据从 DSH_HOME 下 `.credentials.yaml` 的 `records.client-connection.browser-session.payload.secret` 读取（已确认该文件存在且 daemon 进程可读）。
  - web 离线/调用失败时进入**持久化重试队列**（backoff，daemon 重启不丢），恢复后补归档；归档幂等（已归档会话按成功处理）。
  - 新增配置键：`agent.dsh_web_url`（缺省 `http://127.0.0.1:3080`）与 tidy 总开关（缺省开，仅 `agent.harness: dsh` 时生效）。
- **明确非目标（上游限制）**：不实现「会话归入工程工作区分组」——dsh-workspace 无 move API 且归属判据为 cwd 精确匹配，worktree 会话在「显示归档」视图中仍出现在「未分组」组内，靠标题内嵌工程名辨认。

## Capabilities

### New Capabilities

- `dsh-session-hygiene` — dsh 驱动的 agent 会话自动卫生：确定性标题（bundle 侧）+ run 终态自动归档（daemon 侧，含重试队列与幂等）。

### Modified Capabilities

（无——已检索 `spec/changes/*/specs/` 与 `spec/archive/*/specs/`，无既有能力声明 dsh 会话标题/归档行为；`dsh-harness-integration`、`fenix-dsh-bundle` 域的既有需求不变。）

## Impact

- **dsh-bundle/**：`cordis.patch.yml` 增加两个服务条目与一个小插件（TS）；bundle 版本钉扎面如受影响需同步（`fenix-dsh-bundle` 能力域）。不触碰既有五件套与三守卫。
- **core/agent_runner/**：run 终态收尾链路（`runner.py` `_log_run_metrics` 邻域）挂接归档投递；新增归档投递模块（pending 队列持久化 + 子进程调用 helper）。
- **core/config.py**：新增 `agent.dsh_web_url`、tidy 开关配置键与校验。
- **部署面**：cloud-phone 等以 `harness: dsh` 运行的 fenixd 管理工程，升级 fenixd + 重建 dsh-bundle 部署副本后自动生效；用户 dsh web 需保持运行才能实时归档（离线由重试队列兜底）。
- **风险**：web API 鉴权握手的精确形态（header/cookie 名）以 client SDK 源码为准，实现期核实；`/root/.dsh` 对 daemon 进程可读性在部分部署（如只读挂载）下可能不成立——读失败时 tidy 静默降级（WARN 留痕），不影响 run 主链路。
