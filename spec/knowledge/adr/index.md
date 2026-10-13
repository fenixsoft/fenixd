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
| [ADR-055](ADR-055-llm-via-claude-cli-no-native-client.md) | superseded | 框架不实现独立 LLM 客户端：交互场景由执行会话完成、后台场景统一 headless claude -p（参数列表传参、超时有界、失败不改原值）；已被 ADR-271（可插拔 harness）取代其 headless 措辞，不实现独立客户端纪律延续 |
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
| [ADR-115](ADR-115-daemon-supervisor-hosting-chain-three-state.md) | accepted | daemon 托管链拓扑：supervisor 父进程+tmux 仅脱离终端（取代 ADR-031 的 tmux 直启，软删除裁定保留），项目根解析禁软链跟随、托管态三态 managed/unmanaged/stopped 一等可见，消费方写信号前探活升级为托管态闸 |
| [ADR-116](ADR-116-spec-review-gate-reviewing-state-judge-paradigm.md) | accepted | 方案级评审门挂 drafted→ready 间：显式 reviewing 状态不靠字段子状态、默认全量+白名单跳过（evo- 硬否决）、判官范式主树直跑、越界检测式校验不自动回滚、评审失败 fail-closed 且 rejected/incomplete 前缀分流 |
| [ADR-117](ADR-117-deliverable-delete-kind-hard-contract-soften-exempt.md) | accepted | delete 交付物 kind 一等硬契约：gitignored 路径 delete 晋升 lint 直接拒（恒假校验立项当下暴露）、守卫返回结构化条目携带 kind、delete 排除出全部机械软化路径升级人工不自动降级 |
| [ADR-118](ADR-118-impl-progress-contract-carrier-matches-route-tools.md) | accepted | 实现进度契约载体=结果文件结构化字段（completed_tasks/unfinished/partial），按路由 init.tools 能力条件生效缺工具 fail-open+审计，partial 消耗实现预算且归因禁空壳，硬门失败原地续做不废轮 |
| [ADR-119](ADR-119-hang-governance-bounded-execution-over-transcript-heuristics.md) | accepted | 挂起治理：活性快照分离实质事件与心跳（心跳不计进展）、短路只认可观测零产出三条件、禁纯转录重复度判据（实测不判别），主防线是有界全量套件入口（硬超时+faulthandler+基线归类）与并发隔离 |
| [ADR-120](ADR-120-death-run-budget-refund-infrastructure-death-only.md) | accepted | 死亡 run 预算豁免仅限基础设施性死亡（interrupted/网关链路耗尽），监督超时与停滞击杀跑满预算不豁免（细分 ADR-047 豁免面），跨 attempt 继承结构化诊断且清 error 不连带清诊断 |
| [ADR-121](ADR-121-blocked-bifurcation-leverage-criterion-paired-freeze-alert.md) | accepted | blocked 二分类判据=admin 有无可操作杠杆（冻结转人工 vs 阻塞待 admin），冻结必经单一成对入口一次写入 frozen+规范前缀+人工升级告警，结构性消除静默冻结 |
| [ADR-122](ADR-122-pending-merge-window-terminal-anchor-git-fact-criterion.md) | accepted | 已实现未合并窗口：branch 锚点随 run 终态成功落盘（语义=本轮实现分支、禁平行字段），待合并活性以 git 未并入提交为据（禁分支存在性恒真判据、全等归属禁前缀 glob、豁免有界回落防洗白），停机保护集由状态驱动不由事件可见性驱动 |
| [ADR-123](ADR-123-verdict-single-read-entry-shared-result-role-stamp.md) | accepted | 验证裁决单源读取：共享结果文件唯一写入点按 agent_type 注入 role/spec 戳，裁决读先验戳不依赖 run_id 可解析、role≠verifier 记 dispute 不当裁决，丢弃仅限裁决读路径 |
| [ADR-124](ADR-124-run-transcript-toolresult-recognition-single-source.md) | accepted | run 流转录 tool_result 识别单一真源（真实形态=user 事件包裹 block，顶层仅兼容），全部消费点共用判定函数禁各自假设，解析失明自检 WARNING 不入人工告警，外部格式解析必配真实形态夹具 |
| [ADR-125](ADR-125-control-plane-silent-failure-ast-guard-exception-tiering.md) | accepted | 控制平面静默失效防线：AST 静态守卫（唯一签名+无变长参数才比对、候选集下限自检）不靠运行时断言不引重型类型检查，复位路径编程错误签名升级告警携调用点栈帧、运维异常保持 WARNING，悬置探测独立短阈值不改 stuck 语义 |
| [ADR-126](ADR-126-run-verdict-artifact-first-over-exit-code.md) | accepted | run 判定产物优先：进程退出码不等于裁决，失败分支先验结果产物已落盘合法（白名单+派发锚点 mtime+spec 戳）即消费不重派，failed/戳不符视为不可信保守重试 |
| [ADR-127](ADR-127-failure-classification-three-way-gate-accounting-decoupling.md) | accepted | 失败三态 product/infra/env 独立函数分类（原 bool 签名不动防恒真），门禁阈值只累计 product，infra 轮只记账+预算事后补偿（须入对账豁免防冲销）、env 保留 blocked 通道，unknown 保守按 product 宁少豁免 |
| [ADR-128](ADR-128-link-level-infra-circuit-breaker-spec-counters-isolation.md) | accepted | 链路级 infra 熔断持久化落盘（补 provider 4xx 内存熔断未覆盖的 402/429/quota/budget），冷却短路派发入口，infra 失败对 spec 级尝试计数与冻结失盲，无杠杆告警只落 ESCALATION 不唤起 |
| [ADR-129](ADR-129-run-id-spec-attribution-single-source-semantic-split.md) | accepted | run 归属判定单一真源全等匹配（禁前缀 glob 判归属、后缀剥离必覆盖 -a/-r），归属归一用全量前缀集而失败计数保留显式子集，一张表禁承载两种语义、口径变化须显式声明配测试 |
| [ADR-130](ADR-130-dashboard-read-path-incremental-invalidation-no-write-side-effect.md) | accepted | dashboard 读路径：增量失效只重算变化项（全量重建仅冷启动/损坏）、缓存签名必须完备覆盖决定输出的全部输入（含 STATE 条目指纹、等价性用例验收）、run 文件尾读+memo 且末行禁截断、读侧零写副作用（清理挂 daemon 周期任务） |
| [ADR-131](ADR-131-repair-success-git-fact-verification-commit-before-test.md) | accepted | repair 成功声明不进信任半径：worker 侧只读 git 事实复核（tip 前进+无冲突残留+无 MERGE_HEAD）后再 re-merge，失败注入具体事实重派，prompt 契约确立提交先于测试为强制终点 |
| [ADR-132](ADR-132-module-to-package-split-paradigm-facade-patch-contract.md) | accepted | 巨型文件包化拆分范式：先改名入包 _legacy 再逐组摘出（同名包遮蔽）、补丁缝隙一等契约（门面 re-export 不保 patch 语义、调用点经门面延迟解析）、依赖参数注入禁模块级回引、内部调用走一行委托保实例打桩、子模块单向依赖、符号名锚定禁绝对行号 |
| [ADR-133](ADR-133-signal-kill-attribution-closed-set-channel-isolation.md) | accepted | 信号致死闭集归因按序短路（cancel→监督强杀→daemon 关停→外部信号，不可判别标 unknown 禁猜测），信号死法冷却按 spec 维度禁写全局瞬断指纹，产物硬门两类失败与瞬断指纹通道隔离 |
| [ADR-134](ADR-134-run-liveness-tail-terminal-criterion-single-recovery-path.md) | accepted | run 存活判据以流末行终态为准（复用终态单源集合、superseded 非死亡、解析失败 fail-open 不误杀），恢复语义单一实现点（精触发与全量扫描同源），精触发稳态零 STATE 写入 |
| [ADR-135](ADR-135-same-cause-redispatch-fingerprint-breaker-freeze-human.md) | accepted | 同因重派熔断按归因归一化指纹连续计数（差异化即重置），达阈值冻结转人工不再入队，冻结文案内嵌原状态供解冻还原，既有各熔断/退避通道独立记账互不喂入 |
| [ADR-136](ADR-136-honest-exit-convergence-single-criterion-lane-uniform.md) | accepted | 诚实退出收敛判据单点（partial+缺口非空⊆unattainable、禁回退读主树勾选），两车道同源判据/收口/留痕，fast-track 收敛降级 full 补三阶段独立验证，非法 unattainable 收敛点 fail-closed |
| [ADR-137](ADR-137-redispatch-legacy-inheritance-contract-claim-single-entry.md) | accepted | 打回重派路径必须重派前登记可继承遗产（现场保留或仅分支登记），保留判定复用收敛判据单点、异常 fail-open 不阻断收工，认领单点覆盖式更新，断言以「在册+可认领」为准 |
| [ADR-138](ADR-138-facade-forwarding-getattr-registry-class-level-alias.md) | accepted | 门面转发以 __getattr__ 内联显式注册表统一委托（未知名严格 AttributeError、dunder 不转发、patch 缝隙兼容），静态式转发以类级别名收敛不入实例注册表，契约测试逐名覆盖性硬门 |
| [ADR-139](ADR-139-interactive-session-longlived-stream-subprocess-process-bound.md) | accepted | 交互式自由会话=长驻 claude 流式子进程（必带 --replay-user-messages），会话状态与有界事件缓冲仅存 dashboard 进程内（无落盘无 resume），spawn cwd 锁死注册项目根，uuid 去重全量重拉接回 |
| [ADR-140](ADR-140-declaration-authority-branch-side-baseline-snapshot-shrink-guard.md) | accepted | 交付物声明权威源=实现分支（worktree>分支>主树统一解析入口），改写同位写分支并提交、主树由 merge-back 对齐，派发时可信基线快照机械化「只可增不可减」，陈旧声明凭三要素凭据确定性重定位禁语义推断 |
| [ADR-141](ADR-141-external-tool-credential-injection-run-level-home.md) | accepted | 外部工具凭据注入走 run 级隔离 HOME（其配置文件压制 env 时唯一确定性手段），HOME 须指向直接含配置目录的目录，包装器用 PATH 搜索型 exec，baseurl 原样透传不归一化，环境缺口降级放行须非空原因 |
| [ADR-142](ADR-142-gate-sentinel-dispatched-in-shared-failopen-predicate.md) | accepted | 门控字段哨兵值（如 start_after=manual）必须在共享 fail-open 谓词内解析前显式分派，禁消费点各自判等；哨兵复用单字段、读侧原样返回禁折叠/伪渲染，激活=置空+既有唤醒信号且幂等拒绝 |
| [ADR-143](ADR-143-artifact-ownership-table-promotion-gate-motivation-elimination.md) | accepted | 验证产物按「产物→归属车道集合」声明式归属表治理，三重合取机械判据在晋升 lint 拦截「要求实现者产出他车道产物」；自证型作弊消除动机而非写侧拦截（堵写不可行），零误拦优先 |
| [ADR-144](ADR-144-orphan-declaration-preclassify-reference-plane-kind-split.md) | accepted | 孤儿声明判定分离引用面与观测面（git grep 负向 pathspec 排除记账面/spec 自身/产物），历史判据按 kind 分化（new 不查历史、modify 路径历史、delete 不参与），机械删除后续走守卫对账防「删完即收口」 |
| [ADR-145](ADR-145-build-artifact-config-driven-unresolved-first-class-wip-head-align.md) | accepted | 构建产物判定零默认值全由项目显式配置驱动，未裁决为一等三态之一且 fail-safe 恒假+起草信号，WIP 重叠闸门产物子集 stash 前对齐 HEAD（只对重叠子集、失败回落不阻塞），未裁决信号挂咽喉处复用 admin 起草链路 |
| [ADR-146](ADR-146-scenario-reroute-stoploss-failure-set-comparison-chain-scoped.md) | accepted | 场景改道止损=跨轮失败集对比（改道前⊆重跑即无一修复立即升级不耗预算，有修复则续预算），读取点须在重跑产物落定后，留存带链内作用域（深度≥1+轮次匹配）防陈旧留存误停新链 |
| [ADR-147](ADR-147-recovery-driver-exclude-admin-intentional-wait-structured-field.md) | accepted | 恢复判定排除 admin 前缀（admin run 非被处置 spec 的驱动证据），判定纯函数、在飞守卫放派发/唤起点（存储 pending∪进程表两真相并集），有意等待双落持久退避字段+定时器（定时器不作唯一机制），耗尽计数只在他终态与人工解冻清零 |
| [ADR-148](ADR-148-verify-serving-reclaim-multi-evidence-retain-failsafe.md) | accepted | verify-serving 回收按多证据保留集（spec 存活含归档/登记 resolve 全等/活进程/宽限期，异常一律保留），mtime 不作删除依据只作宽限，复用幂等 remove、启动+周期双触发（done 事件不作唯一机制），依赖实装默认 hardlink |
| [ADR-149](ADR-149-ledger-resolve-by-full-observation-only-window-append-only.md) | accepted | 审查台账核销只由全量快照观测驱动（未观测≠已修复，窗口观测只增不核销），空 manifest 禁记全绿，框架预算 manifest 为进度分母权威，窗口源与同节拍任务同源且检查点次序先于覆写方，ingest 只消费结构化字段 |
| [ADR-150](ADR-150-new-file-signal-tripod-consume-sweep-hosting-guard.md) | accepted | 新增文件信号必须三件齐登：主循环消费点+启停清扫路径（损坏删除防卡死）+托管守卫（daemon 未运行拒绝写入），消费后即时清理且幂等，新车道复用既有信号机制不另立平行通道 |
| [ADR-151](ADR-151-gate-guard-convergence-dual-landing-zero-write-deferral.md) | accepted | 门控守卫挂自动通道汇聚点并覆盖队列候选筛选双落点防旁路，判定重读当前 STATE 禁用调用方快照，组合谓词单点定义禁吞异常（fail-open 收口留调用点），顺延零 STATE 写禁 error 防事件反馈环（审计走 `_` 侧车+debug 零噪音），在飞判据进程表真相/流兜底、陈旧锚点放行交恢复清理禁自清 |
| [ADR-152](ADR-152-suppression-bounded-releaser-named-edge-alerts.md) | accepted | 顺延/冷却/抑制必须有硬上限回落既有升级通道且显式点名解除者（无解除者的顺延=无限停摆），抑制=窗口计数+冷却锁存双条件、告警按边沿落一次，自触发循环计数须持久化跨进程累计（内存计数单进程最多 1 次阈值恒不可达），聚合清单有界截断，禁复用写入即 mark_handled 的 signal_type，核销内联过期分支且跨时钟域窗口加偏差裕量 |
| [ADR-153](ADR-153-hold-split-resume-consume-before-anchor-clear.md) | accepted | 派发出口清锚点前必须先判定并消费恢复续做标记（消费先于清除），降级/旁路出口禁清锚点禁消费标记，恢复归因须显式来源标记（复用登记非空≠恢复续做），续做收口字段集与先例同集同形状，判定复用 `_resolve_preserved_branch`/`resolve_resume_site` 单点禁副本，载体不可用 fail-closed 拒绝不清锚点，保持态按出路分型（取消保持显式复位 / 冻结保持解冻续做）不合并 |
| [ADR-154](ADR-154-terminal-event-dual-registry-sync.md) | accepted | 新终态事件必须写读两侧同步登记（读侧状态映射+写侧终态集合，各有用例锁定），缺任一侧时间轴永判 running 或删除归档被误拦，下游消费点（归档集/活跃计数/预算计数只认 error 末行/存活探测）逐处复核，让位分支禁写门禁终态防同次失败双红节点，中间弃置行中性呈现归因由终态节点承担 |
| [ADR-155](ADR-155-state-boolean-read-side-normalization.md) | accepted | STATE 布尔字段读侧必须显式归一化（登记归一化表或 str().lower() in true/1/yes 口径）禁裸真值判定——STATE.md 以 Python 字面量序列化、False 读回为真值字符串，StateMachine 与 dashboard 两进程读法不可互推；摘要指纹白名单随新增读取字段同步登记（漏则仅该字段变化不失效返陈旧），前端 TS 接口同步声明+大写 False 负例用例锁定 |
| [ADR-156](ADR-156-review-lane-dispatch-queue-no-impl-slot.md) | accepted | 评审并入派发队列与实现同构执行（禁第三套 worker 池、禁复用 admin 执行池防互饿），不占 max_concurrent 槽位不进活动优先级集合（槽位闸门早退只为评审条目放行），独立在飞登记补「出队→锚点落盘」窗口、单飞守卫双判据至收口、释放禁晚于锚点落盘（防同线程续 attempt 自锁），在飞判据取在飞结论仅陈旧锚点可清，收口链保持同调用栈（attempt 时间戳新鲜度基准） |
| [ADR-157](ADR-157-startup-baseline-snapshot-before-watcher.md) | accepted | daemon 启动必须先同步建 STATE 基线快照再起 watcher（否则存量 SPEC 全判新出现、pushed hook 全量重放连环触发），首扫拆两段：同步快照+后台线程主体不阻塞主循环（主循环是全部信号消费者唯一驱动），全量扫描保留同步组合入口、启动路径禁调异步版（后台线程被同步等待吞掉=修复静默失效），后台线程 daemon 标记纳入 stop() 收口 |
| [ADR-158](ADR-158-spec-level-stop-owner-polling-loop.md) | accepted | spec 级停止（冻结）在属主轮询环内进程内读 STATE 判定禁新增文件信号三段接力，frozen 先于 cancel（spec 级>run 级）并清 cancel 旗标防解冻再杀、poll 已退出按自然结果收工，禁引入重试子循环细粒度位置，冻结终止走独立异常+独立终态行（复用取消异常会撞取消保持使解冻被恢复链豁免），现场走保留登记并扩展分支保护覆盖冻结态，跨进程删除=异步受理+文件信号+有界等待终态 |
| [ADR-159](ADR-159-frozen-set-contract-versioning-migration-chain.md) | accepted | 持久化冻结集契约演进走条目级版本戳（根节点形态不变、缺失视为 1 存量兼容）+写端恒盖当前版本戳（新产物天然达标零迁移）+登记式迁移链循环推进支持跳版本，未登记段 fail-closed 回人工禁猜禁跳过，全量过时删除回落生成通道不置 blocked，迁移前备份、写回失败照常以内存结果继续（幂等），迁移后二次失败走人工禁静默吞禁自动重出 |
| [ADR-160](ADR-160-mergeback-gate-order-structured-classification.md) | accepted | merge-back 闸门固定优先级：语义冲突(rehearsed)→WIP 重叠→spec 目录在飞顺延→放行（预演 merge-tree 无视工作区脏状态，主树脏形态不被预演拦截），可重试分类置于既有早退之后防误判，无 git 退出码形态必须结构化字段判据禁文本匹配、文本匹配锚定 git 原文片段禁宽泛正则且 fail-open，顺延走既有返回载体布尔字段不计失败指纹、非派发调用方保留标记再试，检测只读禁就地收口主树，预算回退复用既有幂等原语禁第三套旁路 |
| [ADR-161](ADR-161-agent-isolated-settings-provider-rebuild.md) | accepted | 隔离运行环境必须按目标 provider 完整重建（清宿主映射同时写入按 provider 重算的新映射、tier 全部映射到 provider 自身模型，只清不建=tier 解析回落宿主 env 全数 404），存量隔离目录版本标记+内容不匹配原子重写（marker 跳过使存量目录对改动免疫、测试须覆盖非首次创建路径），同语义配置键禁双活（死键收编或明示边界），子代理启动失败显式落告警禁静默 |
| [ADR-162](ADR-162-run-metrics-transcript-authority.md) | accepted | run 经济性指标以转录事件（assistant 事件数+message.usage）为权威源禁采信网关 modelUsage 金额（实测自相矛盾差一个量级），新指标并入既有收尾指标设施同名同义禁两套字段语义、估算型显式标注口径，诊断告警设最小样本门槛（零轮空跑/维护类 run 只落指标不打告警），前缀缓存不可依赖属网关侧结论以可复现探针固化、不做缓存优化 |
| [ADR-163](ADR-163-fixture-registry-flag-narrow-aggregation-filter.md) | accepted | 验证夹具以监控注册表显式布尔字段声明（禁项目内 config 标记多次 IO、禁路径/名字推导脆弱），扫描发现恒非夹具（宁多展示不静默隐藏）存量条目由供给脚本复位补写，噪音过滤收窄在告警/运维记录缺省聚合分支禁在共享项目数据源整体过滤、显式点名查询零改动，夹具复位清验证数据写面到空基线杜绝跨轮累积 |
| [ADR-164](ADR-164-full-suite-mutex-domain-process-group-kill.md) | accepted | 同主机全量套件第二发起者必须共入既有主机级互斥域禁另起新锁（拿不到即放弃留痕顺延下周期），硬超时按进程组中止（shell 串形态只杀直接子进程留测试森林存活），跨语言结果格式单一 JUnit XML、非法 format 值按未配置处理禁静默按缺省格式解析，周期任务防重状态独立落盘禁复用他任务状态文件 |
| [ADR-165](ADR-165-external-tool-param-channel-by-property.md) | accepted | 外部工具可调参数先实测性质再分流注入通道（持久化配置键→run 级配置直写、仅 CLI flag→提示词软约束+完整串断言），同参数禁双通道并存防遮蔽歧义（升级=整体切通道非叠加），非法/缺失/环境缺口一律回退缺省禁当交付物缺口重派，未 A/B 实测的归因只作推断、机制设计不依赖推断成立 |
| [ADR-166](ADR-166-selfdrive-batch-loop-ternary-outcome-consumed-leaves-pool.md) | accepted | 自驱动批循环收尾三态化（success/consumed/halt），consumed 与 halt 分界判据=该批条目是否已全部离开可选池（可选池严格单调缩小保证收敛，无出池去向的失败禁入自驱动分支），选批为空是正常收敛出口禁误报故障 |
| [ADR-167](ADR-167-unattended-lane-failure-selfheal-scene-discard-two-tier-skip-budget.md) | accepted | 无人值守车道失败自愈纪律：失败现场即弃+锁即时释放（留痕走档案 branch/tip_sha 不走现场保留），瞬态失败链内跳过与确定性失败档案预算两层分离（预算内新链自动释放免人工），预算用尽永久跳过+一次性点名录告警+台账人工项，预算上限为模块常量不设配置键 |
| [ADR-168](ADR-168-item-progress-read-side-synthesis-explicit-batch-context.md) | accepted | 进度明细类字段由读侧经 agent 产物实时合成禁新增写侧回写路径（合成字段现算不落盘、不可得恒 null 禁回退 0/空对象），读侧定位上下文由写侧显式落盘既有状态文件并随收尾清除、禁目录 glob/前缀反推，run 标识编排器预生成经形参传入（不预生成则目标窗口失效） |
| [ADR-169](ADR-169-inflight-signal-public-method-fail-tight.md) | accepted | 在飞判定经属主层公开方法封装（带参按 spec 精确判/无参任一在飞即 busy）禁跨层直读私有登记、禁线程车道塞 Popen 注册表，判定异常按在飞处理宁紧勿松（判定不可得不得放行杀在飞 run 的动作），消费侧薄容错单点维护（缺属性不阻断/仅采纳真 bool） |
| [ADR-170](ADR-170-fingerprint-staleness-lifecycle-exemption-constructive-git-criterion.md) | accepted | 产物指纹陈旧判定必须区分陈旧与生命周期迁移（merge-back 豁免用构造性 git 判据 merge-base==head 即已完整合入，禁状态枚举双真源），豁免最小化只跳迁移影响项、身份项 branch/head 全等仍强制（head 前移拒 stale 不变），SPEC 终态后门禁呈现确定性收口（终态豁免最高优先级+固定 reason+终态集合与流水线集合有意分离，新状态引入必须同步豁免集合） |
| [ADR-171](ADR-171-artifact-gate-candidate-locations-shared-tree-freshness.md) | accepted | 产物门判缺失必须穷尽同一逻辑产物的全部合法落点（worktree 优先、共享主树回退带新鲜度守卫），fail-closed 只针对确实缺失不针对「在另一授权位置存在」，校验体单点共用禁双实现 |
| [ADR-172](ADR-172-add-dir-minimal-lane-authorization-prompt-anchoring.md) | accepted | `--add-dir` 是工作区边界显式信号按车道最小授权（落点在 worktree 的车道不注入共享树），提示词产物落点与门读取层同源逐车道锚定，授权措辞禁一词多树 |
| [ADR-173](ADR-173-file-signal-single-slot-criterion-explicit-conflict-refusal.md) | accepted | 文件信号单槽位可接受判据=写入方把 conflict 变显式拒绝，否则多槽位化（目录+每主体一文件）；写侧如实回报禁假成功，陈旧信号挂消费方时钟回收（阈值内先消费再删、超阈值仅删），路径常量落中性共享模块 |
| [ADR-174](ADR-174-state-rmw-lock-interior-atomicity-idle-predicate-lane-completeness.md) | accepted | STATE 读改写整体收进跨进程文件锁内禁锁外快照整体回写，构造必注入 logger 写入必留痕，自愈空闲判定须对全部车道在飞经既有权威判据复核禁单一计数器与流新鲜度单独判在飞 |
| [ADR-175](ADR-175-code-fix-lane-framework-batch-loop-mergeback-ironrule.md) | accepted | code-fix 车道框架编排一批一 run 不占 spec 预算，未过全量回归不合回不置终态，零产物行与零有效修复双重白洗防线，批收尾必释放 worktree 锁，进度分母按激活链身份定格 |
| [ADR-176](ADR-176-impl-review-parallel-lane-join-existing-exit.md) | accepted | 长耗时收尾审查摘出实现 run 为框架并行车道（merge-back 后与 tester 同点启动审分支 head），join 于 testing 出口、打回复用 bug_found 零新状态、修轮上限 1，指纹陈旧 fail-closed、车道失败 fail-open 留痕 |
| [ADR-177](ADR-177-visibility-artifacts-soft-constraint-no-hard-gate.md) | accepted | 为可视化新增的落盘是软约束（守卫只查格式违规仅 WARNING、缺失零拦截），权威判定已存在的项读侧合成禁框架新增写者，历史数据 fail-open 零新增打回循环 |
| [ADR-178](ADR-178-hosting-criterion-process-topology-not-inherited-env.md) | accepted | 实例托管形态判据读父进程身份（/proc comm 恰等匹配）不用可继承环境变量（tmux/shell 传播污染双向误判），判据落代码为根本修复、入口 env 前缀只是双保险，读取失败偏向防泄漏 |
| [ADR-179](ADR-179-adjudication-correction-write-read-same-layer.md) | accepted | 裁决修正写入层=守卫读取层（source 三态分流，branch 无落盘禁写主树就地生效），核心不变量「修正被执行⇔下次读取可见」，复发熔断独立计数禁复用可清零字段，跨轮凭据核销需替代路径真实存在，降级必留痕 |
| [ADR-180](ADR-180-manual-trigger-override-param-keeps-guard-chain.md) | accepted | 手动触发复用编排器单一入口临时授权成参（缺省关），只放宽调度门槛不跳过安全链（失败保留/契约 fail-closed/单飞照常），结果文件+请求时间戳回链防陈旧结果误读 |
| [ADR-181](ADR-181-adjudication-choices-registry-snapshot-atomic-resolve.md) | accepted | 人工裁决选择题化：静态注册表共同事实源，choices 写告警时快照进记录（历史不被注册表演进改写），resolve 单端点原子编排动作+推进+handled+留痕，豁免推进走状态机合法路径 |
| [ADR-182](ADR-182-inrun-selfcheck-production-validator-single-source.md) | accepted | run 内自证入口=生产校验体的模块级 CLI 出口（同一函数对象禁复制逻辑），契约正反例动态注入禁双源，回归判定责任单点化到验证链，读侧优先级=框架车道产物>run 内自查>pending |
| [ADR-183](ADR-183-full-chain-model-unavailable-attribution-no-same-cause-redispatch.md) | accepted | 候选链尾模型仍被拒→失败归因必含「全链模型不可用」、派发器禁同因重派（阻断冷却周期重撞循环），链内切换不递增瞬断/重派计数，运行时链摘除为人工运维步骤不进门禁 |
| [ADR-184](ADR-184-mergeback-wip-overlap-precheck-human-escalation-default.md) | accepted | merge-back WIP 重叠交集非空不发 merge，缺省处置从 auto 静默收纳改为人工升级拦截（choices 告警附交集清单），bypass 逃生门，闸门优先序不变 |
| [ADR-185](ADR-185-restart-drain-window-independent-key-ordering-constraint.md) | accepted | restart 排水窗口独立键与常规停机窗分离（禁一键两义），新增时间窗必须显式声明与既有协调窗口的次序不等式保证监督者后动，restart 流程广播 checkpoint 后短窗排水超窗强杀 |
| [ADR-186](ADR-186-verdict-cache-quadruple-key-fail-closed.md) | accepted | verdict 缓存键=（场景id,内容指纹,构建指纹,验证配置指纹）四元组全等才采信、存疑 fail-closed，PASS 判定同样入缓存（否则读侧无据），重验集=失败∪受影响∪前置链 |
| [ADR-187](ADR-187-verify-lane-parallelization-ready-state-dispatch-capped-exemption.md) | accepted | 验证链并行化：出题挂 ready 态吃实现排队窗口，就绪短路复用既有校验禁双标准，槽位豁免带独立在飞上限防挤占网关，judge 轮内重裁决阈值先于 spec 级硬上限、低置信优先证据扩充 |
| [ADR-188](ADR-188-underlying-signal-type-additive-field-no-top-level-replace.md) | accepted | 包装通道透传底层信号类型用独立附加字段禁顶层替换（防记账/节流/展示互吞），发现靠消费侧反查未处置记录取最新并排除自产记录，复位门判定点单点扩展 |
| [ADR-189](ADR-189-lane-heartbeat-over-probe-exemption-terminal-last-line-invariant.md) | accepted | 最小生命周期车道运行期必须发心跳消费既有活动判据——治理探针误报优先补活性信号禁加豁免（豁免无 boot 恢复会遮蔽重启后真孤儿），停跳先于终态写保「终态末行后置」不变量 |
| [ADR-190](ADR-190-new-periodic-role-shared-scheduler-wiring-state-key-separation.md) | accepted | 新周期角色挂共享调度入口：状态键分离禁写宿主「今日已执行」键与增量窗口锚点（共享单键双向互相抑制），早退门扩为全部角色键齐备才闭合（单角色失败同日可补跑），run 前缀独立并登记宿主统计排除集防污染零活动防护，agent 类型注册表全链路同步逐表断言（漏一处静默失效） |
| [ADR-191](ADR-191-managed-config-key-whitelist-merge-four-point-roundtrip.md) | accepted | 受管配置键必须走白名单合并全链路四处必改点（合并分支/前置校验/键来源映射/缺省回显），禁挂只透传部分子键的既有段（被吞），验收必须含读写往返断言（保存→重新 GET→值仍在）禁只断言保存返回 200，项目级键卡片沿用 scope 约定防写入用户级 |
| [ADR-192](ADR-192-worktree-lock-residue-recovery-inmemory-authority-and-retry-quota-layering.md) | accepted | worktree 锁残留恢复：内存锁权威源不变、落盘 sidecar 禁构造期加载为拒绝依据（反超即把重启后成功翻成拒绝），残留判定进程表为主+转录新鲜度有前缀盲区禁单凭判残留+记录缺失 fail-closed 判活动，create 层只做一次性清理重试、重试配额语义归属派发层禁双重重试链，锁冲突结构化原因对齐基础设施故障先例不落死亡 run 豁免不计 retry |
| [ADR-193](ADR-193-facade-call-site-coverage-hard-gate-ast-bucketing.md) | accepted | 门面字面调用点覆盖性硬门：AST 正扫 `self._pm.<名>` 断言经所属门面可解析（解析域=注册表键∪显式定义含实例属性赋值 AST 推导，豁免显式名单按注册表/显式/豁免三归属可辨），扫描域目录分桶完备禁混扫（未入桶即失败），反向断言查悬空不查死键（按条目形态适配），漏注册由测试合入前拦截禁调用点 try/except 兜底 |
| [ADR-194](ADR-194-transient-unseal-progressive-release-single-gate-selfdrive.md) | accepted | 熔断解封渐进恢复：hold 与探针叠加非二选一（解封次数按指纹记忆稳定衰减），解封节奏全部闸态由派发首道闸单通道态序短路消费禁旁路通道，探针判败复用既有指纹记账禁新探测调用，各到期锚点单飞行定时器链自驱禁依赖外部触发点，准入 pop 前消费 pop 后对称退还，判定异常 fail-open 放行 |
| [ADR-195](ADR-195-frozen-entry-recheck-and-escalation-cooldown-dual-leg-defense.md) | accepted | 冻结回置噪音双腿防御缺一不可：恢复/派发/重试入口 frozen 复核断「部分回置」腿（INFO 留痕零写入），daemon_errors 指纹级重启冷却+同轮孪生合并兜「整文件重置抹 frozen」腿，后续 SPEC 禁以任一腿为由删另一腿 |
| [ADR-196](ADR-196-gate-exemption-and-dispatch-interception-two-criteria-layering.md) | accepted | 内容闸门豁免与派发拦截两判据分层：终态豁免/已交付降级只免冻结与告警，spec_has_content 四类认可名单不动且 verification-report.md 禁入（防盲目重实现已交付成果），终态 spec 入队属异常由派发层状态机管辖 |
| [ADR-197](ADR-197-wipgate-defer-keep-scene-release-lock-zero-budget.md) | accepted | WIP 阻断延迟合回：暂态阻断零预算走独立 defer 台账禁入失败预算体系（预算语义=重跑，暂态只需等待），保留现场必须同步显式放锁（只保留不放锁=建树恒 None 车道死锁），defer 条目必退选批池，重试挂既有链节拍不新增线程 |
| [ADR-198](ADR-198-agent-side-task-subagent-batch-parallel-single-run-contract.md) | accepted | 车道批内并行放 agent 侧 Task 子代理（框架单 run/单 out_path/单回归合回契约零改动），产物落盘验证提交集中 orchestrator 单写者、子代理三禁（写产物/验证/提交），并发上限保守且由框架按批规模注入不设配置键 |
| [ADR-199](ADR-199-code-review-shard-direct-write-single-discovery-aggregation.md) | accepted | code-review 产物分片直写（谁审谁写审完即写、禁异步等待收工），分片发现单一入口 shard_paths 禁消费侧自写 glob，聚合口径三侧统一（分片 N 升序→主产物兜底、按 file 先见去重），错名分片 fail-显式只告警不消费；与 ADR-198 单写者以「产物是否喂回归/合回门」划界 |
| [ADR-200](ADR-200-manual-trigger-ack-result-carries-no-run-terminal-epoch-criterion.md) | accepted | 手动触发受理回链文件只承载受理三态不承载 run 终态（单文件覆盖写），受理窗口守卫凭 run 标识 epoch 构造性区分「排队中」与「已跑完」+新鲜度窗口防锁死（二判据缺一即回归），POST 200 非启动确认、前端 requested_at 回链匹配，竞态与超窗放行统一 fail-open 到单飞显式拒绝落结果 |
| [ADR-201](ADR-201-ratelimit-switch-channel-independent-cooldown-no-fuse-double-count.md) | accepted | 429 限流纳入切换类通道（三种显式形态判定且先于瞬断/4xx 解析），provider 走独立限流冷却（缺省 300s 独立常量不与 switch 冷却共用键），MUST NOT 计入 4xx 熔断双计数，全链同冷却维持 chain_exhausted 直接失败 |
| [ADR-202](ADR-202-ratelimit-terminal-redispatch-intent-registration-consumer-split.md) | accepted | 限流打死的 run 冷却到期自动重派一次：runner 只写重派意图不执行重派，消费落在唯一生产调用方收场分支，上限 1+冷却到期前置构成对 ADR-183 禁同因重派的有界例外，重派幂等续做复用原产物 |
| [ADR-203](ADR-203-worktree-branch-numeric-tail-naming-contract.md) | accepted | worktree 分支名末段恒为纯数字时间戳、命名公式禁掺非数字后缀（queries 层 rsplit+isdigit 解析契约），同名冲突以单调递增换名（同名双换、至多 2 次重试）解决，不用 uuid 唯一化、不做同名分支复用 |
| [ADR-204](ADR-204-wip-defer-flag-lifecycle-invariant-selfheal-before-summons.md) | accepted | spec 车道 WIP 阻断必落结构化等待标志（禁 error 文本唯一载体），标志生命周期不变式「implementing+带标志⇒无在飞实现 run」由三类清账写点构造性保证（消费者免查活动 run），周期自愈先于孤儿探测且豁免与降级消费同一超限常量（禁双源阈值），既有重试入口守卫只拦非 implementing 禁收紧为须带标志 |
| [ADR-205](ADR-205-verify-lane-terminal-reclaim-cancel-key-epoch-convergence.md) | accepted | 车道终态自我收尾复用 cancel_run 但取消键 MUST 为含 epoch 完整 run 级 id（裸 `<lane>-<spec>` 键与消费点精确集合判定不收敛、取消静默失效且返回值显成功），逐 run 归属复核 run_spec_part 禁裸前缀误中同根后代，收尾挂终态收敛点转移成功之后（逃生门续跑路径不收尾），协作式取消退出延迟由应用侧非 testing 丢弃兜底双腿缺一不可，`_stop_parallel_planning` 裸键为反例禁照搬 |
| [ADR-206](ADR-206-regression-fix-single-channel-code-fix-lane-ledger-conversion.md) | accepted | 回归问题修复复用 code-fix 车道单通道（消费端转换入账+override 授权派发，禁独立修复车道与前端台账写路径），台账共享契约零改动、`regression-` 前缀隔离标识，快照读取以当下为准缺读落 snapshot_missing 不重试 |
| [ADR-207](ADR-207-tailwind-content-explicit-dir-registration.md) | accepted | Dashboard 双样式管线并存：tailwind 仅服务 claude-* 迁移组件且按目录显式注册 content（CLI 有 content 配置时不启用自动内容检测，不注册则类名静默不编译、构建零报错），禁 preflight、全站恒亮色，新增 tailwind 目录须成对扩 content 并 import 生成 css |
| [ADR-208](ADR-208-session-completion-metadata-from-init-event-only.md) | accepted | 会话补全元数据唯一口径=CLI init 事件缓存（禁自扫 skills/命令目录），init 捕获写入 Session 缓存后即丢弃不进事件缓冲不广播 SSE，缓存随 Session 生命周期存亡，init 未到达静默降级空候选 |
| [ADR-209](ADR-209-pytest-per-test-timeout-gate-single-source-signal.md) | accepted | pytest 单用例 10s 超时门仓级单源（pytest.ini，各入口零配置继承禁旁路）、不设全局放宽旋钮（唯一放宽通道=显式豁免清单三字段+机械校验）、中断方法固定 signal（thread 整进程代价禁作全局方法），与套件级硬超时分层互补 |
| [ADR-210](ADR-210-codefix-regression-gate-pass-semantics-round-scoped.md) | accepted | code-fix 回归门通过语义分轮：首轮全量、定向重试轮只重跑上一轮失败用例集且子集通过即门通过（MUST NOT 补跑全量），漏检由合回后周期回归兜底+失败明细落盘复发追溯锚定，下游消费该信号禁假设全量绿，修测试授权随定向轮放开（fix_scope=test 标注+明细落盘+台账复发重开三重防白洗） |
| [ADR-211](ADR-211-regression-subset-execution-facade-layer-primitive-agnostic.md) | accepted | 回归用例子集执行承载于 run_regression 门面可选参数、core.regression 原语层不感知子集（既有调用点语义逐字不变），命令改写固定「取代既有收集位置参数」禁尾部追加（pytest 多位置参数并集语义会静默退化全量），不可安全改写（非 pytest 形态/无收集目标/shell 操作符与命令替换）一律 fail-closed 回全量 |
| [ADR-212](ADR-212-adjudication-env-exemption-no-self-approval-admin-anchored.md) | accepted | 裁决 env 豁免不得自我批准：「失败全部环境性」轮次两级防线（judge 前全批 blocked-env 短路 + 采纳尾段断言级判据）共享同一 inconclusive 计数器禁双计数，重验前须框架权限内补救（dist 探针）留现场禁静默，豁免生效以 AdminStore DISPOSITION 放行记录为唯一锚、admin 介入前禁以豁免清单自行 verified |
| [ADR-213](ADR-213-mergeback-wip-mechanical-occupant-id-event-driven-wakeup.md) | accepted | 合回 WIP 阻断：占用者识别纯机械求交（三点 diff + run 前缀过滤 + code-fix spec 桥接，禁 LLM 推导；主树直改盲区按无主走宽限升级禁主树写探测），唤醒以持有者 run 终态事件为主（per-run 终态监听挂 agent_runner 终态收口、注册先查已终态）轮询兜底、禁依赖 scheduling_kick 单槽位唯一唤醒，事件重试复用单一重试入口禁旁路线程直调，无主宽限耗尽升级禁自动 stash/丢弃主树改动 |
| [ADR-214](ADR-214-maintenance-run-stall-dual-criteria-fail-open.md) | accepted | 维护型 run 停滞判定双判据合取（产物 mtime × 进程树 CPU，任一有进展即重置），判据不可用 fail-open 不触发，阈值独立配置键脏值回退缺省，取消走既有原语与急救落账禁新造通道 |
| [ADR-215](ADR-215-lane-decoupling-logical-only-physical-contention-natural.md) | accepted | 车道解耦只删逻辑调度层否决/等待条件，物理冲突点由既有锁自然串行禁再叠互斥，车道自驱动推进覆盖全部批收尾路径不依赖他车道事件或周期扫描兜底 |
| [ADR-216](ADR-216-dashboard-on-demand-longtask-accept-poll-lightweight-spawn.md) | accepted | dashboard 按需长任务固定受理-轮询异步范式（HTTP 线程禁同步等待、状态原子写落盘、重启残留读侧合成中断）+ 一次性 headless spawn 执行不入开发主链路（无 run 台账/车道/预算/新配置项），成本靠手动触发+单飞+超时上限自然节流 |
| [ADR-217](ADR-217-spawn-artifact-verdict-authority-reality-not-selfreport.md) | accepted | spawn 产物成败判定权威=产物实况（退出码→文件存在非空→特征校验→marker 提取）禁采信 agent 自述；形态数值校验只对能提取的情况生效、提取失败记 null 放行，可用性优先于校验完备性 |
| [ADR-218](ADR-218-generated-html-iframe-sandbox-no-same-origin.md) | accepted | 机器生成 HTML 一律专用只读端点下发 + iframe sandbox=allow-scripts（禁 allow-same-origin）渲染，产物脚本与主站存储/DOM 隔离；同源交互需求须独立安全设计评估禁顺手放开 |
| [ADR-219](ADR-219-external-skill-dependencies-vendored-no-runtime-install.md) | accepted | 外部 skill/工具依赖一律 vendored 整包随库分发（vendor/<name>/ + VENDORED.md 溯源，只许整包替换升级），运行时零联网安装、零用户环境依赖，指引以提示词注入原文+包根绝对路径交付；部署缺件属部署损坏 fail-closed 判失败禁安装自愈，可用性禁押在运行时外网可达性上 |
| [ADR-220](ADR-220-run-stall-composite-criteria-default-off-chain-terminate.md) | accepted | run 停滞判停只许复合判据（连续 N×120s 往返 或 stall 占比过半+M 分钟无产物进展）、整个预算缺省关闭灰度，命中即强杀 attempt 并终止整个重试链（禁瞬态/in-place 重派放大止损），统计 run 级累积跨 attempt 不重置，禁绝对次数单一阈值 |
| [ADR-221](ADR-221-agent-runner-reads-pm-engine-via-injected-callback.md) | accepted | agent_runner 读 pm_engine 车道状态一律构造注入 reader 回调（沿 result_gate 注入约定）禁模块级依赖，未注入/读取异常/数据缺失一律按无数据处理 fail-open 不阻断既有行为 |
| [ADR-222](ADR-222-project-log-alert-dedup-at-business-check-site.md) | accepted | PROJECT_LOG 告警去重是业务检查点语义禁下沉共享日志通道，去重状态承载 AdminStore 持久告警存储（latest_signal 窗口查询）按 signal_type 族级键判定、禁扫描日志文本，状态源不可用降级照常追加 |
| [ADR-223](ADR-223-request-signal-autoclosure-whitelist-fact-equivalence.md) | accepted | 请求型信号「探测通过即免唤起」自动闭环走白名单制，入表门槛=只读谓词+「谓词与诉求满足是同一事实」语义等价双条件，需语义判断类型永不收录；探测 fail-open 永不为信号前置门，handled 回写属记账动作失败降级不阻塞处置落盘 |
| [ADR-224](ADR-224-llm-generation-pipeline-small-context-stages-disk-handoff.md) | accepted | spawn claude 生成管线每轮请求必须落「小上下文×短输出」安全区（大上下文×长输出被网关静默丢弃）：长任务顺序分段、段间磁盘为唯一交接面、大文本指引路径引用禁内嵌 prompt、大产物分段小步写、段级独立超时与产物实况判定链、中间产物盖指纹头跳段复用无 TTL；细化 ADR-219 指引交付通道，vendored 零安装裁定不变 |
| [ADR-225](ADR-225-help-docs-placement-by-user-scenario.md) | accepted | 帮助文档机制描述按使用场景落位进「用户遇到问题时会翻的那一章」（env 豁免→验证章、unseal→治理节、取消保持态→生命周期+Dashboard 互链），禁集中新建「新机制汇总」章；组织轴=使用场景非提交历史，篇幅两段式上限+既有标题文本不动防锚点漂移 |
| [ADR-226](ADR-226-codefix-batch-file-group-indivisible-target-scale-binpacking.md) | accepted | code-fix 选批以文件组为最小不可拆单元确定性贪心装箱，batch_size 定语义为目标规模 T（硬上限 2T）、同目录=直接父目录全等禁语义相似度判据、单文件组超限独立成批不拆；后续触碰选批者不得破坏确定性与文件组不可拆 |
| [ADR-227](ADR-227-codefix-two-stage-regression-last-batch-full-baseline.md) | accepted | code-fix 批收尾回归两段式：非末批按触碰面定向（{test_targets} 占位符）、末批恒全量为整链唯一合并防线；定向化 fail-open（无占位符/映射空/配置关一律回退全量禁跳过）、末批判定与链选批同排除口径禁裸计数、复用 run_regression 不新增执行通道；合回防线降为末批全量是显式取舍，后续 SPEC 不得削弱 |
| [ADR-228](ADR-228-manual-llm-health-probe-stateless-proxy-circuit-isolated.md) | accepted | 手动 LLM 健康探测=daemon 后端代理纯探测（浏览器不直连、端点无状态显式三字段、解析链在前端），与运行期熔断状态严格隔离禁写熔断计数/切换冷却/半开探针，请求签名与运行期 CLI 同构保证结论对运行期有效 |
| [ADR-229](ADR-229-worktree-lock-wait-caller-layer-no-takeover-crossing.md) | accepted | worktree 锁让路退避归 runner 获取调用层（共用原语禁内嵌等待、不消耗 attempt 额度不写 STATE 退避字段），自动等待一律不可穿越人工接管——frozen/_cancelled_hold/status 迁出立即让位且退避每轮重探前复查，锁释放后取得不构成并行 run |
| [ADR-230](ADR-230-truth-source-write-single-gate.md) | accepted | 知识真相源写入单门：增量蒸馏/回填/audit 转写一切写入走同一蒸馏契约+validate_knowledge 全量校验+pathspec 限定提交，页级冲突先提交者胜、后写 run 重读现网叠加，不做页级锁 |
| [ADR-231](ADR-231-audit-two-tier-disposition-semantic-llm-only.md) | accepted | audit 病灶两级处置：机械项脚本直修直提交，语义项禁脚本改写必走定向蒸馏 run 由 LLM 终判重写，初筛宁松勿紧、误报判无矛盾零改动收场 |
| [ADR-232](ADR-232-distill-run-main-tree-direct-no-mergeback.md) | accepted | 蒸馏 run 主树直跑无 merge-back（与 fast-track worktree 模式 deliberately 不同），格式对账与 git 提交不进 agent：daemon 侧 validate_knowledge 对账+违规回反馈 ≤2 轮+pathspec 限定提交，放弃产出 restore 不留半成品 |
| [ADR-233](ADR-233-distill-trigger-single-funnel-commit-archive-move.md) | accepted | 蒸馏触发单点挂载归档共同漏斗 commit_archive_move：手工/自动归档/软删除三路径单点全生效，fail-open 不影响归档返回值，新增归档路径必须沿用漏斗否则视为放弃蒸馏 |
| [ADR-234](ADR-234-backfill-distill-queue-ledger-registration-single-writer.md) | accepted | 回填期增量蒸馏排队=登记进回填台账而非内存队列/写者锁，spec/knowledge 单写者归零页级冲突，收敛（台账无 pending）后恢复即时派发，排队判定故障 fail-open 放行原派发 |
| [ADR-235](ADR-235-cli-stderr-noise-single-source-triple-separation.md) | accepted | CLI stderr 噪声判别单源收口（具体枚举、行首锚定、逐行判别）与拒模型瞬态分类、error 归因降噪三源分离互不替代；留证层一律不过滤，降噪只作用摘要与归因消息 |
| [ADR-236](ADR-236-api-timeout-salvage-at-failure-reuse-claim-never-consume.md) | accepted | code-fix API 超时签名判别收口 runner 层单源（两形态窄口径）、现场抢救挂失败判定当时（salvage 提交+legacy 保全+置复用标记）非清扫期、同链接续只走 reuse 认领 fail-open 禁 consume_legacy 回收端（删分支复刻悬空净损失），非该签名失败行为保形 |
| [ADR-237](ADR-237-ratelimit-attribution-dual-source-shared-quota-shaved-resume.md) | accepted | 限流重派闭环双车道化：终态归因双源（异常文本先行、result 事件兜底）、手动+周期共享配额统一消费入口、剃余续跑只跑剩余文件、快照核销覆盖完整性门宁锁勿白洗（修订单消费方与全量重跑前提，ADR-202 有界例外裁定延续） |
| [ADR-238](ADR-238-codefix-regression-placeholder-sanitize-fallback-exits-periodic-exempt.md) | accepted | code-fix 回归占位符消毒挂全部回退执行路径（三类回退出口+定向重试轮两态，缺省 tests/、零迁移），判别读原件执行用消毒副本禁入口盲替，周期回归通道显式豁免（参数位占位符属配置错误由模板警示兜底，定向化须另立条目） |
| [ADR-239](ADR-239-run-jsonl-read-topline-then-retention-archive-fallback.md) | accepted | run 转录聚合/对账读取一律双路径回退（顶层 .fenix/runs/ → retention 归档副本 .fenix/runs/archive/，并存取顶层即最新副本），缺失语义按「两处皆缺」判定、零贡献 fail-open 禁中断链终局；单路径只读顶层被排除——retention 300s 移档×长时段链跨数小时，链终局多数 run 已移档，漏样本归零（chain rollup 恒零实测根因，同类缺陷两度复发） |

| [ADR-240](ADR-240-run-artifact-lifecycle-bound-to-spec-archive-no-capacity-trim.md) | accepted | run 产物生命周期单轨绑定 SPEC 归档（归档即两处清理、唯一入口不新增第三入口），归档目录禁设容量上限、以「SPEC 归档清理+无主产物 14 天兜底」双机制保证有界，无主判定现算+扫描失败 fail-closed 防误删，删除必逐文件审计+批次上限，禁再立 keep 类容量裁剪 |
| [ADR-241](ADR-241-archive-eviction-manifest-first-dual-source.md) | accepted | 归档条目迁出固定「先清单后活跃」顺序不变量（崩溃窗口只允许双源中间态、禁丢条目态），STATE.md 收敛为活跃集+归档清单 `.fenix/STATE.archive.md` 第二真源，已归档判定与全部读侧消费方双源合取活跃优先，统计恒活跃口径 |
| [ADR-242](ADR-242-escalation-narrative-write-entry-pure-enhancement-fail-open.md) | accepted | 转人工裁决叙事挂告警写入口作纯增强字段（三段结构、不改结构化语义、机器消费方零感知），机械闸门零 LLM、失败 fail-open 至多一次硬超时——叙事是增强不是门禁，后续告警 LLM 增强必须沿用此边界 |
| [ADR-243](ADR-243-llm-assist-single-shot-via-spawn-channel-no-direct-gateway.md) | accepted | 特性级 LLM 单发调用一律复用 agent spawn 通道（模型回退链+硬超时+依赖注入假通道测试），禁直连网关 HTTP 第二套凭据/UA/代理面、禁传高危旗标；高频批量场景须另立条目不得私开 HTTP 客户端 |
| [ADR-244](ADR-244-dashboard-conditional-get-datasource-signature-dispatch-short-circuit.md) | accepted | dashboard GET 读端点条件请求通道：ETag=数据源全集 (mtime_ns,size) 签名哈希（禁响应体哈希、禁不完整签名）、协商短路在表驱动分派层先于 handler（兼容自含响应 handler）、签名缺失/抛错降级无条件 200（宁缺 304 不假 304+发头前复核防两趟读取错标）；后续新增 GET 端点必须注册签名函数，文件签名禁跨请求 memo stat |
| [ADR-245](ADR-245-builtin-default-behavior-read-side-injection.md) | accepted | 零配置默认行为进代码：hook_config() 读侧向返回副本注入内置 hook 条目（同 id 用户条目优先），禁原地 mutate 入参、禁持久化进 gitignored 运行时配置（落盘则逃生键失效），注入条目走与用户条目同一执行链无旁路；后续零配置默认行为一律沿用此形态 |
| [ADR-246](ADR-246-naive-timestamps-interpret-local-parse-ts-single-entry.md) | accepted | naive 时间戳唯一解读=本地时区（存量 naive 实测多产自本地 now()），全框架只许 timelib.parse_ts 一种 naive 解释、任何模块不得实现第二种，时间产生/解析/序列化/渲染收拢 timelib 六函数单源，AST 守卫棘轮（白名单只许收缩+僵尸条目报失败）防回潮；后续全仓调用点迁移必须消费同一冻结契约 |
| [ADR-247](ADR-247-hhmm-schedule-semantic-boundary-local-wallclock-to-aware-utc.md) | accepted | HH:MM 调度语义边界：本地墙钟解析后立即转 aware UTC、配置字面值不变、窗口计算全程 aware 比较，后续 HH:MM 类调度配置一律沿用此换算、不得保留 naive 气泡也不得按 UTC 解读字面值 |
| [ADR-248](ADR-248-untracked-deploy-copy-manual-refresh-no-mergeback.md) | accepted | 未跟踪部署副本（.fenix/bin）不随 merge-back 落地：bin 真身修改后的人工刷新登记为必备交付项，agent 不可交付部署副本、禁纳跟踪绕过，真身与副本漂移排查先于「改了没生效」归因 |
| [ADR-249](ADR-249-subset-evidence-invisible-to-fullscope-gates.md) | accepted | 定向子集证据对全量口径门禁不可见：口径标记（run_scope）仅在子集实际生效时落，门读侧数据源内部 fail-open 回落不吸收口径差距，后续新增部分范围产物源必须携带口径标记并同步读侧判定 |
| [ADR-250](ADR-250-contract-signal-window-bifurcation-closing-semantics-follow-window.md) | accepted | 契约信号按触发窗口二分互斥（ready/implementing 巡检前置 vs testing 后消费期 fail-fast），处置收尾语义随窗口而非随信号类型（前置=起草落位勿复位 spec、消费期=复位 ready 重验证），新增触发点必须归窗并携带匹配收尾指引 |
| [ADR-251](ADR-251-project-level-artifact-signal-singleton-no-spec-fanout.md) | accepted | 项目级产物（一份/项目）的检测信号必须项目级单例、禁按命中 spec 数量放大唤起（(spec, signal_type) 节流对不同 spec 不互斥），spec 字段只是唤起挂靠点不代表处置对象 |
| [ADR-252](ADR-252-api-stall-observe-only-no-intervention-no-jsonl-contract-growth.md) | accepted | 子进程内 API 停滞只读侧观测（期内 WARNING 留现场 + run_metrics 字段入账），不做 kill/重派/自动重试/人工告警等任何期内干预（黑盒不可重连、合法长轮与真停滞转录不可区分），观测产物不向 run jsonl 注入新事件类型，结构化出口只走字段与日志检索两条 |
| [ADR-253](ADR-253-run-budget-observe-judgment-separation-default-off-guard.md) | accepted | run 预算轴新证据维度一律只观测不改判（观测面恒开、故障记 unavailable），活性矩阵收窄只许缺省关闭+多条件合取+仅实现车道+复用既有 kill/WIP 收口的守卫形态（封顶语义优先、关闭逐位一致），预算推算只抬不压（override>推算>base、解析单点） |
| [ADR-254](ADR-254-spec-amendment-observe-only-intel-attach-dual-entry-single-source.md) | accepted | 主树已提交在飞 spec 修订检测为只读情报附着（命中只告警+挂 amended_inflight，不改 merge 结局/不入熔断，插点靠纯只读性前移闸门序列头部），判定与指纹收口单模块级单源供 merge-back 与周期扫描双入口共用，告警唯一反馈面禁自动改道/推送/拦截，后续自动干预类须显式 supersede |
| [ADR-255](ADR-255-inprocess-verify-liveness-named-thread-probe-primary.md) | accepted | 进程内验证活性判定主判据=命名线程探测（线程名从派发队列单点取值、`fenix-<agent_type>-<spec>` 命名空间成为进程内车道对判定读侧的注册契约）、辅证=进度文件独立活动窗 mtime（禁复用 120s run 宽限）、线程臂无时间上界（回收交给验证车道既有超时）、终态口径逐位一致、单次消费出口只跳过不设延迟队列；周期探测/运行期恢复/处置复位直通道三出口同 helper 收口 |
| [ADR-256](ADR-256-baseline-branch-single-resolver.md) | accepted | 分支相对基线的未合并提交判定单源经共享解析器（origin/HEAD → main → master → 回退 main，带超时与缓存），后续基线类判定禁自建口径或硬编码主干名，闸门失败方向由各调用点 git 查询自身维持不随迁移重写 |
| [ADR-257](ADR-257-maintree-staleness-content-fingerprint-no-mtime.md) | accepted | 主树改动集滞留/陈旧计时一律用内容指纹（路径排序集 + `git diff HEAD` 内容哈希）的连续在场，禁用 mtime——autostash pop 会批量重写改动文件 mtime，mtime 不是主树可靠时钟；后续同类滞留判定受同约束 |
| [ADR-258](ADR-258-stray-sweep-readonly-observer-attribution-single-source.md) | accepted | 主树 WIP 占用归因单源复用 `identify_wip_occupant` 禁重造求交，观察型归因消费者禁设空闲预检（否则在飞车道全被误判无主），盘点为旁路只读观察者（主树锁非阻塞弃轮、只读白名单零触碰、处置权留人工程序），处置自动化须显式 supersede |
| [ADR-259](ADR-259-alert-zero-blocking-async-sidecar-narrative.md) | accepted | 告警落盘零阻塞：机械文案即时落盘，LLM 增强后台生成写不可变本体之外的侧车（原子写+读侧按 id 合并），失败/熔断写终态侧车禁 pending 假态，配连续失败熔断与有界重试；修订 ADR-242 的同步执行后果，纯增强/零门禁边界延续 |
| [ADR-260](ADR-260-adjudication-choice-result-first-closeout-and-scope-declaration.md) | accepted | 裁决 choice 作用域在注册表逐项显式声明（spec_scoped 缺省保守 True，spec_scoped 禁全表反查兜底放行），消费端提前跳过+执行器拒绝双层设防共用解析单源，处置终态回写结果前置（失败记 failed 保留待重审、禁假闭环）、留痕与 handled 置位解耦，全局信号必须保留非作用域等价动作收口不断路 |
| [ADR-261](ADR-261-codefix-mergeback-conflict-salvage-before-cleanup-group-granularity.md) | accepted | code-fix 合回真冲突救回挂整批即弃前 _safe_cleanup 窗口内单轮闭环（rebase 基线+重跑批回归+重走合回至多 1 次，禁依赖分支/worktree 跨轮存活），失败降级 commit 组粒度 cherry-pick 回收（冲突文件集取 MergeConflictInfo 单源、条目归属以 body items: 清单为唯一依据禁无据归属），终局兜底仍整批入档与现状兼容，wip_gate_blocked defer 零预算路径不触发救回 |
| [ADR-262](ADR-262-state-typed-field-reset-zero-write-shape-rejection-priority.md) | accepted | STATE 持久化字段按类型契约管理：非布尔字段复位写类型零值（覆盖类字段写 null），布尔归一清单禁纳非布尔字段；写侧单字段形状守卫拒绝优先于静默归一（只剥违规字段不牵连同批），解析侧按类型登记幂等归一兜存量，读端降级安全缺省并留痕 repr 与字段来源、禁布尔语义映射领域值 |
| [ADR-263](ADR-263-maintree-session-attribution-relevance-gate-single-key-rollback.md) | accepted | 主树活交互会话归因三裁定：探测只读 fail-open（零命中/源缺失/异常逐位回无主现状）、相关性信号门（命中必须含散件×会话路径交/路径提及＋身份/时间窗/活跃窗判据，仅「存在活跃会话」不得单独吞掉无主散件）、采信回退全局单键（admin.maintree_session_attribution_action 同一读取器约束盘点降级与 defer 采信、非法值回退 keep、降级留痕不新增 AdminStore signal_type）；后续新增归因源受同约束 |
| [ADR-264](ADR-264-cli-env-lane-scoped-injection-evidence-gated.md) | accepted | CLI 行为调参 env 一律车道级注入（env_overrides 组装处、禁 runner 全局位防残留后台任务烧满 run_timeout），扩展到其它车道须同构证据评估（模板含子代理派发+转录击杀签名）默认不注入 |
| [ADR-265](ADR-265-crossday-recurrence-observability-readonly-escalation-only.md) | accepted | 跨日同刻复发聚合观测纯只读（仅 escalation 升级告警、绕过 30 分钟重启冷却），不接派发/熔断/冷却/salvage 任何自动干预消费点，第一维度判定规则不动，归一化放宽方向保守（同形聚合计数只增不减），自动动作类须显式 supersede |
| [ADR-266](ADR-266-run-failure-attribution-structured-fields-over-denoised-text.md) | accepted | run 失败归因以 AgentRunResult 结构化字段（api_error_status/conn_error）随结果对象传递、catch-all 回填，失败分类优先消费结构化字段、降噪 stderr 文本指纹仅作回退，后续车道归因禁以文本匹配为主判据 |
| [ADR-267](ADR-267-auto-freeze-narrative-rootcause-prefix-redlines.md) | accepted | 自动冻结文案按根因取专用前缀（不得自称用户指令）守三红线（保留 parse_orig_status 子串、不命中有意等待豁免形态、仍走 freeze_for_human 成对入口），FREEZE_ERROR_PREFIX 人工冻结豁免契约不可动，供给瞬态自动恢复归分类层不归文案层 |
| [ADR-268](ADR-268-orphan-disposition-convergence-signal-anchor-external-evidence-append.md) | accepted | 孤儿处置收敛侧主承力（Bash 直调不做执行时刻拦截）、滞留判据唯一锚定关联 SIGNAL 未收口（None↔"global" 归一化，disposition.handled/pending 占位不作判据）、生效核查只信 STATE/日志外部证据禁记录自证、DISPOSITION 台账一律 append 补记幂等、逐动作留痕禁携 admin_run_id 防组提前 final、升级/在飞优先于补记 |
| [ADR-269](ADR-269-repo-gate-convention-claudemd-not-hooks.md) | accepted | 仓库级门禁/约定要同时约束实现 run（worktree）与交互直改会话时载体必须是入库文件（仓库根 CLAUDE.md），不采用 git hooks（hook 不入库且对 worktree 不生效）；强制力为提示词级，机械强制走脚本加车道挂点 |
| [ADR-270](ADR-270-codefix-delivery-guard-single-entry-schedule-window-no-probe.md) | accepted | code-fix 投递守卫一律收敛在 checkpoint() 唯一入口单点判定（四路触发汇入，新增激活路禁旁路，手动授权只越 enabled 总开关不越公共守卫）；已知周期断窗用配置化时刻静默窗前置规避（窗内拒新批窗末放行、窗次幂等武装/解除留痕），不引入上游可用性主动探测，窗外瞬态仍由冷却/salvage 兜底 |
| [ADR-271](ADR-271-pluggable-agent-harness.md) | accepted | 可插拔 agent harness：车道与一次性 spawn 的命令构造唯一入口收口 adapter（协议边界在进程边界），run jsonl claude stream-json 为唯一 canon、自由会话与 CLAUDE_PID watchdog 豁免直连、worktree 目录约定字面冻结，agent.harness 选型 dispatch 前置健康检查（dsh 未部署 fail-fast）；取代 ADR-055 的「统一 headless claude -p」措辞、保留其「不实现独立 LLM 客户端」纪律 |
| [ADR-272](ADR-272-mergeback-archive-residue-proxy-commit-authorization-boundary.md) | accepted | 归档残留自愈的代理提交授权边界：同 spec 两侧成对判据（归档收口宽信号上另加校验、单侧半提交不授权）、add 限定精确残留路径禁前缀通配、spec 外脏文件一票否决恒限 spec/ 两类路径、单条至多自动尝试一次 + 补提交前重查防并发踩踏；后续框架代提交类自愈受同边界约束，放宽须显式 supersede |
| [ADR-273](ADR-273-defer-entry-single-driver-threshold-boundary.md) | accepted | 顺延条目单驱动不变式：驱动权按熔断阈值分界，未超阈值条目 Timer 链独占、周期消费者只接手无存活 Timer 的超阈值 pending 条目（与出口同判式须同源，漂移即双驱动/漏接手）、带 WIP defer 标志归 WIP 消费者车道、接手重试每条目至多一次失败维持熔断告警；新增顺延消费者须先证明目标条目无存活驱动源 |
| [ADR-274](ADR-274-host-change-rollback-alert-only-no-auto-execution.md) | accepted | 宿主变更回滚义务只告警不自动执行：义务权威载体=变更发生时即时写入的 worktree 根 host_changes.json 登记（击杀类终止无 run-result 也不丢）、失败终态含击杀类在 worktree 清理前读登记派发 admin 回滚义务告警（只增不执行、人工裁决）、成功终态仅留痕；框架自动回滚/自动快照还原方向须显式 supersede 并论证基线判定/并发互斥/失败兜底三前提 |
