# dsh web 会话组织机制（workspace 分组 / 标题 / 归档）侦察结论

- 2026-11-09，来源：/fenix-new 需求「dsh web 中 agent 会话自动归档/分组/标题」立项侦察（SPEC add-dsh-session-title-archive）。
- **分组**：会话归属工程 workspace 的唯一判据 = 会话记录 cwd realpath 精确等于 workspace 注册路径（dsh-workspace README："a session from another directory cannot be moved in"，无 move API）。worktree cwd 的 agent 会话永远落「未分组」，fenixd 侧无解，属 dsh 上游限制。bootstrap 仅首次（registry `initialized` 标记）。
- **registry**：`<dsh_home>/storages/workspace.json`（unit workspace v2：workspaces 表 + global.workspaceIds/archivedSessionIds/pinnedSessionIds/initialized）。写路径经 domain write chain；dsh-storage-json README 明示 **No cross-process write locking — last-completion wins** → 非 web 进程直接写 registry 会与 web 进程内存缓存互相覆盖（丢更新、UI 不刷新），headless 侧严禁直接写。
- **归档**：正确姿势 = 经 dsh web HTTP API（API Gateway `/api/remote.mux` WebSocket，`dsh-api-workspace-controller` 的 `ctx.remote.workspace.archiveSession`）。鉴权凭据 = `<dsh_home>/.credentials.yaml` 的 `records.client-connection.browser-session.payload.secret`（daemon 同主机可读；精确握手形态以 `@deepseek-ai/dsh-api-gateway/client` SDK 为准）。web 默认视图（Hide archived）隐藏归档；归档不可打开可 Unarchive；无 stopActivity 时对有活动会话报 `workspace/session-active`。
- **标题**：dsh-session-title 服务三来源 newest-wins（首条 human message 兜底 / provider / rename()），limits 三键全必填无缺省（fallbackMaxWords/fallbackBytes/maxTitleBytes）。fenix profile（dsh-bundle/cordis.patch.yml）原先未挂载 → headless 会话显示「未命名」。标题写会话 header（进程自有写路径，无跨进程问题）。
- **触发现场**：`agent.harness: dsh` 的管理工程（如 /root/cloud-phone/.fenix/config.yaml L121-124）的 agent run 会话落 `<dsh_home>/sessions/--<cwd路径编码>--/`，即「未分组+未命名+永不归档」的来源；fenixd 本项目缺省 claude 通道（core/config.py get_harness）。
- **bash 沙箱限制**：本机 bash 内 `/root/.dsh` 只读（EROFS），裸跑 dsh 会失败；fenixd daemon 主进程不受此限。worktree 内测试需用临时 DSH_HOME。
