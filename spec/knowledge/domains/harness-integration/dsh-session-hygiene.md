# dsh 会话自动卫生（确定性标题 / run 终态归档）

<!-- knowledge: capability=dsh-session-hygiene rev=4
     sources=spec/changes/add-dsh-session-title-archive,spec/knowledge/_inbox/done/dsh-session-created-append-gate.md,spec/knowledge/_inbox/done/dsh-tidy-attempt-session-registration.md,spec/knowledge/_inbox/done/dsh-tidy-maintenance-lane-hooks.md -->

fenixd 对 dsh 驱动 agent 会话的自动卫生机制：bundle 侧在会话启动期赋予确定性标题（web 不再显示「未命名」），daemon 侧在 run 终态把该 run 捕获的全部会话归档（web 默认视图不再堆积 headless 会话）——全链路失败安全，不影响 run 主链路。

## 规则

- **标题装配（bundle 侧）**：每个 fenixd 经 dsh 派发的 headless 会话在启动期获得确定性标题，格式 `<工程目录basename> · <worktree目录basename>`（示例 `cloud-phone · impl-code-review-fix-1794159697`），由 spawn env `FENIX_RUN_PROJECT_ROOT` / `FENIX_RUN_WORKTREE` 派生；任一 env 缺席回退另一 key 的 basename，两者全缺不命名（交由 dsh-session-title 内置兜底），任何异常吞掉 WARN，不得使会话启动失败。标题按 UTF-8 字节截断至装配面 `maxTitleBytes`（120）。
- **标题写路径与落盘时机**：标题写入走会话自身 header 写路径（bundle 内 `rename()`，source=user pin 住），同进程自有写路径，不依赖 dsh web 在线；user 源 pin 同时抑制 dsh-base 对 boilerplate 首条消息的 LLM 标题调度。落盘时机受 dsh-session 会话流 append 闸约束（上游闸门语义见 [dsh web 会话组织](dsh-web-session-organization.md)）：`session/created` 同步派发期会话流只读，监听器内同步 rename 必抛 `session "<id>" cannot append before session/created completes`——装配完好下确定性必败，非竞态，rename 必须经 `queueMicrotask` 推迟到派发循环同步结束后落盘。微任务仍先于 headless `run()` 续行与首条消息兜底执行，`source=user` pin 语义不受影响。命名幂等：`session/created` 在 resume 重放路径同样触发，已有标题且来源非 fallback 时不覆盖。
- **headless 失败痕迹与验证纪律**：插件 try/catch + `logger.warn` 的失败安全模式在 headless 车道是静默的——无落盘、stderr 不入日志，吞错缺陷不留下可见痕迹；headless 插件的行为验证只能端到端：真实 spawn 后解剖会话流 `sessions/<dir>/session.v4.jsonl.zstd`（`/usr/bin/zstd -dc` 解压）。标题装配的复验判据：`session/created` 后即落 seq 0 的 `session/title` 记录（`source.kind=user`、标题 `<工程> · <worktree>`），流中零 `title-llm-request`。
- **终态自动归档（daemon 侧）**：`agent.harness: dsh` 且 tidy 开启（缺省开启）时，run 到达终态后，经 dsh web HTTP API 把该 run 捕获的全部 dsh 会话逐个标记归档（通道与凭据规则见 [dsh web 会话组织](dsh-web-session-organization.md)），web 默认视图（Hide archived）不再显示。归档调用不带 `stopActivity`；`workspace/session-active` 按可重试处置。归档幂等：目标会话已归档按成功处理。
- **终态挂接落点全执行面枚举**：任何「终态资源清理/投递」类挂接，落点必须枚举全部执行面而非只见 dispatch 族。终态挂接共三类外口：`_execute_agent` finally（dispatch 族 impl/verify/repair/planner/judge）、dispute-judge/spec-review 直调函数 finally、maintenance_runs 直调车道（`run_administrator` / `run_arbiter`）主 run try finally——三类执行面不经共同终态外口，漏一面即该面 run 终态静默不投递。新增直调车道（同 `run_administrator` 骨架：claim→组装→`_run_agent`→硬门→指标收尾）的主 run try 必须自带终态挂接。维护车道注入的 facade 替身可能缺目标方法，挂接一律 `getattr` 判空静默跳过（logger 判空同款先例）。
- **终态挂接守卫双保险**：覆盖性测试用「端到端替身跑真函数 + AST 源码契约」双保险钉死（对齐 `test_run_agent_call_site_arity.py` 先例）——端到端证行为（成功与异常终态均投递），AST 契约证落点存在（防后续重构拆除挂钩）。
- **会话登记按 attempt 收敛（列表语义）**：同 run 的每次 attempt 各 spawn 独立 dsh 会话，捕获值按 attempt 逐个登记进 base run_id 键下的列表；终态 pop 登记值后全量按序逐 id 投递。登记幂等面：同 id 重复登记不重复入列表；None 尝试不擦既有捕获（尚无捕获时保持 None 哨兵）；存量 str 旧形态读入时并入列表；None/空列表终态走既有「未捕获」WARN 面。列表语义是硬性要求：登记键经 `_normalize_run_id` 把 `-a<n>`/`-r<n>` 后缀剥到 base run_id，凡以 base 键登记 per-attempt 资源，纯赋值必然逐 attempt 覆盖只留末次——多 attempt run 的每份资源都必须走列表/集合语义登记、终态全量消费（一切重试链 run 同面，非 repair 特有，repair 只是高重试率先暴露）。
- **投递通道**：daemon 以子进程调用 Node helper（协议面在 helper 侧，daemon 零帧编解码，复用官方 client SDK）；鉴权凭据经 `--secret-file` 从 `<dsh_home>/.credentials.yaml` 读取。helper 退出码三分类：0 = 成功（含已归档 no-op，队列同 id 条目移除）；2 = 可重试（连接失败/超时/session-active/5xx，子进程自身异常同面入队）；1 = 致命（凭据缺失或形态不符/鉴权被拒/协议错/session-not-found——重试永不成功，不入队直接 WARN）。
- **失败安全**：run 主链路（事件投影、run_metrics、门禁）不依赖归档结果；投递全程持锁串行（并发 1），单次同步等待上界 = helper `--timeout`（缺省 10s）+ 子进程宽限，超时按可重试处置。终态但未捕获 `session_id` 的 run 不投递不入队，WARN 即止（无归档目标，属接受噪音）。非 dsh harness（claude/缺省）零动作。
- **重试队列**：持久化 JSONL `<project_root>/.fenix/dsh_session_tidy/pending.jsonl`，daemon 重启不丢。消费事件驱动（无后台线程）：每次投递先抽干至多 drain_limit 条到期条目再投新会话，daemon 重启后第一次新 run 终态即恢复消费；无新 run 时队列静置（兜底定位而非时效承诺）。backoff 30s 起指数退避封顶 1h；放弃阈值缺省 200 次尝试或 30 天队龄先到为准，触顶移除并 WARN。
- **配置面**：`agent.dsh_web_url`（dsh web 基址，缺省 `http://127.0.0.1:3080`；键缺失回退缺省，显式 null 与非法形态——非 http(s)/缺 host/带路径/query/fragment——加载期校验报错不静默回退，合法值尾斜杠归一）与 `agent.dsh_session_tidy`（总开关，缺省 true；非布尔 fail-open 按缺省 true 并 WARNING 一次）。置 false = daemon 不投递、重试队列暂停消费不清空（恢复开关后继续）；bundle 侧标题装配不受开关影响。两键与 `agent.harness` 同面：分层覆盖、30s 热更新重载即生效、设置页回显与投递消费同函数不脱节。

## 关键行为

- 会话启动（含 resume 重放）：bundle 插件在 `session/created` 读 spawn env → 派生标题 → `queueMicrotask` 推迟 `rename()` 落 header（同步派发期会话流只读，禁止同步写；已有非 fallback 来源标题即跳过）→ 异常吞掉 WARN，不阻塞会话创建。
- run 终态：终态挂接在各执行面 finally 触发（dispatch 族经 `_execute_agent` finally；dispute-judge/spec-review 经各自直调 finally；admin/arbiter 直调车道经主 run try finally）→ 非 dsh harness 或开关关闭即返回；已捕获的全部 `session_id` 逐 id 按序同步投递（持锁串行，先抽干队列到期条目再投新会话）→ 按退出码处置（成功清队列 / 可重试入队 / 致命丢弃 WARN）。
- web 离线：投递失败入持久化队列，后续任一次投递时机补投到期条目；放弃阈值触顶移除并 WARN。

## 代码锚点

- 标题装配插件：`dsh-bundle/src/session-title.ts`；服务挂载与 limits：`dsh-bundle/cordis.patch.yml`
- 归档投递器与重试队列：`core/dsh_session_tidy.py`；归档 helper：`dsh-bundle/src/session-tidy-helper.ts`
- run 终态挂接与键归一/列表登记：`core/agent_runner/runner.py`、`core/agent_runner/maintenance_runs.py`（admin/arbiter 直调车道挂接）；配置读取与校验：`core/config.py`
- 守卫测试：`tests/test_dsh_session_tidy.py`、`dsh-bundle/tests/session-title.test.ts`、`dsh-bundle/tests/session-tidy-helper.test.ts`、`dsh-bundle/tests/auth-probe.test.ts`

## 溯源

- 2026-11-09 add-dsh-session-title-archive（spec/changes/add-dsh-session-title-archive/） — 新建本页：dsh 会话确定性标题（spawn env 派生、120 字节截断、resume 幂等）、run 终态自动归档（Node helper 投递、退出码三分类、事件驱动重试队列与放弃阈值、失败安全边界）、配置键 `agent.dsh_web_url` / `agent.dsh_session_tidy`。
- 2026-11-09 dsh-session-created-append-gate（spec/knowledge/_inbox/done/dsh-session-created-append-gate.md） — 折叠 append 闸结论：标题 rename 必须经 queueMicrotask 推迟到 session/created 同步派发结束落盘（同步写必抛 cannot append、确定性必败非竞态）、微任务先于 run() 续行故 user 源 pin 不受影响、headless 失败安全静默故行为验证只能端到端（zstd 解剖会话流）与复验判据（seq 0 session/title、kind=user、零 title-llm-request）。
- 2026-11-09 dsh-tidy-attempt-session-registration（spec/knowledge/_inbox/done/dsh-tidy-attempt-session-registration.md） — 折叠多 attempt 漏归档结论：spawn 期会话捕获按 attempt 列表登记进 base run_id 键（纯赋值逐 attempt 覆盖只留末次，`-a<n>/-r<n>` 剥后缀键归一是覆盖根因），终态全量按序逐 id 投递（同 id 幂等、None 不擦既有捕获、str 旧形态并入、None/空列表走未捕获 WARN 面）；一切重试链 run 同面，非 repair 特有。
- 2026-11-09 dsh-tidy-maintenance-lane-hooks（spec/knowledge/_inbox/done/dsh-tidy-maintenance-lane-hooks.md） — 折叠 maintenance_runs 漏挂结论：终态挂接落点必须枚举全部执行面（`_execute_agent` finally / dispute-judge、spec-review 直调 finally / maintenance_runs admin、arbiter 直调车道主 run try finally），新增直调车道主 run try 必须自带终态挂接，facade 替身缺方法 `getattr` 判空静默跳过，守卫测试「端到端替身 + AST 源码契约」双保险。起因 cloud-phone web 未分组 6 条存量漏归档（admin×4、arbiter×2），两车道补挂接后 TDD 先红后绿、关联 7 套件 169 passed。
