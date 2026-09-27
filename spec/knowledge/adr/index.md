# ADR 索引

跨 SPEC 架构级决策记录。每行一条：编号链接、状态、一句话摘要；
superseded 条目保留在列供溯源。编号接续本目录既有最大号。

| 编号 | 状态 | 摘要 |
| --- | --- | --- |
| [ADR-001](ADR-001-agent-run-jsonl-protocol.md) | accepted | Agent 运行产物以 stream-json 逐行落盘 `.fenix/runs/<run_id>.jsonl`，终态行协议保证文件任何时刻可解析 |
| [ADR-002](ADR-002-model-routing-env-plus-official-model.md) | accepted | 模型路由：进程 env 承载真实 baseurl/key/model，`--model` 恒取官方名（`sdk_model`）只过 SDK 校验 |
| [ADR-003](ADR-003-agent-lane-claude-config-dir-isolation.md) | accepted | 配置了 provider 的 agent 车道必须以 `CLAUDE_CONFIG_DIR` 隔离启动，凭据走进程 env 不落盘 |
| [ADR-004](ADR-004-provider-failover-attempt-boundary.md) | accepted | provider 候选链的失效转移只在 attempt 边界推进，切换类错误驱动、4xx 维持熔断、跨 provider resume 零损上下文 |
| [ADR-005](ADR-005-strict-priority-tiered-parallel-scheduling.md) | accepted | 调度为严格优先级分档并行：同档并行至 `max_concurrent`，跨档不并行、不抢占 |
| [ADR-006](ADR-006-config-tiered-deep-merge.md) | accepted | 配置分级：用户级 `~/.fenix/config.yaml` 与项目级深度合并，项目级优先、list 整体替换、缺省键兜底 |
| [ADR-007](ADR-007-multi-project-discovery.md) | accepted | 多项目发现 = 显式注册 + 目录扫描兜底（未配置扫 `~` 一级），项目识别判据仅 `STATE.md` |
| [ADR-008](ADR-008-dashboard-zero-dependency-stack.md) | accepted | Dashboard 固定零新增依赖栈：stdlib http.server + 无构建原生前端 + vendored marked |
| [ADR-009](ADR-009-dashboard-file-endpoint-security-model.md) | accepted | Dashboard 文件读取端点统一安全模型：白名单 + kebab 校验 + resolve 后目录前缀校验，缺失返回 `found:false` |
| [ADR-010](ADR-010-dashboard-writes-via-state-machine.md) | accepted | Dashboard 对状态/配置的写回一律复用既有写入口（flock 序列化 + 原子 rename），并发为最后写者胜 |
| [ADR-011](ADR-011-auto-approve-driven-by-daemon.md) | accepted | auto 审批模式由 daemon 在 done 后执行 push 并标记 pushed；默认 manual，失败保留 done 人工兜底 |
| [ADR-012](ADR-012-admin-zero-llm-monitor-and-main-tree.md) | accepted | 自愈监视零 LLM 成本（规则检测），仅困境时唤起 Administrator；其处置直接落 main 树 |
| [ADR-013](ADR-013-task-writeback-and-completion-gate-at-transitions.md) | accepted | 任务进度回写（只增不减）与完成度门禁挂在 pm_engine 的 run 终态/状态转换点，不在 agent_runner |
| [ADR-014](ADR-014-unattended-retry-safety.md) | accepted | 无人值守重试安全：错误指纹熔断、主树脏走 stash 不 commit、daemon 单实例 flock、max_turns/续跑/孤儿清理 |
| [ADR-015](ADR-015-graceful-shutdown-drain-and-interrupted-mark.md) | superseded | 优雅退出秒级排水（SIGTERM 全部→interrupted 标记→≤10s→SIGKILL），不扩展 supervisor 窗口（已随 ADR-063 规划性重启排水退役） |
| [ADR-016](ADR-016-dispatch-selfheal-discipline.md) | accepted | 调度自愈纪律：状态机纯记录直调补发、重发幂等不清历史字段、孤儿判定白名单、单条异常不中止整轮 |
| [ADR-017](ADR-017-fake-success-defense-fail-closed-promotion.md) | accepted | 假成功防御：rc==0 须校验 result 终态；晋级关 fail-closed、推送关 fail-open；VERIFIED→TESTING 仅限自动回退 |
| [ADR-018](ADR-018-push-main-first-sha-idempotent.md) | accepted | pushed 终态以远端内容（SHA）为准：main 先行为成功判据、分支仅审计留痕，ls-remote 去重幂等、失败有界退避超限升级人工 |
| [ADR-019](ADR-019-repair-channel-dedup-family-cap.md) | superseded | 同根缺陷双修复通道（重实现/派生子 fix）先到先得，重置/spawn/派发三边界守卫互斥；族谱深度宽度硬上限越界转人工（已随 ADR-034 原地打回退役） |
| [ADR-020](ADR-020-provider-4xx-circuit-breaker.md) | accepted | provider 4xx 熔断：判据只认解析出的状态码、状态进程内存不落盘，熔断期不动状态机不增重试计数 |
| [ADR-021](ADR-021-mergeback-conflict-selfheal-keep-merge-result.md) | accepted | merge-back 冲突自愈保 merge 结果：pop 冲突 checkout HEAD 弃 stash 版本、untracked 按分支新增路径交集移开备份，不一致副本不静默丢弃 |
| [ADR-022](ADR-022-watchdog-thresholds-derived-single-source.md) | accepted | 看门狗阈值单源派生：恢复阈值=run_timeout+固定宽限，成对时间阈值一律派生自锚点旋钮不设独立键，绝对上限联动校验 |
| [ADR-023](ADR-023-worktree-isolation-cwd-seeding-mergeback.md) | accepted | 实现车道 worktree 隔离三要素：子进程 cwd 锚定 worktree（写读同层）、SPEC 播种分支自包含、成功后框架 merge-back 回主树 |
| [ADR-024](ADR-024-agent-dispatch-thread-per-run.md) | accepted | agent 派发线程化：每运行一 worker 线程、派发即返不阻塞事件循环，max_concurrent 以计数守卫落实 |
| [ADR-025](ADR-025-run-timeout-liveness-supervision.md) | accepted | 运行时限活性监督：零事件直判停滞、有活动才问 LLM（复用 fallback 路由），续期同步顺延 stuck 基准，锁与存活唯一真相是进程表 |
| [ADR-026](ADR-026-resume-via-progress-injection-not-environment.md) | accepted | 断点续跑以进度数据注入实现，跨 attempt 不复用运行环境；与 attempt 内 --resume 续跑分属不同机制 |
| [ADR-027](ADR-027-verify-failure-deterministic-triage.md) | accepted | 验证失败分流用确定性规则：环境性失联探针后置分类、噪音/缺陷按「断言从未执行」分流，不进 prompt 不用 LLM，噪音走告警不自动改场景 |
| [ADR-028](ADR-028-verify-report-synthesis-fallback.md) | accepted | 人读验证报告缺失时由结构化数据确定性合成兜底：agent 报告优先、兜底不覆盖不静默（必发告警）、合成器单一共享实现 |
| [ADR-029](ADR-029-spec-toolchain-native-selfcontained.md) | accepted | SPEC 工具链原生自包含：原生 Python 重实现移除 npm CLI，schema vendored 随库分发，changes 目录布局契约不变 |
| [ADR-030](ADR-030-dashboard-control-plane-file-signals.md) | accepted | dashboard 控制面以文件信号驱动 daemon：server 不直接派发 agent，请求落盘由 daemon 轮询拾取，信号文件即互斥且崩溃安全 |
| [ADR-031](ADR-031-dashboard-project-lifecycle-tmux-softdelete.md) | accepted | 项目运维：daemon 启停走 tmux 会话（优雅信号优先、kill 兜底、启动幂等），软删除=ignored 忽略列表（忽略优先于显式注册） |
| [ADR-032](ADR-032-failover-chain-element-model-mapping.md) | accepted | failover 链元素级模型映射：元素 str|{provider,model} 三级解析回退、角色级 model 可选，校验改「每元素可解析」，保存整体替换防覆写 |
| [ADR-033](ADR-033-v2-frontend-vendored-amis-sdk.md) | accepted | v2 前端栈=vendored AMIS SDK+JSON DSL 页面：tarball 提取无构建链、页面 JSON 深合并单页缺失可跳过；修订 ADR-008 前端形态，其零构建/vendored 原则延续 |
| [ADR-034](ADR-034-inplace-bug-repair-no-derivation.md) | superseded | bug 修复原地打回：重置 implementing 在原 SPEC 内修复，不再派生 fix-* 子 SPEC；3 轮连续失败升级人工，通道去重/族谱治理随派生退役（推翻 ADR-019）（已随 ADR-075 修订：缺省原地、派生可选） |
| [ADR-035](ADR-035-repair-convergence-dual-counter-budget.md) | accepted | 修复收敛双计数器：验证失败轮数只在 PASS 归零（连续性），实现 run 总预算派发时递增、重派决策处设卡耗尽 blocked（总量），沉没成本放行跑完 |
| [ADR-036](ADR-036-deliverable-gate-before-merge-typed-extractor.md) | accepted | 交付物守卫 merge 前零 LLM 校验声明路径存在，提取器语境分类 deliverables/references，无法判定保守归硬校验（宁误拦不漏放），引用缺失仅审计 |
| [ADR-037](ADR-037-worktree-test-server-reverse-proxy.md) | accepted | 页面验证服务=worktree 静态资源+API/SSE 反代主服务：打真后端不跑第二实例，框架管启停注入 V2_BASE_URL，端口高位段确定性分配 |
| [ADR-038](ADR-038-v2-shell-level-sse-broadcast-bridge.md) | accepted | v2 事件架构：SSE 桥挂壳级转 sse:<type> broadcast、页面 onEvent 重拉（500ms 前缘节流）；增量数据流（run_events）自管 EventSource 快照先行 |
| [ADR-039](ADR-039-v2-adapter-pure-function-data-layer.md) | accepted | v2 数据分层：Adapters 纯函数层（UMD 双出口）是字段逻辑唯一收口，计数 Number 归一+三级回退，页面 JSON 不做字段逻辑 |
| [ADR-040](ADR-040-recovery-legacy-file-salvage-no-session-resume.md) | accepted | 死亡恢复=文件级遗产收编：worktree_manager 注册遗产获清扫豁免、prompt 注入快照、agent 只读复制进自己 worktree；跨派发会话续跑不可行不做 |
| [ADR-041](ADR-041-verify-scenario-set-freeze.md) | accepted | 验证场景集跨轮冻结：scenarios.json 持久化，修复轮只增不减、删减须理由，确定性校验器补齐不可绕过，既有场景每轮全量重跑 |
| [ADR-042](ADR-042-verdict-classification-evidence-enforced-checker.md) | accepted | 裁决强制分类+证据结构化：非 PASS 四选一并附证据，分类-状态映射采纳处强制重写，warning 连续 2 轮升级；确定性校验器把关 LLM 产物 |
| [ADR-043](ADR-043-alert-auto-resolve-condition-whitelist.md) | accepted | 告警自动闭环：写入埋 trigger、判定挂既有周期扫描，condition 白名单未识别永不闭环，人工记录不可覆盖，存量首启一次推断回填 |
| [ADR-044](ADR-044-token-accounting-at-completion-budget-alert-only.md) | accepted | token 计量收工单点采集进 STATE 内部字段（jsonl 留审计），验证链增量走侧车；预算线 80%/100% 幂等告警只告警不冻结，存量不回填 |
| [ADR-045](ADR-045-core-componentization-facade-boundaries.md) | accepted | core 巨文件组件化：组合提取+门面、组件只许单向回引门面、锁与状态同迁；测试直调组件、门面只留有生产调用者的方法 |
| [ADR-046](ADR-046-interaction-contract-prevalidation-per-assert-triage.md) | accepted | 交互契约前置校验（声明式可交互候选须有场景或展示声明）+ 豁免逐断言归因：全断言非 product-bug 才豁免，断言级豁免清单可复核 |
| [ADR-047](ADR-047-budget-counter-atomic-primitive-death-refund.md) | accepted | 预算计数单点+补偿回退：死亡 run 豁免在死亡判定点回退而非启动处预判，读改写收敛到 state_machine 锁内原子原语 |
| [ADR-048](ADR-048-admin-lane-threadpool-per-run-disposition-files.md) | accepted | admin 处置并发模型：主循环只拾取投递、线程池后台执行、处置文件按 run_id 实例分离；主循环信号拾取不得同步执行长任务 |
| [ADR-049](ADR-049-agent-prompt-files-single-source-of-truth.md) | accepted | agent 提示词文件为唯一真相（无内置副本、占位符替换、动态段归代码）；项目附加层末尾注入、缺席零注入、软链布局级防护 |
| [ADR-050](ADR-050-dashboard-incremental-data-pipeline.md) | accepted | dashboard 数据面增量化：摘要索引+签名增量重算、广播只带变更条目、前端本地归并 30s 心跳校准、连接/线程硬上限 503 |
| [ADR-051](ADR-051-signature-key-natural-invalidation-dir-level-polling.md) | accepted | 变更检测纪律：读缓存键=(路径,mtime,size) 依赖写后自然失效不维护写侧钩子；watcher 目录级签名两级跳层替代 inotify 保零依赖 |
| [ADR-052](ADR-052-state-md-field-whitelist-terminal-snapshot.md) | accepted | STATE.md 新字段必入序列化白名单；终态统计量在终态转换点快照进 STATE，读取仅终态采用持久值、脏值回退实时路径 |
| [ADR-053](ADR-053-fast-track-single-run-lane-mode-in-spec-yaml.md) | accepted | fast-track：单 run 全包四段守卫保留，mode 存 `.spec.yaml` 缺省 full fail-closed；超预算升级保分支置 implemented 不重跑；判定靠确定性硬校验兜底 |
| [ADR-054](ADR-054-mergeback-conflict-repair-branch-side-merge-main.md) | accepted | merge-back 语义冲突原地修复：git 层判定/调度层决策，repair 在分支侧合 main、主树恒干净不冻结，三态判定只信 git 事实，熔断计数不被 repair 清零 |
| [ADR-055](ADR-055-llm-via-claude-cli-no-native-client.md) | accepted | 框架不实现独立 LLM 客户端：交互场景由执行会话完成、后台场景统一 headless claude -p（参数列表传参、超时有界、失败不改原值） |
| [ADR-056](ADR-056-archive-visibility-dir-existence-periodic-governance.md) | accepted | 归档判定唯一事实源=活跃目录存在性（不写 STATE 标志）；按条目枚举 changes 必须容忍目录缺失；低频治理挂主循环周期计时而非事件埋点 |
| [ADR-057](ADR-057-task-progress-subject-contract-read-side-fallback.md) | accepted | 任务进度协议：一个任务=一个 TaskCreate=一次汇报=一次勾选（subject 内嵌编号为契约）；读侧兜底链不依赖编号（创建序回退带弱一致性门槛） |
| [ADR-058](ADR-058-dispatch-single-flight-inflight-state-protection.md) | accepted | 派发单飞守卫（异步操作前置位查重）+ 在飞态保护：失败回写不降级活跃验证态，verifier 结果竞态下重放合法路径或 blocked 留证，绝不静默丢弃 |
| [ADR-059](ADR-059-runs-append-only-single-archival-entry.md) | accepted | runs 顶层产物只增不减，离开顶层唯一入口=spec 归档（推断单一实现+搬移 fail-open）；容量治理须带审计重新立项 |
| [ADR-060](ADR-060-framework-artifact-commit-points.md) | accepted | 框架产物入库时机：归档残留挂 push 尾部批量收口（pathspec 限定、失败降级不阻塞终态）；须立即被 worktree agent 看见的产物在写入点即时 commit+push |
| [ADR-061](ADR-061-rapid-death-judged-by-process-lifetime.md) | accepted | run 瞬时死亡判定以进程存活时长为准不解析退出码，框架主动 SIGTERM 不计入；连续秒挂冷却后自动恢复 |
| [ADR-062](ADR-062-cooperative-cancellation-owner-thread-hold-state.md) | accepted | 人工取消=属主线程协作式终止（旗标+专用异常绕开重试/退避/provider 切换），取消不做状态转换（hold-state），自动链路无权取消 |
| [ADR-063](ADR-063-planned-restart-drain-and-preserve-resume.md) | accepted | 停机分规划性（restart_request 在册→排水 shutdown_drain_seconds、supervisor 联动 +120s）与非计划（快速 terminate）两档；恢复按 git 事实保全分支续做（推翻 ADR-015 恒快速排水） |
| [ADR-064](ADR-064-merge-tree-rehearsal-gate-direct-repair.md) | accepted | merge-back 语义冲突只读预演拦截（merge-tree 于 stash 前），命中直通 repair 不烧熔断记账不降级；remerge 真失败熔断不动 |
| [ADR-065](ADR-065-verify-serving-instance-lifecycle-discipline.md) | accepted | 被测实例按 run 生命周期管理不常驻复用：进程组 spawn/killpg、ppid 自灭、作用域 try/finally 收割+周期清扫+登记制；端口耗尽用临时端口绝不回退主树实例 |
| [ADR-066](ADR-066-fasttrack-read-side-fallback-synthesis.md) | accepted | fast-track/full 双模式产物差异由读侧回退合成吸收：写入端契约不动、专属副本优先+spec 守卫、口径同源；新增消费点必须接入回退链 |
| [ADR-067](ADR-067-periodic-lane-attach-inspection-loop.md) | accepted | 周期自主车道：调度挂既有巡检循环不新增定时器、状态走 .fenix sidecar 不进 STATE.md、独立 run 类型不占 spec 预算、失败降级告警当日不重试、产物写入即入库 |
| [ADR-068](ADR-068-local-cost-computation-per-provider-billing.md) | accepted | 成本金额只认本地计算：读侧解析 run 产物 usage+实际生效 marker 现算零新持久化，价格内嵌 providers[i].billing per-provider 谓词，四价齐备否则整体不可计价 |
| [ADR-069](ADR-069-route-map-declared-generator-protocol.md) | accepted | 框架不解析被测应用源码：路由地图由项目声明生成器协议接入（固定路径/单参/Markdown stdout/超时 fail-open），来源=impl worktree、复用键=HEAD，覆盖缺口靠措辞防线 |
| [ADR-070](ADR-070-config-validation-tolerance-classification.md) | accepted | 配置校验按缺陷性质分类：键集不匹配逐键降级（保留键+内嵌重启处方+进程生命周期去重），值/类型非法整段拒绝、启动 FATAL |
| [ADR-071](ADR-071-daemon-self-monitoring-signal-semantics.md) | accepted | daemon 自检信号：错误升级按时间窗+归一化指纹（无状态重算、fail-closed），代码陈旧用 mtime 指纹（不用 git hash/schema 版本），阈值模块常量不进配置 |
| [ADR-072](ADR-072-content-assets-served-by-backend-dynamic-read.md) | accepted | 内容型资产由后端端点动态读盘伺服不进前端 dist（白名单+realpath 防穿越），重依赖渲染库动态加载；内容与代码演进边界确立 |
| [ADR-073](ADR-073-state-events-published-at-eventbus-diff.md) | accepted | SPEC 状态事件发布点收口 EventBus 状态 diff（唯一全局观察者覆盖跨进程写入），消费者禁入 state_machine 回调；2s 延迟与跳变合并为接受代价，动作线程池执行不阻塞状态机 |
| [ADR-074](ADR-074-runtime-mutable-values-never-versioned.md) | accepted | 运行时可变值不落版本库：调度门控字段存 STATE.md entry、订阅配置存 .fenix/config.yaml，spec 目录只承载版本化文档；.spec.yaml 仅放创建期声明 |
| [ADR-075](ADR-075-bug-repair-mode-configurable-prefix-retired.md) | accepted | bug 修复方式由 admin.bug_repair_mode 配置（inplace 缺省/derive），名称前缀分流退役；切换实时生效、在飞链自然终态不迁移（推翻 ADR-034 一律原地口径，派生治理随 derive 模式长期保留） |
| [ADR-076](ADR-076-llm-verdict-run-dispatch-daemon-mechanical-execution.md) | accepted | LLM 裁决以轻量单轮 agent run 派发（复用路由/记账/超时），judge 只读只产裁决 JSON，daemon 机械执行+重跑守卫；修正声明≠放行缺件，审计留痕可回滚 |
| [ADR-077](ADR-077-verify-runner-plugin-architecture.md) | accepted | 验证引擎 Runner 插件化：调度器不认识 kind、场景级 kind 混排、断言结果恒为 pass/layer 字段 dict 下游零分支、契约形态按场景集反推零新增字段；新形态只加 Runner |
| [ADR-078](ADR-078-dangling-run-terminal-state-sweep-startup-and-runtime.md) | accepted | 悬空 run 终态补写双兜底：启动清扫（派发前全扫）+ 运行期三重判据（不在注册表∧mtime 停更≥1800s∧尾部无终态）周期扫；interrupted 补写 reason 区分来源，线程级 except 兜底归因 re-raise |
| [ADR-079](ADR-079-deterministic-undeclarable-soften-before-llm-judge.md) | accepted | 确定性不可交付声明（gitignored/仓库外/dist/.fenix）在 LLM/人工介入前机械软化 kind→reference：晋升期软化先于 lint、守卫期预分类免 judge，全程审计留痕，LLM 终审只接语义矛盾 |
| [ADR-080](ADR-080-verify-contract-signal-routed-autodraft-selfcert-gate.md) | accepted | 验证契约缺失不打回 plan：信号化唤起 Administrator 自主起草，草稿须过机械三段自证才落位；有效契约一律不碰、人类 UI 显式授权（overwrite 标记）方可越过 |
| [ADR-081](ADR-081-provider-transient-inplace-backoff-before-chain-advance.md) | accepted | provider 瞬断原地退避优先换链：attempt 内子重试 r{n} 续 --resume、worktree 全类型保留+transient keep_for_reuse、dispatch 排程等待重派、全局错误指纹熔断；归因判定只看原始信号不读降噪文本 |
| [ADR-082](ADR-082-gate-evidence-per-spec-addressed-persistence.md) | accepted | 门禁证据 per-spec 寻址持久化（verify-progress/<spec>/impl-result.json 原子快照）：共享 run-result 降级为兼容兜底，证据缺失 fail-closed 拦截，恢复巡检尊重门禁结论、re-trigger 作人工修复心跳 |
| [ADR-083](ADR-083-drafted-promotion-single-choke-point-shared-core.md) | accepted | drafted 晋升门控单点化（manual 等待不写 error），晋升核心共享函数供 daemon/dashboard/CLI 三通道复用；transition 收尾留调用方，CLI 人工子命令独立入口不挂 daemon 主程序 |
| [ADR-084](ADR-084-contract-agent-artifact-hard-gate-retry-budget-split.md) | accepted | 产物契约型 agent（planner-judge/plan）成功判定加产物硬门：exit 0 但产物缺失/不可解析判失败走瞬态重试，产物不合规走裁决重试，两类预算分离；judge 逐场景 checkpoint 先落盘再深入 |
| [ADR-085](ADR-085-worktree-verify-progress-copyback-per-file-mtime-guard.md) | accepted | worktree 产物拷回收口于 runner 成功收口点（覆盖全部 agent 类型），逐文件 copy2+mtime 三态守卫防陈旧回灌，fail-open 留痕、失败路径不拷回 |
| [ADR-086](ADR-086-cancel-hold-state-persistent-recovery-monitor-exempt.md) | accepted | 人工取消保持态随 STATE 持久（`_cancelled_hold`），重启恢复与自动监测豁免、不覆盖人工决策，仅显式 status 复位解锁；存量不迁移 |
| [ADR-087](ADR-087-autostash-drop-criterion-tree-diff-sha-pinned.md) | accepted | autostash 删除判据=树级 diff 全同+sha 钉住+栈顶核对，含独有内容必保留并附找回命令；冲突事件留痕可处置、WIP 重叠只读预警不阻断 |
| [ADR-088](ADR-088-verify-scenario-root-separated-from-project-root.md) | accepted | 验证执行根与簿记根分离：scenario_root 承载 cli 场景 cwd 与 seed 写入（物理隔离进 serving worktree），project_root 保留簿记路径不动 |
| [ADR-089](ADR-089-wip-checkpoint-silent-window-collapse-before-mergeback.md) | accepted | WIP 检查点只在框架可证明静默窗口提交（排水进程死绝后/瞬断退避 sleep 前，无条件下生效），merge-back 前 soft-reset 塌缩 `fenix(wip):` 提交保主树历史零污染 |
| [ADR-090](ADR-090-scenario-defect-only-reroute-to-judge-repair.md) | accepted | 纯场景缺陷（product-bug=0）改道门定向重派 judge 走 scenario-repaired 通道，实现轮预算不修场景；静态扫描只产情报 fail-open，与修复重入共用预算 |
| [ADR-091](ADR-091-per-spec-budget-override-resolution-priority.md) | accepted | 实现预算解析优先级 per-spec 覆盖>全局 config>缺省、夹紧 1-10 单点纯函数共享，dashboard 读侧引用同源实现不重复解析，null=清除回退全局 |
| [ADR-092](ADR-092-attribution-grading-framework-computed-screenshot-algorithmic-label.md) | accepted | 归因分级由框架机械计算（非 judge 自报）+截图健康算法标签+基线防污染+批量归因查重（≥3 逐字同拒落盘），inconclusive 达阈值必唤起 admin |
| [ADR-093](ADR-093-scenario-set-write-gate-same-source-validation.md) | accepted | 场景集写入端全量过同源结构校验，坏条目剔除继续不整批拒绝、备份全合法才更新、加载净化只动内存；未消费反馈不再自动重跑改分级升级 |
| [ADR-094](ADR-094-verdict-artifact-fail-closed-copyback-before-gate.md) | accepted | 裁决产物 fail-closed：拷回前置+硬门 mtime 新鲜度下界+白名单单源，不可读任何路径不得等价 verified，三阶段重试一次后 blocked、legacy 直接 blocked |
| [ADR-095](ADR-095-verdict-dispatch-yield-zero-write-fail-history-sidecar.md) | accepted | 裁决重试 frozen/cancelled 让位零写入（不触状态机不发告警），失败 cause 结构化分型+fail_history 侧车 diff 识别无进展循环，只有真二次违规产出告警 |
| [ADR-096](ADR-096-control-signal-machine-semantics-typed-bifurcation-dedup.md) | accepted | 控制信号机器语义走独立 signal_type 不依赖 evidence 字段（四处注册点同步），同项目同型未处置信号在途去重，前端 ref 同步锁防双击穿透 |
| [ADR-097](ADR-097-plan-artifact-single-status-whitelist-degrade-annotation.md) | accepted | plan 产物硬门合法终态单值白名单（只认 plan-ready）+校验路径与读侧同源+归因携带真实 status，降级事实落盘持久化并渲染标注，新流程成功时清旧标注 |
| [ADR-098](ADR-098-run-artifact-terminal-postlude-invariant-stale-reclass.md) | accepted | run 产物终态后置不变量：弃置前必补写 superseded 终态行（紧跟 transient_retry）；读侧 mtime 1800s 改判 stale 挡活跃计数，存量免清扫自愈不清洗 |
| [ADR-099](ADR-099-impl-terminal-nocommit-gate-pre-rmtree-reference-snapshot.md) | accepted | implementer 正常终态+分支零提交+dirty 在 cleanup 前拦截走 WIP 提交+退避+resume 续做，机械归因零 LLM，rmtree 前引用式 stash create 快照留档 |
| [ADR-100](ADR-100-approve-push-file-signal-liveness-precheck-no-retry.md) | accepted | 有状态写操作禁 dashboard 双轨直执行：跨进程走文件信号+写前探活 409+消费不重试（各失败源有既有兜底）+payload 极简防漂移 |
| [ADR-101](ADR-101-spec-content-integrity-gate-at-dispatch.md) | accepted | 空 SPEC 内容完整性闸门挂派发前（预算闸门同层）：实质四选一宽松判定、闸门自身 IO 异常放行、命中 blocked+告警注册解除条件自动闭环 |
| [ADR-102](ADR-102-tasksmd-relint-before-merge-branch-side-fail-open.md) | accepted | tasks.md 损伤 merge 前两车道机械复检（full=分支 HEAD 基准、fast-track=worktree 文件），显示层 lint fail-open 宁漏勿拦、解析计数单源纯函数 |
| [ADR-103](ADR-103-turn-limit-liveness-renewal-forced-kill-wip-salvage.md) | accepted | turn-limit 命中按封闭矩阵活性续期（分支新提交或 tool_result 流量任一即活性、步长 25% 封顶 2 次），强杀收口在可证明静默后接 WIP 保全、消耗记 unobserved 不记零 |
| [ADR-104](ADR-104-verdict-dedup-rejection-resynthesis-loop.md) | accepted | 裁决查重拒绝必有出口回路：违规落盘→定向重合成（复用轻量 judge 通道）→同入口全链再校验→有界升级；按场景子集回炉、全量重复仍升级、级联豁免防误拦 |
| [ADR-105](ADR-105-inplace-retry-spec-state-recheck-before-redispatch.md) | accepted | 原地重试子循环退避后重派前必须复查 spec 预期态与冻结/取消旗标，非预期态语义化放弃，复查自身异常 fail-open，与 attempt 层 give-up 检查同源 |
| [ADR-106](ADR-106-visual-baseline-pass-gate-never-auto-rebuild.md) | accepted | 视觉基线固化过健全性+场景通过性双门（未过顺延 baseline_deferred 非打回），截图前动画静置+限次重拍择优，污染只标记告警、框架永不自动重建基线 |
| [ADR-107](ADR-107-blocked-to-testing-reverify-gate-lane.md) | accepted | blocked→testing 重验直通道走 GATE_TRANSITIONS 逃生门（守卫=非冻结+分支已合并 git 事实、异常回退 ready），复位挂 admin 处置收尾，阻塞轮数生命周期累计第 2 次必冻结 |
| [ADR-108](ADR-108-self-evolution-daemon-hosted-gitignored-draft-staging.md) | accepted | 自进化车道 daemon 宿主+同进程状态机注册（不新增第三条文件信号）、草稿 gitignored 暂存接受时先提交后注册零残留、LLM 只读复核、落盘/lint/注册全在确定性代码 |
| [ADR-109](ADR-109-stale-code-selfheal-daemon-builtin-circuit-breaker.md) | accepted | 代码陈旧自愈 daemon 内建闭环（30s mtime 持续状态+内部双源空闲判定+空闲重启），外部 when-idle 脚本退役；未托管不自愈、启动熔断 60s/3 次人工清标 |
| [ADR-110](ADR-110-verify-env-deterministic-failfast-before-scenarios.md) | accepted | 确定性验证环境错误场景执行前 fail-fast：预检只拦确定形态零误杀、不可达短路场景数=0 走既有升级通道不产报告、mtime 快照门自证、user_blocked 守卫保留 |
| [ADR-111](ADR-111-dashboard-four-layer-fault-isolation.md) | accepted | dashboard 四层故障隔离：探测按 errno 分流（ENOENT 静默/EIO 告警）、ignored 前置于探测、发现跳过+日志、聚合 per-project error、缓存保留旧值推进时间戳、前端保留 stale 数据 |
| [ADR-112](ADR-112-dispatch-wakeup-event-source-not-scan-frequency.md) | accepted | 调度空隙用事件源补齐不提频扫描：接受态转换定向反查 dependents（不建索引）、重评同源判据、派发走既有入口继承全部闸门、观察项判据收紧先自愈后升级 |
| [ADR-113](ADR-113-fasttrack-death-bifurcation-branch-commits-stamp-failclosed.md) | accepted | fast-track 死亡路径按分支提交分流（有提交 merge+升级完整模式补验证、禁合成 verdict），共享结果文件 stamp 守卫 fail-closed、消费后在快照落盘单点删除 |
| [ADR-114](ADR-114-preserve-chain-git-fact-fallback-predelete-snapshot.md) | accepted | 保全链 branch/worktree 以 git 事实回落（不信内存表、STATE branch 只终态写、前缀歧义按不可用），dirty 快照改删除前置动作覆盖全部删除路径，保护集宁多保不删 |
