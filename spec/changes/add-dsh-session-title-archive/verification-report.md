# 验证报告：add-dsh-session-title-archive

> ⚠️ 本报告由框架于 2026-11-09T02:03:04Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。
> 报告时效标记（判定本报告是否属上一轮）：合成源轮次指纹：report.json@2026-11-09T02:03:04.686581+00:00+run-result@mtime1794189784732532259

## 结论：✅ 通过（verified）

**状态：verified — 7/7 场景通过，0 失败，0 错误（全部场景通过）**

全绿快道: 7/7 场景通过、0 失败 0 警告——无分类对象，跳过 judge 机械 verified

| 指标 | 数量 |
| --- | --- |
| 通过 | 7 |
| 失败 | 0 |
| 错误 | 0 |
| 产品 Bug | 0 |
| 本链增量 Token（输入） | 2.09M |
| 本链增量 Token（输出） | 0.05M |


## 场景结果

| 场景 | 描述 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- | --- |
| dsh-title-unit-tests | 会话确定性标题插件行为（bundle 侧）：dsh-bundle/tests/session-title.test.ts 全绿，覆盖 tasks 1.1 钉扎的五分支——正常派生（FENIX_RUN_PROJECT_ROOT/FENIX_RUN_WORKTREE basename 拼接「工程 · worktree」）、超 maxTitleBytes=120 UTF-8 字节截断不报错、单 key 缺席回退另一 key basename、双 key 全缺不命名不抛错（会话启动不阻塞）、重复触发幂等不覆盖既有非默认标题；套件内集成冒烟用例（隔离 DSH_HOME dump-config 探测，tasks 1.3）在 dsh 二进制缺席时明确 skip 留痕不 fail。环境依赖（npm registry 可达）有 fallback: pnpm 本地 store 缓存 prefer-offline + --ignore-scripts 重试。出处：spec.md「会话确定性标题（bundle 侧）」两 Scenario + tasks.md 1.1/1.3 + core/agent_runner/harness/dsh_adapter.py:941（标题派生 env 注入源）。 | pass | 0/4 | - |
| dsh-title-patch-assembly | fenix profile 标题装配静态契约：dsh-bundle/cordis.patch.yml 含 @deepseek-ai/dsh-session 与 @deepseek-ai/dsh-session-title 服务条目，limits 三键全显式（fallbackMaxWords: 8 / fallbackMaxBytes: 96 / maxTitleBytes: 120）；服务条目为 dsh 侧 config 面（顶格 - id: 条目形态），且 MUST NOT 出现在任何 entry 的 inject 列表（cordis disabled/inject 装配事故纪律，见 cordis.patch.yml 头注——inject 会让 cordis 等待永不激活的服务、entry 卡 pending）。出处：spec.md「MUST 挂载 dsh-session 与 dsh-session-title 服务」+ tasks.md 1.2 + dsh-bundle/cordis.patch.yml:2-36（装配纪律头注）。 | pass | 0/6 | - |
| dsh-tidy-config-surface | tidy 配置面与投递器落盘契约静态核验：core/config.py 含 agent.dsh_web_url 键与缺省字面量 http://127.0.0.1:3080、agent.dsh_session_tidy 开关键（缺省 true，走 get_harness 同面 ConfigLoader 模式）；core/dsh_session_tidy.py 投递器以 subprocess 子进程调 helper（Python 不手搓 WS 帧）且持久化重试队列路径字面量 .fenix/dsh_session_tidy/pending.jsonl 在位（对齐 .fenix/runs、maintenance_log.jsonl 既有惯例）。出处：spec.md「配置面」+ tasks.md 3.1/3.2 + core/config.py:378（get_harness 同面先例）+ design.md D2/D3。 | pass | 0/6 | - |
| dsh-tidy-docs | 文档与探针结论沉淀：dsh-bundle/README.md 增补标题装配说明（服务条目与 limits）、session-tidy-helper 用法与退出码表、部署注意（web 在线实时归档/离线队列兜底、.credentials.yaml 依赖）、「分组归工程工作区受 dsh-workspace cwd 精确匹配 + 无 move API 限制」的范围说明；dsh-bundle/docs/probe-findings.md 新增鉴权握手探针结论章节（records.client-connection/browser-session grant、header/cookie 形态、最小连通性证据，tasks 2.1）。tasks.md:40 的 link 候选为文档行内链接、纯展示非页面交互元素，declared_display 登记。出处：tasks.md 4.1/2.1 + proposal.md Impact 段。 | pass | 0/7 | - |
| dsh-tidy-helper-unit-tests | 归档 helper 契约（bundle 侧）：dsh-bundle/tests/session-tidy-helper.test.ts 与 tests/auth-probe.test.ts 套件全绿（无真实 dsh web 的验证树上探针用例按 tasks 2.1 skip 留痕、不 fail）。覆盖 tasks 2.2/2.3 钉扎契约——CLI 参数解析（--url/--secret-file/--session-id/--timeout）、退出码三分类（0=成功/已归档幂等、1=致命〔凭据缺失/协议错〕、2=可重试〔连接失败/超时/session-active〕）、stdout 单行 JSON {ok, session_id, outcome, detail}；归档调用集成用例验证 workspace.archiveSession 幂等分类与 archivedSessionIds 写入。环境依赖（真实 dsh web 在场方可全链路集成）有 fallback: 隔离 DSH_HOME web 实例，仍不可行时以最小 WS stub 复现 gateway invoke 帧（tasks 2.3 既有 fallback 条款，差异在用例注释注明）。出处：spec.md「归档投递 MUST 以子进程调用 Node helper」+ tasks.md 2.1/2.2/2.3。 | pass | 0/5 | - |
| dsh-tidy-helper-build-entry | helper 编译产物入口：pnpm build 后 dsh-bundle/dist/session-tidy-helper.mjs 存在（daemon 子进程调用的实际入口，产物 gitignored 不入库、验证树上由 build 现产），产物内含 workspace.archiveSession 调用面（复用 @deepseek-ai/dsh-api-gateway/client 官方 SDK，Python 侧零手搓 WS 帧）。环境依赖（npm registry 可达）有 fallback: pnpm 本地 store 缓存 prefer-offline + --ignore-scripts 重试。出处：tasks.md 2.2「编译产物入口为 dsh-bundle/dist/session-tidy-helper.mjs」+ spec.md「归档投递 MUST 以子进程调用 Node helper（复用既有 client SDK 与官方协议帧）」。 | pass | 0/5 | - |
| dsh-tidy-daemon-tests | daemon 侧 tidy 投递全量单测：tests/test_dsh_session_tidy.py 全绿。覆盖 tasks 3.1/3.2/3.3 钉扎的行为分支——投递器入队/backoff 重试/放弃阈值（200 条或 30 天先到为准，放弃 WARN）/「已归档」幂等按成功/队列文件读写 round-trip（daemon 重启恢复消费）；配置校验与缺省（dsh_web_url 缺省 http://127.0.0.1:3080、非法 URL 启动校验报错、dsh_session_tidy 缺省 true、false 时投递暂停且队列不清空）；runner 终态挂接（_log_run_metrics 邻域）成功/超时/异常三形态均不影响终态指标行与门禁、非 dsh harness 零动作、终态缺 session_id 仅 WARN 不入队（spec 接受噪音条款）、workspace/session-active 按「稍后重试」入队。对应 spec 三 Scenario：run 终态后自动隐藏（stub/monkeypatch 层验证）、web 离线时入队重试、harness 非 dsh 时零动作。出处：spec.md「run 终态自动归档（daemon 侧）」+「配置面」+ tasks.md 3.1/3.2/3.3 + core/agent_runner/runner.py:530（_log_run_metrics 收尾邻域挂接点）。 | pass | 0/3 | - |

## 本轮场景集变更

当前稳定场景集共 7 个（第 1 轮）。

- 首轮写入 7 个场景

