# dsh web 会话组织（分组 / 标题 / 归档）

<!-- knowledge: capability=dsh-web-session-organization rev=2
     sources=spec/knowledge/_inbox/done/dsh-web-session-organization.md,spec/changes/add-dsh-session-title-archive -->

dsh web 对 agent 会话的分组、命名与归档组织规则（上游机制面）——headless run 会话在 dsh web 中的可见性约束。fenixd 侧对这些规则的消费（确定性标题装配 + run 终态归档投递）见 [dsh 会话自动卫生](dsh-session-hygiene.md)。

## 规则

- **分组归属判据（上游限制）**：会话归属工程 workspace 的唯一判据 = 会话记录 cwd 的 realpath **精确等于** workspace 注册路径；无 move API（dsh-workspace README："a session from another directory cannot be moved in"），外部目录会话不能移入。worktree cwd 的 agent 会话恒落「未分组」，fenixd 侧无解；降级补偿 = 确定性标题内嵌工程名 + 终态自动归档隐藏。registry 的 workspace bootstrap 仅首次（`initialized` 标记）。
- **registry 写约束**：registry 位于 `<dsh_home>/storages/workspace.json`（workspace v2：workspaces 表 + global.workspaceIds / archivedSessionIds / pinnedSessionIds / initialized）。dsh-storage-json 无跨进程写锁、last-completion wins——非 web 进程直写 registry 会与 web 进程内存缓存互相覆盖（丢更新、UI 不刷新），headless 侧严禁直写。
- **归档通道**：归档唯一正确姿势 = 经 dsh web HTTP API（API Gateway `/api/remote.mux` WebSocket，`dsh-api-workspace-controller` 的 `workspace.archiveSession`），复用 `@deepseek-ai/` 官方 client SDK、不手搓 WS 帧协议。鉴权凭据 = `<dsh_home>/.credentials.yaml` 的 `records.client-connection.browser-session.payload.secret`（daemon 同主机可读）。归档幂等（已归档按成功）；目标会话仍有活动且无 stopActivity 时 API 报 `workspace/session-active`（可重试类）。web 默认视图（Hide archived）隐藏归档会话；归档会话不可打开、可 Unarchive。
- **标题服务**：dsh-session-title 标题三来源 newest-wins（首条 human message 兜底 / provider / rename()）；limits 三键 `fallbackMaxWords` / `fallbackMaxBytes` / `maxTitleBytes` 全必填无缺省；`rename()` 落 header 且 user 源 pin 住，属会话进程自有写路径、无跨进程写风险。fenix profile 的挂载与确定性标题派生见 [dsh 会话自动卫生](dsh-session-hygiene.md)。
- **run 会话落点**：`agent.harness: dsh` 管理工程的 agent run 会话落 `<dsh_home>/sessions/--<cwd路径编码>--/`；run 结束后的收尾卫生（终态自动归档）由 [dsh 会话自动卫生](dsh-session-hygiene.md) 承载，run 会话对用户 web 默认视图不可见，工程辨认靠标题。
- **bash 沙箱限制**：本机 bash 沙箱内 `/root/.dsh` 只读（EROFS），裸跑 dsh 会失败；daemon 主进程不受此限。worktree 内测试一律用临时 `DSH_HOME`（隔离纪律见 fenix-dsh-bundle）。

## 代码锚点

无独立实现载体（规则面属 dsh 上游仓库，非本仓代码）；fenixd 消费侧实现锚点见 [dsh 会话自动卫生](dsh-session-hygiene.md)。

## 溯源

- 2026-11-09 dsh-web-session-organization（spec/knowledge/_inbox/done/dsh-web-session-organization.md） — 折叠 dsh web 会话组织侦察结论：分组 cwd 精确匹配判据与无 move API 上游限制、registry 写约束、归档 API 通道与鉴权凭据、标题服务三来源与 limits 必填、bash 沙箱 EROFS 限制；按后写覆盖前写更新当前态（profile 已挂载标题服务、daemon 已实现终态自动归档）
- 2026-11-09 add-dsh-session-title-archive（spec/changes/add-dsh-session-title-archive/） — fenixd 消费侧规则（标题派生/终态归档投递/重试队列/配置键）整体迁出至 dsh-session-hygiene 页，本页收窄为 dsh 上游规则面并互链
