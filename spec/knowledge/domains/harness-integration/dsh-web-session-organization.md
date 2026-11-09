# dsh web 会话组织（分组 / 标题 / 归档）

<!-- knowledge: capability=dsh-web-session-organization rev=1
     sources=spec/knowledge/_inbox/done/dsh-web-session-organization.md -->

dsh web 对 agent 会话的分组、命名与归档组织规则，以及 fenixd 通道（bundle 标题装配 + daemon 终态归档投递）消费这些规则的方式——headless run 会话在 dsh web 中的可见性与收尾卫生由这一层约束。

## 规则

- **分组归属判据（上游限制）**：会话归属工程 workspace 的唯一判据 = 会话记录 cwd 的 realpath **精确等于** workspace 注册路径；无 move API（dsh-workspace README："a session from another directory cannot be moved in"），外部目录会话不能移入。worktree cwd 的 agent 会话恒落「未分组」，fenixd 侧无解；降级补偿 = 确定性标题内嵌工程名 + 终态自动归档隐藏。registry 的 workspace bootstrap 仅首次（`initialized` 标记）。
- **registry 写约束**：registry 位于 `<dsh_home>/storages/workspace.json`（workspace v2：workspaces 表 + global.workspaceIds / archivedSessionIds / pinnedSessionIds / initialized）。dsh-storage-json 无跨进程写锁、last-completion wins——非 web 进程直写 registry 会与 web 进程内存缓存互相覆盖（丢更新、UI 不刷新），headless 侧严禁直写。
- **归档通道**：归档唯一正确姿势 = 经 dsh web HTTP API（API Gateway `/api/remote.mux` WebSocket，`dsh-api-workspace-controller` 的 `workspace.archiveSession`），helper 复用 `@deepseek-ai/` 官方 client SDK、不手搓 WS 帧协议。鉴权凭据 = `<dsh_home>/.credentials.yaml` 的 `records.client-connection.browser-session.payload.secret`（daemon 同主机可读，经 `--secret-file` 传入）。归档幂等（已归档按成功）；目标会话仍有活动且无 stopActivity 时 API 报 `workspace/session-active`（可重试类）。web 默认视图（Hide archived）隐藏归档会话；归档会话不可打开、可 Unarchive。
- **标题服务**：dsh-session-title 标题三来源 newest-wins（首条 human message 兜底 / provider / rename()）；limits 三键 `fallbackMaxWords` / `fallbackMaxBytes` / `maxTitleBytes` 全必填无缺省。fenix profile 以 `fenix-session-title` entry 挂载 dsh-session + dsh-session-title 服务（dsh-base 首层 insert，bundle 以 id 寻址 config-only 覆盖 limits 为 8/96/120），会话启动期（session/created）以 spawn env 派生确定性标题 `<工程basename> · <worktreebasename>`（UTF-8 字节截断至 maxTitleBytes）经 `sessionTitle.rename()` 落 header，user 源 pin 住（同时省去 session-title-llm 对 boilerplate 首条消息的 LLM 生成）；两 env 全缺不命名，交由内置兜底。标题写会话自身 header（进程自有写路径），无跨进程写风险。
- **run 会话落点与收尾**：`agent.harness: dsh` 管理工程的 agent run 会话落 `<dsh_home>/sessions/--<cwd路径编码>--/`；daemon 在 run 终态捕获 session_id 后投递自动归档（web 离线或可重试失败入持久化重试队列，daemon 重启不丢），run 会话对用户 web 默认视图不可见，工程辨认靠标题。
- **bash 沙箱限制**：本机 bash 沙箱内 `/root/.dsh` 只读（EROFS），裸跑 dsh 会失败；daemon 主进程不受此限。worktree 内测试一律用临时 `DSH_HOME`（隔离纪律见 fenix-dsh-bundle）。

## 代码锚点

- 标题装配插件：`dsh-bundle/src/session-title.ts`；挂载与 limits 覆盖：`dsh-bundle/cordis.patch.yml`
- daemon 归档投递与重试队列：`core/dsh_session_tidy.py`；bundle 侧归档 helper：`dsh-bundle/src/session-tidy-helper.ts`
- 消费方（run 终态挂接）：`core/agent_runner/runner.py`
- 守卫测试：`tests/test_dsh_session_tidy.py`、`dsh-bundle/tests/session-title.test.ts`、`dsh-bundle/tests/session-tidy-helper.test.ts`、`dsh-bundle/tests/auth-probe.test.ts`

## 溯源

- 2026-11-09 dsh-web-session-organization（spec/knowledge/_inbox/done/dsh-web-session-organization.md） — 折叠 dsh web 会话组织侦察结论：分组 cwd 精确匹配判据与无 move API 上游限制、registry 写约束、归档 API 通道与鉴权凭据、标题服务三来源与 limits 必填、bash 沙箱 EROFS 限制；按后写覆盖前写更新当前态（profile 已挂载标题服务、daemon 已实现终态自动归档）
