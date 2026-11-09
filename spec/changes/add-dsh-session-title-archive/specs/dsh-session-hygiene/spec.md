# dsh-session-hygiene — dsh 驱动会话自动标题与归档

## ADDED Requirements

### Requirement: 会话确定性标题（bundle 侧）

fenix profile（`dsh-bundle/cordis.patch.yml` 装配）MUST 挂载 `dsh-session` 与 `dsh-session-title` 服务，并使每个由 fenixd 经 dsh 启动的 headless agent 会话在启动期获得一个确定性标题，使 dsh web 不再显示「未命名」。

- 标题 MUST 由 spawn env 的 `FENIX_RUN_PROJECT_ROOT` 与 `FENIX_RUN_WORKTREE` 派生，格式 `<工程目录basename> · <worktree目录basename>`（示例：`cloud-phone · impl-code-review-fix-1794159697`）；任一 env 缺席时 MUST 回退到另一 key 的 basename，两者全缺时不命名（交由 dsh-session-title 内置兜底），MUST NOT 使会话启动失败。
- 标题 MUST 尊重 `dsh-session-title` 的 `maxTitleBytes` 上限（装配时设为 120，UTF-8 字节），超限截断不报错。
- 标题写入走会话自身 header 写路径（同进程），MUST NOT 依赖 dsh web 在线。
- 命名 MUST 幂等：重复触发（如 resume）MUST NOT 覆盖既有非默认标题。

#### Scenario: headless 会话启动后获得确定性标题

- **WHEN** fenixd 以 dsh harness 派发 agent run，spawn env 含 `FENIX_RUN_PROJECT_ROOT=/root/cloud-phone`、`FENIX_RUN_WORKTREE=/root/cloud-phone/.claude/worktrees/impl-code-review-fix-1794159697`
- **THEN** 该 dsh 会话 header 的标题为 `cloud-phone · impl-code-review-fix-1794159697`，dsh web 会话列表该行不再显示「未命名」

#### Scenario: env 残缺不阻塞启动

- **WHEN** spawn env 两个 `FENIX_RUN_*` key 均缺失
- **THEN** 会话正常启动（不抛错、不挂起），标题由 `dsh-session-title` 内置兜底逻辑产生

### Requirement: run 终态自动归档（daemon 侧）

`agent.harness: dsh` 且 tidy 开启（缺省开启）时，fenixd daemon MUST 在 run 到达终态且已捕获 dsh `session_id` 后，将该会话经 dsh web HTTP API（API Gateway `/api/remote.mux`、`dsh-api-workspace-controller` 的 `workspace.archiveSession`）标记为归档，使 web 默认视图（Hide archived）不再显示该会话。

- 归档投递 MUST 以子进程调用 Node helper（复用 `dsh-bundle/node_modules/@deepseek-ai/` 既有 client SDK 与官方协议帧）完成；Python 侧 MUST NOT 手搓 WS 帧协议。
- 鉴权凭据 MUST 从 `<dsh_home>/.credentials.yaml` 的 `records.client-connection.browser-session.payload.secret` 读取；凭据缺失或不可读时投递 MUST 失败入队 + WARN 留痕，MUST NOT 影响主链路。
- 归档 MUST 幂等：目标会话已归档时按成功处理。
- run 主链路（事件投影、run_metrics、门禁）MUST NOT 依赖归档结果：投递同步等待有上限（可配置超时，缺省 10s），超时/失败转异步重试。
- 归档调用 MUST 不带 `stopActivity`（run 已终态，无活动工作）；`workspace/session-active` 错误按「稍后重试」处理并入队。

#### Scenario: run 终态后 dsh web 自动隐藏会话

- **WHEN** 一个 dsh harness run 成功终态且 session 事件提供了 `session_id`，dsh web 在线且鉴权可用
- **THEN** 数秒内该会话 id 进入 workspace registry 的 `archivedSessionIds`，dsh web 默认视图不再显示该会话，run 主链路结果不受影响

#### Scenario: web 离线时入队重试

- **WHEN** 归档投递时 dsh web 未运行（连接失败/超时）
- **THEN** 投递任务进入持久化重试队列（daemon 重启不丢），按 backoff 重试；web 恢复后队列清空，会话最终被归档；期间 WARN 留痕且不影响后续 run

#### Scenario: harness 非 dsh 时零动作

- **WHEN** `agent.harness` 为 `claude`（或缺省）
- **THEN** 不产生任何归档投递、helper 调用或重试队列活动

### Requirement: 配置面

tidy 行为 MUST 可配置且缺省安全：

- 新增 `agent.dsh_web_url`：dsh web 基址，缺省 `http://127.0.0.1:3080`，非法 URL MUST 启动校验报错。
- 新增 tidy 总开关（`agent.dsh_session_tidy`，缺省 `true`）：置 `false` 时 daemon 侧不投递归档、重试队列暂停消费；bundle 侧标题装配不受该开关影响。
- 两个键 MUST 支持既有 agent 配置的分层与热重载生效语义（与 `agent.harness` 同面）。

#### Scenario: 关闭开关后仅保留标题

- **WHEN** 用户设 `agent.dsh_session_tidy: false`
- **THEN** 新 run 仍有确定性标题，但 daemon 不再归档新会话；既有重试队列暂停（不清空），恢复开关后继续
